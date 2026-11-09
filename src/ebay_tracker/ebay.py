"""Async client for the eBay Browse API."""

import asyncio
import logging
import time
from typing import Any

import httpx

from ebay_tracker.config import Settings
from ebay_tracker.models import Listing, WatchItem

logger = logging.getLogger(__name__)

API_SCOPE = "https://api.ebay.com/oauth/api_scope"
TOKEN_PATH = "/identity/v1/oauth2/token"
BROWSE_SEARCH_PATH = "/buy/browse/v1/item_summary/search"
MAX_PAGE_SIZE = 200
TOKEN_SKEW_SECONDS = 60
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3

# Friendly condition names accepted in the watchlist -> eBay condition IDs.
CONDITION_IDS = {
    "new": "1000",
    "open_box": "1500",
    "certified_refurbished": "2000",
    "seller_refurbished": "2500",
    "used": "3000",
    "for_parts": "7000",
}


class EbayApiError(Exception):
    """eBay returned something we cannot use."""


def build_filter(
    item: WatchItem, currency: str, *, max_price: float | None = None
) -> str:
    """Build the eBay ``filter`` query parameter for a watch item.

    Pure auctions are always dropped: a current bid says nothing about what
    the item will actually sell for.
    """
    parts = ["buyingOptions:{FIXED_PRICE}"]

    if item.condition:
        ids = "|".join(CONDITION_IDS[name] for name in item.condition)
        parts.append(f"conditionIds:{{{ids}}}")

    low = item.min_price
    high = item.max_price
    if max_price is not None:
        high = max_price if high is None else min(high, max_price)
    if low is not None or high is not None:
        low_text = f"{low:.2f}" if low is not None else ""
        high_text = f"{high:.2f}" if high is not None else ""
        parts.append(f"price:[{low_text}..{high_text}]")
        parts.append(f"priceCurrency:{currency}")

    return ",".join(parts)


def is_excluded(title: str, exclude: tuple[str, ...]) -> bool:
    """Return True when the title contains any exclude phrase (case-insensitive)."""
    folded = title.casefold()
    return any(term.casefold() in folded for term in exclude)


def _money(value: Any) -> tuple[float, str] | None:
    """Turn an eBay money object into (amount, currency)."""
    if not isinstance(value, dict):
        return None
    try:
        amount = float(value["value"])
    except (KeyError, TypeError, ValueError):
        return None
    currency = value.get("currency")
    return amount, currency if isinstance(currency, str) else ""


def parse_listing(raw: Any, currency: str) -> Listing | None:
    """Convert one Browse API item summary, skipping anything incomplete."""
    if not isinstance(raw, dict):
        return None

    price = _money(raw.get("price"))
    listing_id = raw.get("itemId")
    url = raw.get("itemWebUrl")
    if price is None or price[1] != currency:
        return None
    if not isinstance(listing_id, str) or not isinstance(url, str):
        return None

    shipping: float | None = None
    options = raw.get("shippingOptions")
    if isinstance(options, list) and options and isinstance(options[0], dict):
        cost = _money(options[0].get("shippingCost"))
        if cost is not None:
            shipping = cost[0]

    title = raw.get("title")
    condition = raw.get("condition")
    return Listing(
        listing_id=listing_id,
        title=title if isinstance(title, str) else "",
        price=price[0],
        currency=currency,
        url=url,
        shipping=shipping,
        condition=condition if isinstance(condition, str) else None,
    )


class EbayClient:
    """Small eBay API client. One instance shares a connection pool and token."""

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        retry_delay: float = 2.0,
    ) -> None:
        self._settings = settings
        self._http = http or httpx.AsyncClient(timeout=20.0)
        self._owns_http = http is None
        self._retry_delay = retry_delay
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> "EbayClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _get_token(self) -> str:
        """Return a cached application token, minting a new one when needed."""
        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token

            response = await self._http.post(
                f"{self._settings.api_base_url}{TOKEN_PATH}",
                auth=(self._settings.client_id, self._settings.client_secret),
                data={"grant_type": "client_credentials", "scope": API_SCOPE},
            )
            response.raise_for_status()
            data = response.json()
            token = data.get("access_token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                raise EbayApiError("eBay OAuth response did not include access_token")

            try:
                lifetime = float(data.get("expires_in", 7200))
            except (TypeError, ValueError):
                lifetime = 7200.0
            self._token = token
            self._token_expires_at = time.monotonic() + lifetime - TOKEN_SKEW_SECONDS
            return token

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        """GET a Buy API endpoint, retrying rate limits and transient failures."""
        url = f"{self._settings.api_base_url}{path}"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last_attempt = attempt == MAX_ATTEMPTS
            token = await self._get_token()
            try:
                response = await self._http.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "X-EBAY-C-MARKETPLACE-ID": self._settings.marketplace,
                    },
                )
            except httpx.TransportError as error:
                if last_attempt:
                    raise
                reason = type(error).__name__
            else:
                if response.status_code == 401 and not last_attempt:
                    self._token = None  # token was revoked early; mint a new one
                    continue
                if response.status_code not in RETRY_STATUSES or last_attempt:
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict):
                        raise EbayApiError(f"Unexpected response body from {path}")
                    return data
                reason = f"HTTP {response.status_code}"

            delay = self._retry_delay * 2 ** (attempt - 1)
            logger.warning(
                "eBay request failed (%s), retry %d/%d in %.0fs",
                reason,
                attempt,
                MAX_ATTEMPTS - 1,
                delay,
            )
            await asyncio.sleep(delay)

        raise AssertionError("unreachable")  # pragma: no cover

    async def search_listings(
        self,
        item: WatchItem,
        *,
        limit: int = MAX_PAGE_SIZE,
        sort: str | None = None,
        max_price: float | None = None,
    ) -> list[Listing]:
        """Search active fixed-price listings that pass the item's filters."""
        params = {
            "q": item.search_query,
            "limit": str(min(limit, MAX_PAGE_SIZE)),
            "filter": build_filter(item, self._settings.currency, max_price=max_price),
        }
        if item.category_id:
            params["category_ids"] = item.category_id
        if sort:
            params["sort"] = sort

        data = await self._get(BROWSE_SEARCH_PATH, params)
        summaries = data.get("itemSummaries")
        if not isinstance(summaries, list):
            return []

        listings = (parse_listing(raw, self._settings.currency) for raw in summaries)
        return [
            listing
            for listing in listings
            if listing is not None and not is_excluded(listing.title, item.exclude)
        ]
