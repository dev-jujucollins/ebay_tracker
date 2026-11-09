from datetime import datetime, timezone
from pathlib import Path

import pytest

from ebay_tracker import cli
from ebay_tracker.stats import PriceSummary
from ebay_tracker.storage import Store


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch):
    """Keep the real .env and environment variables out of CLI tests."""
    monkeypatch.chdir(tmp_path)
    for key in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_TRACKER_DB"):
        monkeypatch.delenv(key, raising=False)


def run_cli(*argv: str) -> int:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(list(argv))
    return int(exit_info.value.code or 0)


def test_history_without_database(capsys):
    assert run_cli("history") == 1
    assert "No history yet" in capsys.readouterr().out


def test_history_lists_items_and_shows_checks(tmp_path: Path, capsys):
    db = tmp_path / "t.db"
    with Store(db) as store:
        store.record_check(
            "Steam Deck",
            PriceSummary(count=42, low=300, p25=450, median=500, mean=510),
            datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc),
        )

    assert run_cli("--db", str(db), "history") == 0
    assert "Steam Deck  (1 checks" in capsys.readouterr().out

    assert run_cli("--db", str(db), "history", "steam", "deck") == 0
    output = capsys.readouterr().out
    assert "2026-11-01 12:00:00" in output
    assert "$500.00" in output

    assert run_cli("--db", str(db), "history", "nope") == 1


def test_watch_without_credentials_exits_with_config_error(caplog):
    assert run_cli("watch") == 2
    assert "EBAY_CLIENT_ID" in caplog.text


def test_watch_with_missing_watchlist_exits_with_config_error(monkeypatch, caplog):
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")

    assert run_cli("watch", "--watchlist", "missing.yaml") == 2
    assert "not found" in caplog.text


def test_check_requires_a_name():
    assert run_cli("check") == 2


def test_every_must_be_positive():
    assert run_cli("watch", "--every", "0") == 2
