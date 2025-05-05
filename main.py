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
) -> Tuple[Optional[float], Optional[str]]:
    """
    Process an eBay item to get its average price.

    Args:
        link: eBay search URL
        item_name: Optional pre-provided item name

    Returns:
        Tuple of (average_price, item_name) or (None, None) if processing fails
    """
    if not validate_url(link):
        return None, None

    item_name = get_item_name(link, item_name)
    if not item_name:
        return None, None

    prices = get_prices_by_link(link)
    if not prices:
        logging.error("No prices found for the item.")
        return None, None

    prices_without_outliers = remove_outliers(prices)
    if prices_without_outliers.size == 0:
        logging.error("No valid prices after removing outliers.")
        return None, None

    average_price = get_average(prices_without_outliers)
    return average_price, item_name


def main() -> None:
    """Main function to run the eBay price tracker."""
    link, item_name = parse_arguments_and_generate_link(sys.argv)

    if not link:
        link = input("Enter an eBay search URL: ").strip()
        if not link:
            logging.error("No link provided. Please provide a valid eBay search link.")
            sys.exit(1)

    average_price, item_name = process_item(link, item_name)
    if average_price is None:
        sys.exit(1)

    print(f"Average price: ${np.around(average_price, 2)}")
    save_to_file(np.array(get_prices_by_link(link)), item_name)


if __name__ == "__main__":
    main()
