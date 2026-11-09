"""SQLite storage for price history and sent alerts."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ebay_tracker.models import Listing
from ebay_tracker.stats import PriceSummary

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY,
    item_id     INTEGER NOT NULL REFERENCES items(id),
    checked_at  TEXT    NOT NULL,
    sample_size INTEGER NOT NULL,
    low         REAL    NOT NULL,
    p25         REAL    NOT NULL,
    median      REAL    NOT NULL,
    mean        REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checks_item_time ON checks (item_id, checked_at);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL REFERENCES items(id),
    listing_id TEXT    NOT NULL,
    alerted_at TEXT    NOT NULL,
    price      REAL    NOT NULL,
    title      TEXT    NOT NULL,
    url        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_item_listing ON alerts (item_id, listing_id);
"""


@dataclass(frozen=True)
class CheckRow:
    checked_at: str
    sample_size: int
    low: float
    p25: float
    median: float
    mean: float


@dataclass(frozen=True)
class ItemRow:
    name: str
    checks: int
    last_checked_at: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    """UTC ISO-8601 text, which sorts correctly as a plain string."""
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


class Store:
    """Thin wrapper around one SQLite connection."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._drop_legacy_kind_column()
        self._db.executescript(SCHEMA)
        self._db.commit()

    def _drop_legacy_kind_column(self) -> None:
        """Upgrade databases created by 0.2.0, which also stored sold prices."""
        columns = [row[1] for row in self._db.execute("PRAGMA table_info(checks)")]
        if "kind" not in columns:
            return
        self._db.executescript(
            """
            BEGIN;
            DROP INDEX IF EXISTS idx_checks_item_time;
            ALTER TABLE checks RENAME TO checks_legacy;
            CREATE TABLE checks (
                id          INTEGER PRIMARY KEY,
                item_id     INTEGER NOT NULL REFERENCES items(id),
                checked_at  TEXT    NOT NULL,
                sample_size INTEGER NOT NULL,
                low         REAL    NOT NULL,
                p25         REAL    NOT NULL,
                median      REAL    NOT NULL,
                mean        REAL    NOT NULL
            );
            INSERT INTO checks
                SELECT id, item_id, checked_at, sample_size, low, p25, median, mean
                FROM checks_legacy WHERE kind = 'listed';
            DROP TABLE checks_legacy;
            COMMIT;
            """
        )

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def _item_id(self, name: str) -> int:
        self._db.execute("INSERT OR IGNORE INTO items (name) VALUES (?)", (name,))
        row = self._db.execute(
            "SELECT id FROM items WHERE name = ?", (name,)
        ).fetchone()
        return int(row[0])

    def record_check(
        self,
        name: str,
        summary: PriceSummary,
        when: datetime | None = None,
    ) -> None:
        """Save one price snapshot for an item."""
        self._db.execute(
            "INSERT INTO checks "
            "(item_id, checked_at, sample_size, low, p25, median, mean) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self._item_id(name),
                _stamp(when or _now()),
                summary.count,
                summary.low,
                summary.p25,
                summary.median,
                summary.mean,
            ),
        )
        self._db.commit()

    def record_alert(
        self, name: str, listing: Listing, when: datetime | None = None
    ) -> None:
        """Remember that we alerted on this listing at this price."""
        self._db.execute(
            "INSERT INTO alerts (item_id, listing_id, alerted_at, price, title, url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                self._item_id(name),
                listing.listing_id,
                _stamp(when or _now()),
                listing.total,
                listing.title,
                listing.url,
            ),
        )
        self._db.commit()

    def last_alert_price(self, name: str, listing_id: str) -> float | None:
        """Lowest price we have already alerted on for this listing, if any."""
        row = self._db.execute(
            "SELECT MIN(a.price) FROM alerts a "
            "JOIN items i ON i.id = a.item_id "
            "WHERE i.name = ? AND a.listing_id = ?",
            (name, listing_id),
        ).fetchone()
        return None if row[0] is None else float(row[0])

    def history(self, name: str, limit: int = 20) -> list[CheckRow]:
        """Most recent checks for an item, newest first."""
        rows = self._db.execute(
            "SELECT c.checked_at, c.sample_size, c.low, c.p25, "
            "c.median, c.mean "
            "FROM checks c JOIN items i ON i.id = c.item_id "
            "WHERE i.name = ? "
            "ORDER BY c.checked_at DESC, c.id DESC LIMIT ?",
            (name, limit),
        ).fetchall()
        return [CheckRow(*row) for row in rows]

    def lowest_median(self, name: str, days: int = 30) -> float | None:
        """Lowest recorded median for an item over the last ``days`` days."""
        since = _stamp(_now() - timedelta(days=days))
        row = self._db.execute(
            "SELECT MIN(c.median) FROM checks c "
            "JOIN items i ON i.id = c.item_id "
            "WHERE i.name = ? AND c.checked_at >= ?",
            (name, since),
        ).fetchone()
        return None if row[0] is None else float(row[0])

    def items(self) -> list[ItemRow]:
        """Every tracked item with how often and how recently it was checked."""
        rows = self._db.execute(
            "SELECT i.name, COUNT(c.id), MAX(c.checked_at) "
            "FROM items i LEFT JOIN checks c ON c.item_id = i.id "
            "GROUP BY i.id ORDER BY i.name"
        ).fetchall()
        return [ItemRow(*row) for row in rows]
