#!/usr/bin/env python3
import sys
import numpy as np
from typing import Optional, Tuple
from utils import (
    logging,
    get_prices_by_link,
    remove_outliers,
    get_average,
    save_to_file,
    validate_url,
    get_item_name,
    parse_arguments_and_generate_link,
)


def process_item(
    link: str, item_name: Optional[str] = None
) -> Tuple[Optional[Tuple[float, float]], Optional[str]]:
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
    sold_avg = (
        get_average(sold_prices_without_outliers)
        if sold_prices_without_outliers.size > 0
        else None
    )

    return (listed_avg, sold_avg), item_name


def main() -> None:
    """Main function to run the eBay price tracker."""
    link, item_name = parse_arguments_and_generate_link(sys.argv)

    if not link:
        link = input("Enter an eBay search URL: ").strip()
        if not link:
            logging.error("No link provided. Please provide a valid eBay search link.")
            sys.exit(1)

    prices, item_name = process_item(link, item_name)
    if prices is None:
        sys.exit(1)

    listed_avg, sold_avg = prices
    print(f"Average listed price: ${np.around(listed_avg, 2)}")
    if sold_avg is not None:
        print(f"Average sold price: ${np.around(sold_avg, 2)}")
    else:
        print("No valid sold prices found.")

    # Gets prices for saving to file
    listed_prices = np.array(get_prices_by_link(link, sold_only=False))
    sold_prices = np.array(get_prices_by_link(link, sold_only=True))
    save_to_file(listed_prices, sold_prices, item_name)


if __name__ == "__main__":
    main()
