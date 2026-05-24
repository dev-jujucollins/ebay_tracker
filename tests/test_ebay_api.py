"""Tests for eBay API helpers."""

from pathlib import Path

from ebay_api import (
    get_ebay_api_config,
    load_env_file,
    parse_browse_prices,
    parse_sold_prices,
)


def test_load_env_file_reads_simple_values(tmp_path: Path, monkeypatch):
    """Env loader should read simple KEY=VALUE pairs."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        """
EBAY_CLIENT_ID=abc
EBAY_CLIENT_SECRET="secret value"
EBAY_ENVIRONMENT=sandbox
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    assert load_env_file() == {
        "EBAY_CLIENT_ID": "abc",
        "EBAY_CLIENT_SECRET": "secret value",
        "EBAY_ENVIRONMENT": "sandbox",
    }


def test_get_ebay_api_config_returns_none_without_credentials(
    tmp_path: Path, monkeypatch
):
    """Missing credentials should leave API integration disabled."""
    (tmp_path / ".env").write_text("EBAY_ENVIRONMENT=sandbox\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert get_ebay_api_config() is None


def test_get_ebay_api_config_uses_sandbox_base_url(tmp_path: Path, monkeypatch):
    """Sandbox environment should use sandbox eBay hosts."""
    (tmp_path / ".env").write_text(
        "EBAY_CLIENT_ID=abc\nEBAY_CLIENT_SECRET=secret\nEBAY_ENVIRONMENT=sandbox\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = get_ebay_api_config()

    assert config is not None
    assert config.api_base_url == "https://api.sandbox.ebay.com"
    assert config.oauth_url == "https://api.sandbox.ebay.com/identity/v1/oauth2/token"


def test_parse_browse_prices_extracts_price_values():
    """Browse parser should extract active listing prices."""
    data = {
        "itemSummaries": [
            {"price": {"value": "100.50", "currency": "USD"}},
            {"currentBidPrice": {"value": "75.25", "currency": "USD"}},
            {"price": {"value": "not-a-number", "currency": "USD"}},
        ]
    }

    assert parse_browse_prices(data) == [100.5, 75.25]


def test_parse_sold_prices_extracts_last_sold_price_values():
    """Marketplace Insights parser should extract sold prices."""
    data = {
        "itemSales": [
            {"lastSoldPrice": {"value": "850.00", "currency": "USD"}},
            {"lastSoldPrice": {"value": "45.00", "currency": "USD"}},
            {"lastSoldPrice": {"currency": "USD"}},
        ]
    }

    assert parse_sold_prices(data) == [850.0, 45.0]
