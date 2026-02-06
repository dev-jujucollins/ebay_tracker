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
        with open(path) as f:
            data = yaml.safe_load(f)

        items = [
            WatchlistItem(
                name=item["name"],
                target_price=float(item["target_price"]),
                check_sold=item.get("check_sold", False),
            )
            for item in data.get("items", [])
        ]

        return WatchlistConfig(
            webhook_url=data.get("webhook_url"),
            items=items,
        )
    except FileNotFoundError:
        logger.error(f"Watchlist file not found: {path}")
        return None
    except (yaml.YAMLError, KeyError, TypeError) as e:
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
    link = generate_ebay_search_link(result.item.name, sold_only=result.item.check_sold)
    message = (
        f"[{timestamp}] PRICE ALERT: {result.item.name} "
        f"average price is ${result.current_price:.2f} "
        f"(${abs(result.price_difference):.2f} below target of ${result.item.target_price:.2f})\n"
        f"    Link: {link}"
    )

    # Log to console
    logger.info(f"🔔 {message}")

    # Append to log file
    try:
        with open(ALERTS_LOG_PATH, "a") as f:
            f.write(message + "\n")
    except IOError as e:
        logger.error(f"Failed to write to alerts log: {e}")


async def send_webhook_alert(result: PriceResult, webhook_url: str) -> bool:
    """
    Sends an alert to a webhook URL (Discord, Slack, etc.).

    Args:
        result: PriceResult that triggered the alert
        webhook_url: URL to POST the alert to

    Returns:
        True if webhook was sent successfully
    """
    link = generate_ebay_search_link(result.item.name, sold_only=result.item.check_sold)
    payload = {
        "content": (
            f"🔔 **Price Alert!**\n"
            f"**{result.item.name}** average price is now **${result.current_price:.2f}**\n"
            f"That's ${abs(result.price_difference):.2f} below your target of ${result.item.target_price:.2f}!\n"
            f"[View on eBay]({link})"
        )
    }

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
        current_price = await fetch_item_price(item)
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
    results = await asyncio.gather(*tasks)

    # Send notifications for items below target
    for result in results:
        if result.is_below_target:
            log_alert_to_file(result)
            if config.webhook_url:
                await send_webhook_alert(result, config.webhook_url)

    return results


async def run_watch_mode(watchlist_path: str = "watchlist.yaml") -> None:
    """
    Main entry point for watch mode.

    Loads watchlist, checks all items, and sends alerts.

    Args:
        watchlist_path: Path to watchlist YAML file
    """
    config = load_watchlist(watchlist_path)
    if not config:
        return

    if not config.items:
        logger.warning("No items in watchlist")
        return

    logger.info(f"Checking {len(config.items)} items...")
    results = await process_watchlist(config)

    # Summary
    alerts_triggered = sum(1 for r in results if r.is_below_target)
    failed_checks = sum(1 for r in results if r.current_price is None)

    logger.info(
        f"Done! {alerts_triggered} alerts triggered, {failed_checks} checks failed"
    )
