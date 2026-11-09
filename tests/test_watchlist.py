from pathlib import Path

import pytest

from ebay_tracker.watchlist import WatchlistError, load_watchlist

ITEM_A = "items:\n  - name: A\n    target_price: 5\n"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "watchlist.yaml"
    path.write_text(text)
    return path


def test_loads_items_with_filters(tmp_path: Path):
    path = write(
        tmp_path,
        """
items:
  - name: " Steam Deck OLED 1TB "
    target_price: 450
    condition: [Used, "open box"]
    min_price: 250
    exclude: ["for parts", "case"]
    category_id: 139971
  - name: "RTX 5090"
    query: "RTX 5090 32GB"
    target_price: "1800.50"
    condition: new
    check_sold: true  # legacy key, ignored
""",
    )

    watchlist = load_watchlist(path)
    deck, gpu = watchlist.items

    assert deck.name == "Steam Deck OLED 1TB"
    assert deck.target_price == 450.0
    assert deck.condition == ("used", "open_box")
    assert deck.min_price == 250.0
    assert deck.exclude == ("for parts", "case")
    assert deck.category_id == "139971"
    assert deck.search_query == "Steam Deck OLED 1TB"
    assert gpu.search_query == "RTX 5090 32GB"
    assert gpu.target_price == 1800.5
    assert gpu.condition == ("new",)
    assert watchlist.webhook_url is None


def test_legacy_webhook_url_is_still_read(tmp_path: Path):
    path = write(tmp_path, "webhook_url: https://example.test/hook\nitems: []\n")

    assert load_watchlist(path).webhook_url == "https://example.test/hook"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "mapping"),
        ("- just\n- a list\n", "mapping"),
        ("items: nope\n", "'items' list"),
        ("items:\n  - target_price: 5\n", "non-empty name"),
        ("items:\n  - name: A\n", "target_price is required"),
        ("items:\n  - name: A\n    target_price: cheap\n", "must be a number"),
        ("items:\n  - name: A\n    target_price: true\n", "must be a number"),
        ("items:\n  - name: A\n    target_price: -1\n", "negative"),
        ("items:\n  - name: A\n    target_price: 5\n    condition: mint\n", "unknown"),
        (
            ITEM_A + "    min_price: 9\n    max_price: 3\n",
            "above max_price",
        ),
        (
            ITEM_A + "  - name: a\n    target_price: 6\n",
            "Duplicate",
        ),
        ("items: [unclosed\n", "not valid YAML"),
    ],
)
def test_invalid_watchlists_raise_readable_errors(tmp_path: Path, text, message):
    with pytest.raises(WatchlistError, match=message):
        load_watchlist(write(tmp_path, text))


def test_missing_file(tmp_path: Path):
    with pytest.raises(WatchlistError, match="not found"):
        load_watchlist(tmp_path / "nope.yaml")
