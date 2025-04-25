#!/usr/bin/env python3
import sys
import numpy as np
from utils import logging, get_prices_by_link, remove_outliers, get_average, save_to_file, validate_url, get_item_name, parse_arguments_and_generate_link

if __name__ == "__main__":
    link, item_name = parse_arguments_and_generate_link(sys.argv)
    
    if not link:
        link = input("Enter an eBay search URL: ").strip()
        if not link:
            logging.error("No link provided. Please provide a valid eBay search link.")
            exit(1)

    if not validate_url(link):
        exit(1)

    item_name = get_item_name(link, item_name)
    if not item_name:
        exit(1)

    prices = get_prices_by_link(link)
    prices_without_outliers = remove_outliers(prices)
    average_price = get_average(prices_without_outliers)
    print(f"Average price: ${np.around(average_price, 2)}")
    save_to_file(prices_without_outliers, item_name)
    print()