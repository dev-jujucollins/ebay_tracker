# Pytests
import numpy as np
import pytest

from main import process_item
from utils import (
    get_prices_by_link,
    parse_price,
    parse_prices_from_html,
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
    prices = [
        10.0,
        11.0,
        12.0,
        13.0,
        14.0,
        15.0,
        16.0,
        17.0,
        18.0,
        19.0,
        100.0,
    ]  # 100 is an outlier
    result = remove_outliers(prices)
    assert 100 not in result


# CSV Saving
def test_save_to_file_creates_csv(tmp_path, monkeypatch):
    # Change working directory to tmp_path so "prices.csv" is created there
    monkeypatch.chdir(tmp_path)
    output_path = tmp_path / "prices.csv"
    save_to_file(
        np.array([10.0, 20.0]), np.array([15.0, 25.0]), "Test Item", str(output_path)
    )
    assert output_path.exists()


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


def test_parse_prices_from_html_sold_only():
    fake_html = """
    <ul class="srp-results">
        <li class="s-item">
            <span class="s-item__price">$50.00</span>
            <span class="POSITIVE">Sold</span>
        </li>
        <li class="s-item">
            <span class="s-item__price">$75.00</span>
        </li>
    </ul>
    """

    prices = parse_prices_from_html(fake_html, sold_only=True)
    assert prices == [50.0]


# Full flow from URL to processed prices
def test_process_item_full_workflow(mocker):
    mocker.patch(
        "main.get_prices_by_link",
        side_effect=[[10.0, 20.0, 30.0], []],
    )
    mocker.patch("main.save_to_file")

    result, _ = process_item("https://ebay.com/test", "test item")
    assert result is not None
    listed_avg, sold_avg, listed_prices, sold_prices = result
    assert listed_avg is not None
    assert sold_avg is None
    assert listed_prices.size > 0
    assert sold_prices.size == 0
