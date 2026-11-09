import pytest

from ebay_tracker.ebay import EbayClient
from ebay_tracker.models import WatchItem
from ebay_tracker.storage import Store
from ebay_tracker.tracker import Tracker
from tests.helpers import SETTINGS, FakeEbay, raw_listing

pytestmark = pytest.mark.anyio

ITEM = WatchItem(name="Deck", target_price=450.0, exclude=("case",))
MARKET = [
    raw_listing("cheap", 400, shipping=20),
    raw_listing("mid", 500),
    raw_listing("high", 600),
    raw_listing("junk", 15, title="Steam Deck case"),
]


class Recorder:
    """Stands in for the Discord notifier."""

    def __init__(self, succeed: bool = True) -> None:
        self.messages: list[str] = []
        self.succeed = succeed

    async def __call__(self, message: str) -> bool:
        self.messages.append(message)
        return self.succeed


async def run(fake: FakeEbay, store: Store, notify=None, items=None, alert=True):
    async with EbayClient(SETTINGS, http=fake.http(), retry_delay=0) as client:
        return await Tracker(client, store, notify).run(items or [ITEM], alert=alert)


async def test_check_records_median_and_alerts_on_the_listing():
    fake, notify = FakeEbay(listings=MARKET), Recorder()
    with Store(":memory:") as store:
        [report] = await run(fake, store, notify)

        assert report.error is None
        assert report.summary is not None
        assert report.summary.count == 3  # the case is excluded
        assert report.summary.median == 500.0
        assert [deal.listing_id for deal in report.deals] == ["cheap"]
        assert [deal.listing_id for deal in report.new_deals] == ["cheap"]
        assert len(notify.messages) == 1
        assert "$420.00" in notify.messages[0]
        assert store.history("Deck")[0].median == 500.0
        assert store.last_alert_price("Deck", "cheap") == 420.0

    deal_search = fake.searches[1].url.params
    assert deal_search["sort"] == "price"
    assert "price:[..450.00]" in deal_search["filter"]


async def test_second_run_does_not_repeat_the_alert():
    fake, notify = FakeEbay(listings=MARKET), Recorder()
    with Store(":memory:") as store:
        await run(fake, store, notify)
        [report] = await run(fake, store, notify)

        assert len(report.deals) == 1
        assert report.new_deals == []
        assert len(notify.messages) == 1
        assert len(store.history("Deck")) == 2  # history still grows


async def test_failed_webhook_is_retried_next_run():
    fake = FakeEbay(listings=MARKET)
    with Store(":memory:") as store:
        [failed] = await run(fake, store, Recorder(succeed=False))
        assert failed.new_deals == []
        assert store.last_alert_price("Deck", "cheap") is None

        notify = Recorder()
        [report] = await run(fake, store, notify)
        assert len(report.new_deals) == 1
        assert len(notify.messages) == 1


async def test_alerts_are_recorded_without_a_webhook():
    with Store(":memory:") as store:
        [report] = await run(FakeEbay(listings=MARKET), store, notify=None)

        assert len(report.new_deals) == 1
        assert store.last_alert_price("Deck", "cheap") == 420.0


async def test_alert_false_records_history_but_sends_nothing():
    notify = Recorder()
    with Store(":memory:") as store:
        [report] = await run(FakeEbay(listings=MARKET), store, notify, alert=False)

        assert len(report.deals) == 1
        assert notify.messages == []
        assert store.last_alert_price("Deck", "cheap") is None
        assert len(store.history("Deck")) == 1


async def test_at_most_three_alerts_per_item_per_run():
    listings = [raw_listing(f"deal-{n}", 300 + n) for n in range(5)]
    notify = Recorder()
    with Store(":memory:") as store:
        [report] = await run(FakeEbay(listings=listings), store, notify)

        assert len(report.deals) == 5
        assert [deal.listing_id for deal in report.new_deals] == [
            "deal-0",
            "deal-1",
            "deal-2",
        ]


async def test_api_failure_is_reported_and_other_items_continue():
    fake = FakeEbay(listings=MARKET, search_statuses=[400])
    items = [WatchItem(name="Broken", target_price=1.0), ITEM]
    with Store(":memory:") as store:
        async with EbayClient(SETTINGS, http=fake.http(), retry_delay=0) as client:
            tracker = Tracker(client, store, max_concurrent=1)
            broken, ok = await tracker.run(items)

    assert broken.error == "HTTP 400 from eBay"
    assert ok.error is None
    assert ok.summary is not None


async def test_no_listings_records_nothing():
    with Store(":memory:") as store:
        [report] = await run(FakeEbay(), store)

        assert report.summary is None
        assert report.deals == []
        assert store.history("Deck") == []
