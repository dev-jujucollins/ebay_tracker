import httpx
import pytest

from ebay_tracker.alerts import (
    find_deals,
    format_alert,
    is_new_deal,
    money,
    send_discord,
)
from ebay_tracker.models import Listing, WatchItem
from ebay_tracker.stats import PriceSummary
from ebay_tracker.storage import Store

ITEM = WatchItem(name="Steam Deck OLED 1TB", target_price=450.0)


def listing(listing_id: str, price: float, shipping: float | None = 0.0) -> Listing:
    return Listing(
        listing_id=listing_id,
        title="Valve Steam Deck OLED 1TB",
        price=price,
        currency="USD",
        url=f"https://www.ebay.com/itm/{listing_id}",
        shipping=shipping,
        condition="Used",
    )


def test_money_formats_known_and_unknown_currencies():
    assert money(1234.5) == "$1,234.50"
    assert money(10, "GBP") == "£10.00"
    assert money(10, "PLN") == "10.00 PLN"


def test_find_deals_counts_shipping_and_sorts_cheapest_first():
    listings = [
        listing("at-target", 450),
        listing("over-with-shipping", 440, shipping=15),
        listing("cheap", 400, shipping=20),
        listing("over", 500),
    ]

    deals = find_deals(listings, ITEM)

    assert [deal.listing_id for deal in deals] == ["cheap", "at-target"]


def test_find_deals_without_target_is_empty():
    assert find_deals([listing("a", 1)], WatchItem(name="x")) == []


def test_is_new_deal_only_realerts_on_a_price_drop():
    with Store(":memory:") as store:
        assert is_new_deal(store, ITEM, listing("a", 440))

        store.record_alert(ITEM.name, listing("a", 440))

        assert not is_new_deal(store, ITEM, listing("a", 440))
        assert not is_new_deal(store, ITEM, listing("a", 445))
        assert is_new_deal(store, ITEM, listing("a", 420))
        assert is_new_deal(store, ITEM, listing("b", 440))


def test_format_alert_includes_listing_target_and_market():
    summary = PriceSummary(count=120, low=300, p25=480, median=520, mean=530)

    message = format_alert(ITEM, listing("a", 400, shipping=20), summary)

    assert "**Steam Deck OLED 1TB** listed at **$420.00**" in message
    assert "Used · $400.00 + $20.00 shipping" in message
    assert "Target $450.00 · market median $520.00 across 120 listings" in message
    assert message.endswith("https://www.ebay.com/itm/a")


def test_format_alert_describes_free_and_unknown_shipping():
    assert "free shipping" in format_alert(ITEM, listing("a", 400), None)
    assert "shipping not stated" in format_alert(
        ITEM, listing("a", 400, shipping=None), None
    )


@pytest.mark.anyio
async def test_send_discord_posts_content():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await send_discord(http, "https://discord.test/hook", "hello")

    assert seen[0].content == b'{"content":"hello"}'


@pytest.mark.anyio
async def test_send_discord_failure_does_not_log_the_webhook_url(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert not await send_discord(http, "https://discord.test/secret-token", "hi")

    assert "secret-token" not in caplog.text
