"""Tests for the alerts module."""

import asyncio
from pathlib import Path

import pytest

from alerts import (
    WatchlistConfig,
    WatchlistItem,
    build_webhook_payload,
    check_price_alert,
    check_item_with_semaphore,
    dispatch_alerts,
    load_watchlist,
    process_watchlist,
    run_watch_mode,
)


class TestCheckPriceAlert:
    """Tests for check_price_alert function."""

    def test_price_below_target_triggers_alert(self):
        """Alert should trigger when price is below target."""
        item = WatchlistItem(name="Test Item", target_price=500.0)
        result = check_price_alert(item, current_price=450.0)

        assert result.is_below_target is True
        assert result.current_price == 450.0
        assert result.price_difference == -50.0  # 450 - 500 = -50

    def test_price_above_target_no_alert(self):
        """No alert when price is above target."""
        item = WatchlistItem(name="Test Item", target_price=500.0)
        result = check_price_alert(item, current_price=550.0)

        assert result.is_below_target is False
        assert result.current_price == 550.0
        assert result.price_difference == 50.0  # 550 - 500 = 50

    def test_price_equals_target_triggers_alert(self):
        """Alert should trigger when price equals target."""
        item = WatchlistItem(name="Test Item", target_price=500.0)
        result = check_price_alert(item, current_price=500.0)

        assert result.is_below_target is True
        assert result.price_difference == 0.0

    def test_none_price_no_alert(self):
        """No alert when price fetch failed (None)."""
        item = WatchlistItem(name="Test Item", target_price=500.0)
        result = check_price_alert(item, current_price=None)

        assert result.is_below_target is False
        assert result.current_price is None
        assert result.price_difference == 0.0


class TestLoadWatchlist:
    """Tests for load_watchlist function."""

    def test_load_valid_watchlist(self, tmp_path: Path):
        """Should load a valid watchlist YAML file."""
        watchlist_content = """
webhook_url: "https://example.com/webhook"
items:
  - name: "Nintendo Switch"
    target_price: 300.00
  - name: "PS5"
    target_price: 400.00
    check_sold: true
"""
        watchlist_path = tmp_path / "watchlist.yaml"
        watchlist_path.write_text(watchlist_content)

        config = load_watchlist(str(watchlist_path))

        assert config is not None
        assert config.webhook_url == "https://example.com/webhook"
        assert len(config.items) == 2
        assert config.items[0].name == "Nintendo Switch"
        assert config.items[0].target_price == 300.0
        assert config.items[0].check_sold is False
        assert config.items[1].name == "PS5"
        assert config.items[1].check_sold is True

    def test_load_watchlist_without_webhook(self, tmp_path: Path):
        """Should load watchlist without webhook URL."""
        watchlist_content = """
items:
  - name: "Test Item"
    target_price: 100.00
"""
        watchlist_path = tmp_path / "watchlist.yaml"
        watchlist_path.write_text(watchlist_content)

        config = load_watchlist(str(watchlist_path))

        assert config is not None
        assert config.webhook_url is None
        assert len(config.items) == 1

    def test_load_nonexistent_watchlist(self):
        """Should return None for nonexistent file."""
        config = load_watchlist("nonexistent_file.yaml")
        assert config is None

    def test_load_invalid_yaml(self, tmp_path: Path):
        """Should return None for invalid YAML."""
        watchlist_path = tmp_path / "watchlist.yaml"
        watchlist_path.write_text("invalid: yaml: content: [")

        config = load_watchlist(str(watchlist_path))
        assert config is None

    def test_load_empty_watchlist(self, tmp_path: Path):
        """Should return None for empty YAML content."""
        watchlist_path = tmp_path / "watchlist.yaml"
        watchlist_path.write_text("")

        config = load_watchlist(str(watchlist_path))
        assert config is None

    def test_load_watchlist_with_non_mapping_top_level(self, tmp_path: Path):
        """Should return None when YAML top level is not a mapping."""
        watchlist_path = tmp_path / "watchlist.yaml"
        watchlist_path.write_text("- name: Test Item\n")

        config = load_watchlist(str(watchlist_path))
        assert config is None

    def test_load_watchlist_with_invalid_target_price(self, tmp_path: Path):
        """Should return None when target_price is not numeric."""
        watchlist_path = tmp_path / "watchlist.yaml"
        watchlist_path.write_text(
            """
items:
  - name: "Bad Item"
    target_price: nope
"""
        )

        config = load_watchlist(str(watchlist_path))
        assert config is None


