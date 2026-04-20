"""
Alert system for eBay price tracking.

Monitors items in a watchlist and sends notifications when prices drop below targets.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import yaml

from utils import (
    generate_ebay_search_link,
    get_prices_by_link_async,
    remove_outliers,
    get_average,
)

logger = logging.getLogger(__name__)

# Alerts log file
ALERTS_LOG_PATH = Path("alerts.log")
AlertKey = tuple[str, bool, float]


@dataclass
class WatchlistItem:
    """Represents an item being watched for price alerts."""

    name: str
    target_price: float
    check_sold: bool = False


@dataclass
class PriceResult:
    """Result of a price check for an item."""

    item: WatchlistItem
    current_price: Optional[float]
    is_below_target: bool
    price_difference: float  # Negative means below target


@dataclass
class WatchlistConfig:
    """Configuration loaded from watchlist.yaml."""

    webhook_url: Optional[str]
    items: list[WatchlistItem]


def load_watchlist(path: str = "watchlist.yaml") -> Optional[WatchlistConfig]:
    """
    Loads watchlist configuration from YAML file.

    Args:
        path: Path to watchlist YAML file

    Returns:
        WatchlistConfig if successful, None otherwise
    """
    try:
        with Path(path).open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            logger.error("Watchlist file is empty")
            return None
        if not isinstance(data, dict):
            logger.error("Watchlist must contain a YAML mapping at top level")
            return None
        if "items" not in data:
            logger.error("Watchlist must define an items list")
            return None
        if not isinstance(data["items"], list):
            logger.error("Watchlist items must be a list")
            return None

        items: list[WatchlistItem] = []
        for index, item in enumerate(data["items"], start=1):
            if not isinstance(item, dict):
                logger.error(f"Watchlist item #{index} must be a mapping")
                return None

            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                logger.error(f"Watchlist item #{index} must have non-empty name")
                return None

            try:
                target_price = float(item["target_price"])
            except KeyError:
                logger.error(f"Watchlist item #{index} is missing target_price")
                return None
            except (TypeError, ValueError):
                logger.error(f"Watchlist item #{index} has invalid target_price")
                return None

            check_sold = item.get("check_sold", False)
            if not isinstance(check_sold, bool):
                logger.error(f"Watchlist item #{index} has invalid check_sold value")
                return None

            items.append(
                WatchlistItem(
                    name=name.strip(),
                    target_price=target_price,
                    check_sold=check_sold,
                )
            )

        webhook_url = data.get("webhook_url")
        if webhook_url is not None and not isinstance(webhook_url, str):
            logger.error("webhook_url must be a string")
            return None

        return WatchlistConfig(
            webhook_url=webhook_url,
            items=items,
        )
    except FileNotFoundError:
        logger.error(f"Watchlist file not found: {path}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse watchlist: {e}")
        return None


async def fetch_item_price(item: WatchlistItem) -> Optional[float]:
    """
    Fetches the current average price for an item.

    Args:
        item: WatchlistItem to fetch price for

    Returns:
        Average price after outlier removal, or None if unavailable
    """
    link = generate_ebay_search_link(item.name, sold_only=item.check_sold)
    prices = await get_prices_by_link_async(link, sold_only=item.check_sold)

    if not prices:
        return None

    filtered_prices = remove_outliers(prices)
    return get_average(filtered_prices)


def check_price_alert(
    item: WatchlistItem, current_price: Optional[float]
) -> PriceResult:
    """
    Determines if an alert should be triggered for this item.

    Args:
        item: The watchlist item with target price
        current_price: The fetched current average price (may be None)

    Returns:
        PriceResult with is_below_target=True if alert should fire
    """
    # Handle failed fetch - no alert, but track it
    if current_price is None:
        return PriceResult(
            item=item,
            current_price=None,
            is_below_target=False,
            price_difference=0.0,
        )

    # Calculate difference: negative means below target
    price_difference = current_price - item.target_price

    # Alert if price is at or below target
    is_below_target = current_price <= item.target_price

    return PriceResult(
        item=item,
        current_price=current_price,
        is_below_target=is_below_target,
        price_difference=price_difference,
    )


def log_alert_to_file(result: PriceResult) -> None:
    """
    Logs an alert to the alerts.log file.

    Args:
        result: PriceResult that triggered the alert
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"[{timestamp}] {build_plain_alert_message(result)}"

    # Log to console
    logger.info(f"🔔 {message}")

    # Append to log file
    try:
        with ALERTS_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(message + "\n")
    except IOError as e:
        logger.error(f"Failed to write to alerts log: {e}")


def get_alert_key(item: WatchlistItem) -> AlertKey:
    """Builds stable key for duplicate alert suppression."""
    return (item.name.casefold(), item.check_sold, item.target_price)


def build_plain_alert_message(result: PriceResult) -> str:
    """Builds plain-text alert body."""
    link = generate_ebay_search_link(result.item.name, sold_only=result.item.check_sold)
    return (
        f"PRICE ALERT: {result.item.name} average price is "
        f"${result.current_price:.2f} "
        f"(${abs(result.price_difference):.2f} below target of "
        f"${result.item.target_price:.2f})\n"
        f"    Link: {link}"
    )


