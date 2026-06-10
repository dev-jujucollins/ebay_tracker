#!/usr/bin/env python3
import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

import numpy as np

from utils import (
    get_prices_by_link,
    remove_outliers,
    get_average,
    save_to_file,
    validate_url,
    get_item_name,
    generate_ebay_search_link,
)


@dataclass
class ItemPrices:
    """Average prices and outlier-filtered samples for one eBay item."""

    item_name: str
    listed_avg: float
    sold_avg: float | None
    listed_prices: np.ndarray
    sold_prices: np.ndarray


def process_item(link: str, item_name: str | None = None) -> ItemPrices | None:
    """
    Processes an eBay item to get its average listed and sold prices.

    Args:
        link: eBay search URL
        item_name: Optional pre-provided item name

    Returns:
        ItemPrices with outlier-filtered prices, or None if processing fails
    """
    if not validate_url(link):
        return None

    item_name = get_item_name(link, item_name)
    if not item_name:
        return None

    # Gets listed prices
    listed_prices = get_prices_by_link(link, sold_only=False)
    if not listed_prices:
        logging.error("No listed prices found for the item.")
        return None

    listed_prices_without_outliers = remove_outliers(listed_prices)
    if listed_prices_without_outliers.size == 0:
        logging.error("No valid listed prices after removing outliers.")
        return None

    # Gets sold prices
    sold_link = generate_ebay_search_link(item_name, sold_only=True)
    sold_prices = get_prices_by_link(sold_link, sold_only=True)
    if not sold_prices:
        sold_prices_without_outliers = np.array([])
    else:
        sold_prices_without_outliers = remove_outliers(sold_prices)
        if sold_prices_without_outliers.size == 0:
            logging.warning("No valid sold prices after removing outliers.")
            sold_prices_without_outliers = np.array([])

    listed_avg = get_average(listed_prices_without_outliers)
    if listed_avg is None:
        logging.error("No valid listed prices after removing outliers.")
        return None

    sold_avg = (
        get_average(sold_prices_without_outliers)
        if sold_prices_without_outliers.size > 0
        else None
    )

    return ItemPrices(
        item_name=item_name,
        listed_avg=listed_avg,
        sold_avg=sold_avg,
        listed_prices=listed_prices_without_outliers,
        sold_prices=sold_prices_without_outliers,
    )


def run_single_item(item_name: str | None = None) -> None:
    """Run price check for a single item (original behavior)."""
    if item_name:
        link = generate_ebay_search_link(item_name)
        logging.info(f"Generated eBay search link: {link}")
    else:
        link = input("Enter an eBay search URL: ").strip()
        if not link:
            logging.error("No link provided. Please provide a valid eBay search link.")
            sys.exit(1)

    result = process_item(link, item_name)
    if result is None:
        sys.exit(1)

    print(f"Average listed price: ${result.listed_avg:.2f}")
    if result.sold_avg is not None:
        print(f"Average sold price: ${result.sold_avg:.2f}")

    save_to_file(result.listed_prices, result.sold_prices, result.item_name)


def positive_interval(value: str) -> float:
    """Parses watch interval and rejects non-positive values."""
    interval = float(value)
    if interval <= 0:
        raise argparse.ArgumentTypeError("watch interval must be greater than 0")
    return interval


def run_watch_mode(
    watchlist_path: str,
    interval_seconds: float,
    run_once: bool,
) -> None:
    """Run watch mode to monitor watchlist for price alerts."""
    from alerts import run_watch_mode as async_watch

    try:
        asyncio.run(
            async_watch(
                watchlist_path,
                interval_seconds=interval_seconds,
                run_once=run_once,
            )
        )
    except KeyboardInterrupt:
        logging.info("Watch mode stopped")


def main() -> None:
    """Main function to run the eBay price tracker."""
    logging.basicConfig(
        level=logging.INFO,
        format="\033[91m%(asctime)s\033[0m - \033[92m%(levelname)s\033[0m - \033[96m%(message)s\033[0m",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(
        description="eBay Price Tracker - Monitor prices and get alerts"
    )
    parser.add_argument(
        "item",
        nargs="*",
        help="Item name to search for (e.g., 'Nintendo Switch 2')",
    )
    parser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Run continuous watch mode and keep checking watchlist for price alerts",
    )
    parser.add_argument(
        "--watchlist",
        default="watchlist.yaml",
        help="Path to watchlist YAML file (default: watchlist.yaml)",
    )
    parser.add_argument(
        "--watch-interval",
        type=positive_interval,
        default=300.0,
        help="Seconds between watch checks (default: 300)",
    )
    parser.add_argument(
        "--watch-once",
        action="store_true",
        help="Check watchlist once, then exit",
    )

    args = parser.parse_args()

    if args.watch:
        run_watch_mode(args.watchlist, args.watch_interval, args.watch_once)
    else:
        item_name = " ".join(args.item) if args.item else None
        run_single_item(item_name)


if __name__ == "__main__":
    main()
