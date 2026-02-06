#!/usr/bin/env python3
import argparse
import asyncio
import sys

import numpy as np

import logging
from typing import Optional, Tuple

from utils import (
    get_prices_by_link,
    remove_outliers,
    get_average,
    save_to_file,
    validate_url,
    get_item_name,
    generate_ebay_search_link,
)


def process_item(
    link: str, item_name: Optional[str] = None
) -> Tuple[
    Optional[Tuple[float, Optional[float], np.ndarray, np.ndarray]], Optional[str]
]:
    """
    Processes an eBay item to get its average listed and sold prices.

    Args:
        link: eBay search URL
        item_name: Optional pre-provided item name

    Returns:
        Tuple of ((listed_price, sold_price), item_name) or (None, None) if processing fails
    """
    if not validate_url(link):
        return None, None

    item_name = get_item_name(link, item_name)
    if not item_name:
        return None, None

    # Gets listed prices
    listed_prices = get_prices_by_link(link, sold_only=False)
    if not listed_prices:
        logging.error("No listed prices found for the item.")
        return None, None

    listed_prices_without_outliers = remove_outliers(listed_prices)
    if listed_prices_without_outliers.size == 0:
        logging.error("No valid listed prices after removing outliers.")
        return None, None

    # Gets sold prices
    sold_prices = get_prices_by_link(link, sold_only=True)
    if not sold_prices:
        logging.warning("No sold prices found for the item.")
        sold_prices_without_outliers = np.array([])
    else:
        sold_prices_without_outliers = remove_outliers(sold_prices)
        if sold_prices_without_outliers.size == 0:
            logging.warning("No valid sold prices after removing outliers.")
            sold_prices_without_outliers = np.array([])

    listed_avg = get_average(listed_prices_without_outliers)
    if listed_avg is None:
        logging.error("No valid listed prices after removing outliers.")
        return None, None

    sold_avg = (
        get_average(sold_prices_without_outliers)
        if sold_prices_without_outliers.size > 0
        else None
    )

    return (
        listed_avg,
        sold_avg,
        listed_prices_without_outliers,
        sold_prices_without_outliers,
    ), item_name


def run_single_item(item_name: Optional[str] = None) -> None:
    """Run price check for a single item (original behavior)."""
    if item_name:
        link = generate_ebay_search_link(item_name)
        logging.info(f"Generated eBay search link: {link}")
    else:
        link = input("Enter an eBay search URL: ").strip()
        if not link:
            logging.error("No link provided. Please provide a valid eBay search link.")
            sys.exit(1)

    result, item_name = process_item(link, item_name)
    if result is None or item_name is None:
        sys.exit(1)

    listed_avg, sold_avg, listed_prices, sold_prices = result
    print(f"Average listed price: ${np.around(listed_avg, 2)}")
    if sold_avg is not None:
        print(f"Average sold price: ${np.around(sold_avg, 2)}")
    else:
        print("No valid sold prices found.")

    save_to_file(listed_prices, sold_prices, item_name)


def run_watch_mode(watchlist_path: str) -> None:
    """Run watch mode to check all items in watchlist for price alerts."""
    from alerts import run_watch_mode as async_watch

    asyncio.run(async_watch(watchlist_path))


def main() -> None:
    """Main function to run the eBay price tracker."""
    logging.basicConfig(
        level=logging.INFO,
        format="\033[91m%(asctime)s\033[0m - \033[92m%(levelname)s\033[0m - \033[96m%(message)s\033[0m",
        datefmt="%H:%M:%S",
    )

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
        help="Run in watch mode: check watchlist.yaml for price alerts",
    )
    parser.add_argument(
        "--watchlist",
        default="watchlist.yaml",
        help="Path to watchlist YAML file (default: watchlist.yaml)",
    )

    args = parser.parse_args()

    if args.watch:
        run_watch_mode(args.watchlist)
    else:
        item_name = " ".join(args.item) if args.item else None
        run_single_item(item_name)


if __name__ == "__main__":
    main()