def build_webhook_payload(result: PriceResult) -> dict[str, str]:
    """Builds Discord webhook payload."""
    link = generate_ebay_search_link(result.item.name, sold_only=result.item.check_sold)
    return {
        "content": (
            f"🔔 **Price Alert!**\n"
            f"**{result.item.name}** average price is now "
            f"**${result.current_price:.2f}**\n"
            f"That's ${abs(result.price_difference):.2f} below your target of "
            f"${result.item.target_price:.2f}!\n"
            f"[View on eBay]({link})"
        )
    }


async def send_webhook_alert(result: PriceResult, webhook_url: str) -> bool:
    """
    Sends an alert to Discord webhook URL.

    Args:
        result: PriceResult that triggered the alert
        webhook_url: URL to POST the alert to

    Returns:
        True if webhook was sent successfully
    """
    payload = build_webhook_payload(result)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10.0)
            response.raise_for_status()
            logger.info(f"Webhook sent successfully for {result.item.name}")
            return True
    except httpx.HTTPError as e:
        logger.error(f"Failed to send webhook: {e}")
        return False


async def check_item_with_semaphore(
    item: WatchlistItem, semaphore: asyncio.Semaphore
) -> PriceResult:
    """
    Checks a single item's price with concurrency limiting.

    Args:
        item: WatchlistItem to check
        semaphore: Semaphore for limiting concurrent requests

    Returns:
        PriceResult for this item
    """
    async with semaphore:
        logger.info(f"Checking price for: {item.name}")
        try:
            current_price = await fetch_item_price(item)
        except Exception as e:
            logger.exception(f"Price check failed for {item.name}: {e}")
            current_price = None
        return check_price_alert(item, current_price)


async def process_watchlist(
    config: WatchlistConfig, max_concurrent: int = 3
) -> list[PriceResult]:
    """
    Processes all items in the watchlist concurrently.

    Args:
        config: Watchlist configuration
        max_concurrent: Maximum concurrent price checks

    Returns:
        List of PriceResults for all items
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = [check_item_with_semaphore(item, semaphore) for item in config.items]
    return await asyncio.gather(*tasks)


async def dispatch_alerts(
    results: list[PriceResult],
    webhook_url: Optional[str],
    active_alerts: Optional[set[AlertKey]] = None,
) -> set[AlertKey]:
    """Sends alerts once per active below-target item until it recovers."""
    if active_alerts is None:
        active_alerts = set()

    current_keys = {get_alert_key(result.item) for result in results}
    active_alerts.intersection_update(current_keys)

    for result in results:
        key = get_alert_key(result.item)

        if not result.is_below_target or result.current_price is None:
            active_alerts.discard(key)
            continue

        if key in active_alerts:
            logger.info(f"Skipping duplicate active alert for {result.item.name}")
            continue

        log_alert_to_file(result)
        if webhook_url:
            await send_webhook_alert(result, webhook_url)
        active_alerts.add(key)

    return active_alerts


async def run_watch_cycle(
    watchlist_path: str = "watchlist.yaml",
    active_alerts: Optional[set[AlertKey]] = None,
    max_concurrent: int = 3,
) -> tuple[Optional[WatchlistConfig], list[PriceResult], set[AlertKey]]:
    """Runs one watchlist check and dispatches any fresh alerts."""
    config = load_watchlist(watchlist_path)
    if not config:
        return None, [], active_alerts or set()

    if not config.items:
        logger.warning("No items in watchlist")
        return config, [], active_alerts or set()

    logger.info(f"Checking {len(config.items)} items...")
    results = await process_watchlist(config, max_concurrent=max_concurrent)
    updated_alerts = await dispatch_alerts(
        results,
        config.webhook_url,
        active_alerts=active_alerts,
    )

    alerts_triggered = sum(1 for r in results if r.is_below_target)
    failed_checks = sum(1 for r in results if r.current_price is None)
    logger.info(
        f"Done! {alerts_triggered} items below target, {failed_checks} checks failed"
    )
    return config, results, updated_alerts


async def run_watch_mode(
    watchlist_path: str = "watchlist.yaml",
    interval_seconds: float = 300.0,
    run_once: bool = False,
) -> None:
    """
    Main entry point for watch mode.

    Loads watchlist, checks all items, and sends alerts.

    Args:
        watchlist_path: Path to watchlist YAML file
        interval_seconds: Seconds between checks
        run_once: Exit after one pass instead of watching continuously
    """
    active_alerts: set[AlertKey] = set()

    while True:
        _, _, active_alerts = await run_watch_cycle(
            watchlist_path,
            active_alerts=active_alerts,
        )
        if run_once:
            return

        logger.info(f"Sleeping for {interval_seconds:.0f}s before next check")
        await asyncio.sleep(interval_seconds)
