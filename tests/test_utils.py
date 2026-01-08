# Pytests
import pytest

from main import process_item
from utils import (
    get_prices_by_link,
    parse_price,
    remove_outliers,
    save_to_file,
    validate_url,
)


# Price Parsing (parse_price)
def test_parse_price_simple():
    assert parse_price("$100.00") == 100.00


def test_parse_price_with_commas():
    assert parse_price("$1,234.56") == 1234.56


def test_parse_price_invalid():
    assert parse_price("Free shipping") is None


# URL Validation (validate_url)
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.ebay.com/sch/...", True),
        ("http://ebay.com/sch/...", True),
        ("https://evil.com", False),
        ("not-a-url", False),
    ],
)
def test_validate_url(url, expected):
    assert validate_url(url) == expected


# Outlier Removal (remove_outliers)
def test_remove_outliers_filters_extreme_values():
    prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 100]  # 100 is an outlier
    result = remove_outliers(prices)
    assert 100 not in result


# CSV Saving
def test_save_to_file_creates_csv(tmp_path, monkeypatch):
    import numpy as np

    # Change working directory to tmp_path so "prices.csv" is created there
    monkeypatch.chdir(tmp_path)
    save_to_file(np.array([10.0, 20.0]), np.array([15.0, 25.0]), "Test Item")
    assert (tmp_path / "prices.csv").exists()


# Mock Playwright
def test_get_prices_by_link_parses_html(mocker):
    # HTML must match eBay's structure: ul.srp-results > li.s-item > span.s-item__price
    fake_html = """
    <ul class="srp-results">
        <li class="s-item"><span class="s-item__price">$50.00</span></li>
        <li class="s-item"><span class="s-item__price">$75.00</span></li>
    </ul>
    """
    mocker.patch("utils.fetch_page_content", return_value=fake_html)

    prices = get_prices_by_link("https://ebay.com/fake")
    assert 50.0 in prices
    assert 75.0 in prices


# Full flow from URL to processed prices
def test_process_item_full_workflow(mocker):
    mocker.patch("main.get_prices_by_link", return_value=[10.0, 20.0, 30.0])
    mocker.patch("main.save_to_file")

    result, _ = process_item("https://ebay.com/test", "test item")
    assert result is not None
