#!/usr/bin/env python3
import numpy as np
from utils import logging, get_prices_by_link, remove_outliers, get_average, extract_item_name, save_to_file

if __name__ == "__main__":
    link = input("Enter the eBay search link: ")
    print()
    if not link.strip():
        logging.error("No link provided. Please provide a valid eBay search link.")
        exit(1)

    item_name = extract_item_name(link)
    if not item_name:
        item_name = input("Enter the name of the item: ").strip()
        if not item_name:
            logging.error("No item name provided. Exiting.")
            exit(1)

    prices = get_prices_by_link(link)
    prices_without_outliers = remove_outliers(prices)
    average_price = get_average(prices_without_outliers)
    print(f"Average price: ${np.around(average_price, 2)}")
    save_to_file(prices_without_outliers, item_name)
    print()