class TestWatchlistItem:
    """Tests for WatchlistItem dataclass."""

    def test_default_check_sold(self):
        """check_sold should default to False."""
        item = WatchlistItem(name="Test", target_price=100.0)
        assert item.check_sold is False

    def test_explicit_check_sold(self):
        """check_sold can be set explicitly."""
        item = WatchlistItem(name="Test", target_price=100.0, check_sold=True)
        assert item.check_sold is True


@pytest.mark.anyio
async def test_check_item_with_semaphore_handles_fetch_failure(mocker):
    """Fetch exceptions should not abort item processing."""
    item = WatchlistItem(name="Broken Item", target_price=100.0)
    mocker.patch("alerts.fetch_item_price", side_effect=RuntimeError("boom"))

    result = await check_item_with_semaphore(item, semaphore=asyncio.Semaphore(1))

    assert result.item == item
    assert result.current_price is None
    assert result.is_below_target is False


@pytest.mark.anyio
async def test_process_watchlist_continues_after_single_item_failure(mocker):
    """One item failure should not abort rest of watchlist."""
    item_ok = WatchlistItem(name="Good Item", target_price=100.0)
    item_bad = WatchlistItem(name="Bad Item", target_price=100.0)
    config = WatchlistConfig(webhook_url=None, items=[item_bad, item_ok])

    async def fake_fetch(item: WatchlistItem) -> float:
        if item.name == "Bad Item":
            raise RuntimeError("boom")
        return 90.0

    mocker.patch("alerts.fetch_item_price", side_effect=fake_fetch)

    results = await process_watchlist(config, max_concurrent=2)

    assert len(results) == 2
    by_name = {result.item.name: result for result in results}
    assert by_name["Bad Item"].current_price is None
    assert by_name["Bad Item"].is_below_target is False
    assert by_name["Good Item"].current_price == 90.0
    assert by_name["Good Item"].is_below_target is True


def test_build_webhook_payload_uses_discord_content_field():
    """Webhook payload should use Discord content field."""
    result = check_price_alert(
        WatchlistItem(name="Switch 2", target_price=500.0),
        current_price=450.0,
    )

    payload = build_webhook_payload(result)

    assert "content" in payload
    assert "text" not in payload


@pytest.mark.anyio
async def test_dispatch_alerts_dedupes_until_price_recovers(mocker):
    """Repeat below-target results should not resend until item recovers."""
    alert_result = check_price_alert(
        WatchlistItem(name="Switch 2", target_price=500.0),
        current_price=450.0,
    )
    recovered_result = check_price_alert(alert_result.item, current_price=550.0)

    log_alert = mocker.patch("alerts.log_alert_to_file")
    send_webhook = mocker.patch("alerts.send_webhook_alert", return_value=True)

    active_alerts = await dispatch_alerts(
        [alert_result],
        "https://discord.com/api/webhooks/123/token",
    )
    active_alerts = await dispatch_alerts(
        [alert_result],
        "https://discord.com/api/webhooks/123/token",
        active_alerts=active_alerts,
    )
    active_alerts = await dispatch_alerts(
        [recovered_result],
        "https://discord.com/api/webhooks/123/token",
        active_alerts=active_alerts,
    )
    await dispatch_alerts(
        [alert_result],
        "https://discord.com/api/webhooks/123/token",
        active_alerts=active_alerts,
    )

    assert log_alert.call_count == 2
    assert send_webhook.await_count == 2


@pytest.mark.anyio
async def test_run_watch_mode_run_once_stops_after_first_cycle(mocker):
    """run_once should execute one cycle and exit."""
    run_cycle = mocker.patch(
        "alerts.run_watch_cycle",
        return_value=(None, [], set()),
    )
    sleep = mocker.patch("alerts.asyncio.sleep")

    await run_watch_mode("watchlist.yaml", interval_seconds=5.0, run_once=True)

    run_cycle.assert_awaited_once()
    sleep.assert_not_called()


@pytest.mark.anyio
async def test_run_watch_mode_repeats_when_not_run_once(mocker):
    """Continuous watch mode should loop between sleeps."""
    state = {"calls": 0}

    async def fake_run_watch_cycle(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] >= 2:
            raise asyncio.CancelledError()
        return None, [], set()

    sleep = mocker.patch("alerts.asyncio.sleep", return_value=None)
    mocker.patch("alerts.run_watch_cycle", side_effect=fake_run_watch_cycle)

    with pytest.raises(asyncio.CancelledError):
        await run_watch_mode("watchlist.yaml", interval_seconds=5.0, run_once=False)

    assert state["calls"] == 2
    sleep.assert_awaited_once_with(5.0)
