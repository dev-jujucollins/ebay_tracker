"""Shared fakes: an in-memory eBay API built on httpx.MockTransport."""

from typing import Any

import httpx

from ebay_tracker.config import Settings

SETTINGS = Settings(client_id="id", client_secret="secret")


def raw_listing(
    listing_id: str,
    price: float,
    title: str = "Steam Deck OLED 1TB",
    shipping: float | None = 0.0,
    currency: str = "USD",
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "itemId": listing_id,
        "title": title,
        "price": {"value": f"{price:.2f}", "currency": currency},
        "itemWebUrl": f"https://www.ebay.com/itm/{listing_id}",
        "condition": "Used",
    }
    if shipping is not None:
        raw["shippingOptions"] = [
            {"shippingCost": {"value": f"{shipping:.2f}", "currency": currency}}
        ]
    return raw


def _price(raw: dict[str, Any]) -> float:
    return float(raw.get("price", {}).get("value", 0))


class FakeEbay:
    """Answers token and Browse search requests."""

    def __init__(
        self,
        listings: list[dict[str, Any]] | None = None,
        search_statuses: list[int] | None = None,
    ) -> None:
        self.listings = listings or []
        self.search_statuses = search_statuses or []  # consumed before success
        self.token_requests = 0
        self.searches: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth2/token"):
            self.token_requests += 1
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})

        if path.endswith("/item_summary/search"):
            self.searches.append(request)
            if self.search_statuses:
                return httpx.Response(self.search_statuses.pop(0), json={})
            listings = self.listings
            if request.url.params.get("sort") == "price":
                listings = sorted(listings, key=_price)
            return httpx.Response(200, json={"itemSummaries": listings})

        return httpx.Response(404)

    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
