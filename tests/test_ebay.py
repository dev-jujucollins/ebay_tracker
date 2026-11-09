import httpx
import pytest

from ebay_tracker.ebay import (
    EbayClient,
    build_filter,
    is_excluded,
    parse_listing,
)
from ebay_tracker.models import WatchItem
from tests.helpers import SETTINGS, FakeEbay, raw_listing

pytestmark = pytest.mark.anyio


def test_build_filter_defaults_to_fixed_price_only():
    assert build_filter(WatchItem(name="x"), "USD") == "buyingOptions:{FIXED_PRICE}"


def test_build_filter_combines_condition_and_price():
    item = WatchItem(name="x", condition=("new", "used"), min_price=250, max_price=900)

    assert build_filter(item, "USD", max_price=450) == (
        "buyingOptions:{FIXED_PRICE},conditionIds:{1000|3000},"
        "price:[250.00..450.00],priceCurrency:USD"
    )


def test_build_filter_open_ended_price():
    item = WatchItem(name="x", min_price=100)

    assert build_filter(item, "GBP") == (
        "buyingOptions:{FIXED_PRICE},price:[100.00..],priceCurrency:GBP"
    )


def test_is_excluded_is_case_insensitive():
    assert is_excluded("Steam Deck CASE only", ("case",))
    assert not is_excluded("Steam Deck OLED", ("case", "for parts"))
    assert not is_excluded("anything", ())


def test_parse_listing_adds_shipping_to_total():
    listing = parse_listing(raw_listing("v1|1|0", 400, shipping=12.5), "USD")

    assert listing is not None
    assert listing.price == 400.0
    assert listing.shipping == 12.5
    assert listing.total == 412.5
    assert listing.url == "https://www.ebay.com/itm/v1|1|0"


def test_parse_listing_handles_unknown_shipping():
    listing = parse_listing(raw_listing("v1|1|0", 400, shipping=None), "USD")

    assert listing is not None
    assert listing.shipping is None
    assert listing.total == 400.0


@pytest.mark.parametrize(
    "raw",
    [
        "not a dict",
        {"itemId": "1", "itemWebUrl": "u"},  # no price
        {
            "itemId": "1",
            "itemWebUrl": "u",
            "price": {"value": "abc", "currency": "USD"},
        },
        {
            "itemId": "1",
            "itemWebUrl": "u",
            "currentBidPrice": {"value": "5", "currency": "USD"},
        },
        raw_listing("v1|1|0", 400, currency="EUR"),
        {"price": {"value": "5", "currency": "USD"}},  # no id or url
    ],
)
def test_parse_listing_skips_unusable_items(raw):
    assert parse_listing(raw, "USD") is None


async def test_search_sends_filters_and_drops_excluded_titles():
    fake = FakeEbay(
        listings=[
            raw_listing("a", 500),
            raw_listing("b", 15, title="Steam Deck carrying case"),
            {
                "itemId": "c",
                "title": "auction",
                "itemWebUrl": "u",
                "currentBidPrice": {"value": "5.00", "currency": "USD"},
            },
        ]
    )
    item = WatchItem(
        name="Deck",
        query="Steam Deck OLED 1TB",
        condition=("used",),
        category_id="139971",
        exclude=("case",),
    )

    async with EbayClient(SETTINGS, http=fake.http()) as client:
        listings = await client.search_listings(item, sort="price", limit=999)

    assert [listing.listing_id for listing in listings] == ["a"]
    request = fake.searches[0]
    params = request.url.params
    assert params["q"] == "Steam Deck OLED 1TB"
    assert params["limit"] == "200"
    assert params["sort"] == "price"
    assert params["category_ids"] == "139971"
    assert params["filter"] == "buyingOptions:{FIXED_PRICE},conditionIds:{3000}"
    assert request.headers["Authorization"] == "Bearer t"
    assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"


async def test_token_is_minted_once_and_reused():
    fake = FakeEbay(listings=[raw_listing("a", 500)])

    async with EbayClient(SETTINGS, http=fake.http()) as client:
        await client.search_listings(WatchItem(name="Deck"))
        await client.search_listings(WatchItem(name="Deck"))

    assert fake.token_requests == 1
    assert len(fake.searches) == 2


async def test_rate_limit_is_retried():
    fake = FakeEbay(listings=[raw_listing("a", 500)], search_statuses=[429, 503])

    async with EbayClient(SETTINGS, http=fake.http(), retry_delay=0) as client:
        listings = await client.search_listings(WatchItem(name="Deck"))

    assert len(listings) == 1
    assert len(fake.searches) == 3


async def test_expired_token_is_refreshed_on_401():
    fake = FakeEbay(listings=[raw_listing("a", 500)], search_statuses=[401])

    async with EbayClient(SETTINGS, http=fake.http(), retry_delay=0) as client:
        listings = await client.search_listings(WatchItem(name="Deck"))

    assert len(listings) == 1
    assert fake.token_requests == 2


async def test_persistent_failure_raises_after_retries():
    fake = FakeEbay(search_statuses=[500, 500, 500])

    async with EbayClient(SETTINGS, http=fake.http(), retry_delay=0) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.search_listings(WatchItem(name="Deck"))

    assert len(fake.searches) == 3


async def test_client_error_is_not_retried():
    fake = FakeEbay(search_statuses=[400])

    async with EbayClient(SETTINGS, http=fake.http(), retry_delay=0) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.search_listings(WatchItem(name="Deck"))

    assert len(fake.searches) == 1
