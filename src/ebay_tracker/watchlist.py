"""Load and validate the watchlist YAML file."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ebay_tracker.ebay import CONDITION_IDS
from ebay_tracker.models import WatchItem


class WatchlistError(Exception):
    """The watchlist file is missing or invalid."""


@dataclass(frozen=True)
class Watchlist:
    items: list[WatchItem]
    # Deprecated: prefer the DISCORD_WEBHOOK_URL environment variable.
    webhook_url: str | None = None


def _number(value: Any, where: str, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise WatchlistError(f"{where}: {field_name} must be a number")
    try:
        number = float(value)
    except ValueError:
        raise WatchlistError(f"{where}: {field_name} must be a number") from None
    if number < 0:
        raise WatchlistError(f"{where}: {field_name} must not be negative")
    return number


def _optional_number(raw: dict[str, Any], key: str, where: str) -> float | None:
    return None if raw.get(key) is None else _number(raw[key], where, key)


def _string_list(value: Any, where: str, field_name: str) -> tuple[str, ...]:
    """Accept a single string or a list of strings."""
    if value is None:
        return ()
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not all(
        isinstance(entry, str) and entry.strip() for entry in values
    ):
        raise WatchlistError(f"{where}: {field_name} must be text or a list of text")
    return tuple(entry.strip() for entry in values)


def parse_item(raw: Any, index: int) -> WatchItem:
    where = f"item #{index}"
    if not isinstance(raw, dict):
        raise WatchlistError(f"{where} must be a mapping")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WatchlistError(f"{where} must have a non-empty name")
    where = f"item #{index} ({name.strip()})"

    if "target_price" not in raw:
        raise WatchlistError(f"{where}: target_price is required")

    condition = tuple(
        entry.lower().replace(" ", "_").replace("-", "_")
        for entry in _string_list(raw.get("condition"), where, "condition")
    )
    unknown = [entry for entry in condition if entry not in CONDITION_IDS]
    if unknown:
        raise WatchlistError(
            f"{where}: unknown condition {unknown[0]!r}; "
            f"use one of {', '.join(CONDITION_IDS)}"
        )

    query = raw.get("query")
    if query is not None and (not isinstance(query, str) or not query.strip()):
        raise WatchlistError(f"{where}: query must be non-empty text")

    category_id = raw.get("category_id")
    if category_id is not None and not isinstance(category_id, int | str):
        raise WatchlistError(f"{where}: category_id must be a number")

    min_price = _optional_number(raw, "min_price", where)
    max_price = _optional_number(raw, "max_price", where)
    if min_price is not None and max_price is not None and min_price > max_price:
        raise WatchlistError(f"{where}: min_price is above max_price")

    return WatchItem(
        name=name.strip(),
        target_price=_number(raw["target_price"], where, "target_price"),
        query=query.strip() if query else None,
        condition=condition,
        category_id=str(category_id) if category_id is not None else None,
        min_price=min_price,
        max_price=max_price,
        exclude=_string_list(raw.get("exclude"), where, "exclude"),
    )


def load_watchlist(path: Path | str) -> Watchlist:
    """Read the watchlist, raising WatchlistError with a readable message."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise WatchlistError(f"Watchlist file not found: {path}") from None
    except yaml.YAMLError as error:
        raise WatchlistError(f"Watchlist is not valid YAML: {error}") from None

    if not isinstance(data, dict):
        raise WatchlistError("Watchlist must be a YAML mapping with an 'items' list")
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise WatchlistError("Watchlist must define an 'items' list")

    items = [parse_item(raw, index) for index, raw in enumerate(raw_items, start=1)]
    names = [item.name.casefold() for item in items]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise WatchlistError(f"Duplicate item name: {sorted(duplicates)[0]}")

    webhook_url = data.get("webhook_url")
    if webhook_url is not None and not isinstance(webhook_url, str):
        raise WatchlistError("webhook_url must be text")
    return Watchlist(items=items, webhook_url=webhook_url or None)
