"""Run price checks for a list of items: search, summarize, store, alert."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from ebay_tracker.alerts import (
    MAX_ALERTS_PER_ITEM,
    find_deals,
    format_alert,
    is_new_deal,
)
from ebay_tracker.ebay import EbayApiError, EbayClient
from ebay_tracker.models import Listing, WatchItem
from ebay_tracker.stats import PriceSummary, summarize
from ebay_tracker.storage import Store

logger = logging.getLogger(__name__)

CHEAPEST_SAMPLE_SIZE = 50
Notifier = Callable[[str], Awaitable[bool]]


@dataclass
class ItemReport:
    """What one check of one item found."""

    item: WatchItem
    summary: PriceSummary | None = None
    cheapest: list[Listing] = field(default_factory=list)
    deals: list[Listing] = field(default_factory=list)
    new_deals: list[Listing] = field(default_factory=list)
    error: str | None = None


class Tracker:
    def __init__(
        self,
        client: EbayClient,
        store: Store,
        notify: Notifier | None = None,
        max_concurrent: int = 3,
    ) -> None:
        self._client = client
        self._store = store
        self._notify = notify
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def run(
        self, items: list[WatchItem], *, alert: bool = True
    ) -> list[ItemReport]:
        """Check every item concurrently. One failing item never stops the rest."""
        return list(
            await asyncio.gather(*(self._check_guarded(item, alert) for item in items))
        )

    async def _check_guarded(self, item: WatchItem, alert: bool) -> ItemReport:
        async with self._semaphore:
            try:
                return await self._check(item, alert)
            except (httpx.HTTPError, EbayApiError) as error:
                message = _describe(error)
                logger.error("%s: check failed: %s", item.name, message)
                return ItemReport(item=item, error=message)

    async def _check(self, item: WatchItem, alert: bool) -> ItemReport:
        report = ItemReport(item=item)

        # 1. A broad sample of the market, for the median and history.
        market = await self._client.search_listings(item)
        report.summary = summarize([listing.total for listing in market])
        if report.summary is not None:
            self._store.record_check(item.name, report.summary)

        # 2. The cheapest matching listings, capped at the target price.
        cheapest = await self._client.search_listings(
            item,
            limit=CHEAPEST_SAMPLE_SIZE,
            sort="price",
            max_price=item.target_price,
        )
        report.cheapest = sorted(cheapest, key=lambda listing: listing.total)
        report.deals = find_deals(report.cheapest, item)

        if alert:
            await self._send_alerts(report)
        return report

    async def _send_alerts(self, report: ItemReport) -> None:
        item = report.item
        fresh = [deal for deal in report.deals if is_new_deal(self._store, item, deal)]
        for listing in fresh[:MAX_ALERTS_PER_ITEM]:
            message = format_alert(item, listing, report.summary)
            logger.info("ALERT %s", message.replace("\n", " | "))
            if self._notify is not None and not await self._notify(message):
                continue  # not recorded, so the next run tries again
            self._store.record_alert(item.name, listing)
            report.new_deals.append(listing)


def _describe(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code} from eBay"
    return f"{type(error).__name__}: {error}"
