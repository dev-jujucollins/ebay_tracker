import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ebay_tracker.models import Listing
from ebay_tracker.stats import PriceSummary
from ebay_tracker.storage import Store


def summary(median: float) -> PriceSummary:
    return PriceSummary(
        count=10, low=median - 50, p25=median - 20, median=median, mean=median
    )


def listing(price: float, listing_id: str = "v1|1|0") -> Listing:
    return Listing(
        listing_id=listing_id,
        title="Steam Deck",
        price=price,
        currency="USD",
        url="https://www.ebay.com/itm/1",
    )


def test_history_is_newest_first_and_case_insensitive():
    now = datetime.now(timezone.utc)
    with Store(":memory:") as store:
        store.record_check("Steam Deck", summary(500), now - timedelta(days=2))
        store.record_check("steam deck", summary(480), now - timedelta(days=1))
        store.record_check("Other", summary(10), now)

        rows = store.history("STEAM DECK")

        assert [row.median for row in rows] == [480, 500]
        assert rows[0].sample_size == 10
        assert [item.name for item in store.items()] == ["Other", "Steam Deck"]
        assert store.history("Steam Deck", limit=1)[0].median == 480


def test_lowest_median_respects_window():
    now = datetime.now(timezone.utc)
    with Store(":memory:") as store:
        store.record_check("Deck", summary(300), now - timedelta(days=90))
        store.record_check("Deck", summary(450), now - timedelta(days=5))
        store.record_check("Deck", summary(470), now)

        assert store.lowest_median("Deck", days=30) == 450
        assert store.lowest_median("Deck", days=365) == 300
        assert store.lowest_median("Unknown") is None


def test_alerts_persist_across_connections(tmp_path: Path):
    path = tmp_path / "nested" / "tracker.db"
    with Store(path) as store:
        assert store.last_alert_price("Deck", "v1|1|0") is None
        store.record_alert("Deck", listing(400))
        store.record_alert("Deck", listing(380))

    with Store(path) as store:
        assert store.last_alert_price("Deck", "v1|1|0") == 380
        assert store.last_alert_price("Deck", "v1|2|0") is None
        assert store.last_alert_price("Other", "v1|1|0") is None


def test_database_with_legacy_kind_column_is_upgraded(tmp_path: Path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
        CREATE TABLE checks (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
            checked_at TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('listed', 'sold')),
            sample_size INTEGER NOT NULL, low REAL NOT NULL, p25 REAL NOT NULL,
            median REAL NOT NULL, mean REAL NOT NULL
        );
        CREATE INDEX idx_checks_item_time ON checks (item_id, checked_at);
        INSERT INTO items VALUES (1, 'Deck');
        INSERT INTO checks VALUES (1, 1, '2026-11-09T22:30:31+00:00', 'listed',
                                   200, 450, 750, 807, 820);
        INSERT INTO checks VALUES (2, 1, '2026-11-09T22:30:32+00:00', 'sold',
                                   50, 300, 400, 420, 430);
        """
    )
    old.close()

    with Store(path) as store:
        store.record_check("Deck", summary(790))

        assert [row.median for row in store.history("Deck")] == [790, 807]
