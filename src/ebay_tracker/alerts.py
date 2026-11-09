"""Deciding which listings deserve an alert, and sending it to Discord."""

import logging

import httpx

from ebay_tracker.models import Listing, WatchItem
from ebay_tracker.stats import PriceSummary
from ebay_tracker.storage import Store

logger = logging.getLogger(__name__)

MAX_ALERTS_PER_ITEM = 3
_CURRENCY_SYMBOLS = {"USD": "$", "CAD": "CA$", "AUD": "A$", "GBP": "£", "EUR": "€"}


def money(amount: float, currency: str = "USD") -> str:
    symbol = _CURRENCY_SYMBOLS.get(currency)
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency}"


def find_deals(listings: list[Listing], item: WatchItem) -> list[Listing]:
    """Listings whose price plus shipping is at or under target, cheapest first."""
    if item.target_price is None:
        return []
    deals = [listing for listing in listings if listing.total <= item.target_price]
    return sorted(deals, key=lambda listing: listing.total)


def is_new_deal(store: Store, item: WatchItem, listing: Listing) -> bool:
    """True if we never alerted on this listing, or its price dropped since."""
    last_price = store.last_alert_price(item.name, listing.listing_id)
    return last_price is None or listing.total < last_price - 0.005


def format_alert(
    item: WatchItem, listing: Listing, summary: PriceSummary | None
) -> str:
    """Build the Discord message for one listing."""
    currency = listing.currency
    lines = [
        f"🔔 **{item.name}** listed at **{money(listing.total, currency)}**",
        listing.title,
    ]

    details = []
    if listing.condition:
        details.append(listing.condition)
    if listing.shipping:
        details.append(
            f"{money(listing.price, currency)} + "
            f"{money(listing.shipping, currency)} shipping"
        )
    elif listing.shipping is None:
        details.append("shipping not stated")
    else:
        details.append("free shipping")
    lines.append(" · ".join(details))

    if item.target_price is not None:
        target_line = f"Target {money(item.target_price, currency)}"
        if summary is not None:
            target_line += (
                f" · market median {money(summary.median, currency)} "
                f"across {summary.count} listings"
            )
        lines.append(target_line)

    lines.append(listing.url)
    return "\n".join(lines)


async def send_discord(http: httpx.AsyncClient, webhook_url: str, content: str) -> bool:
    """POST a message to a Discord webhook. Returns True on success."""
    try:
        response = await http.post(webhook_url, json={"content": content[:2000]})
        response.raise_for_status()
    except httpx.HTTPError as error:
        # Do not log the exception text: it contains the secret webhook URL.
        logger.error("Discord webhook failed (%s)", type(error).__name__)
        return False
    return True
