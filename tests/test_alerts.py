"""Tests for the alerts module."""

from pathlib import Path

from alerts import (
    WatchlistItem,
    check_price_alert,
    load_watchlist,
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
