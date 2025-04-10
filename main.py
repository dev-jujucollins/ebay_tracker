#!/usr/bin/env python3
from bs4 import BeautifulSoup
import requests
import numpy as np
import csv
from datetime import datetime
import logging
from requests.exceptions import RequestException

#* Example link: "https://www.ebay.com/sch/i.html?_from=R40&_trksid=p4432023.m570.l1311&_nkw=nvidia+rtx+5090&_sacat=0pipipi"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='\033[91m%(asctime)s\033[0m - \033[92m%(levelname)s\033[0m - \033[96m%(message)s\033[0m'
)

# function to get prices from ebay search results
def get_prices_by_link(link):
    try:
        r = requests.get(link)
        r.raise_for_status()
    except RequestException as e:
        logging.error(f"Failed to fetch data from eBay: {e}")
        return []
    
    page_parse = BeautifulSoup(r.text, "html.parser")
    search_results = page_parse.find("ul", {"class": "srp-results"})
    if not search_results:
        logging.warning("No search results found on the page.")
        return []

    search_results = search_results.find_all("li", {"class": "s-item"})

    # list to store prices
    item_prices = []

    # loop through search results
    for result in search_results:
        price_tag = result.find("span", {"class": "s-item__price"})
        if not price_tag or not price_tag.text:
            continue
        price_as_text = price_tag.text
        if "to" in price_as_text:
            continue
        try:
            price = float(price_as_text[1:].replace(",", ""))
            item_prices.append(price)
        except ValueError:
            logging.warning(f"Invalid price format: {price_as_text}")
            continue

    if not item_prices:
        logging.warning("No valid prices found.")
    return item_prices

# function to remove outliers from the list of prices
def remove_outliers(prices, m=2):
    """
    Remove outliers from a list of prices.

    Args:
        prices (list): List of prices.
        m (int, optional): The number of standard deviations to use for outlier detection. Defaults to 2.

    Returns:
        numpy.ndarray: Array of prices without outliers.
    """
    data = np.array(prices)
    mask = abs(data - np.mean(data)) < m * np.std(data)
    return data[mask]

# function to get average of list of prices
def get_average(prices):
    return np.mean(prices)

# function to save prices to csv file
def save_to_file(prices):
    if prices.size == 0:  # Check if the array is empty
        logging.warning("No price to save.")
        return

    fields = [datetime.today().strftime("%Y-%m-%d"), np.around(get_average(prices), 2)]
    try:
        with open("prices.csv", "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(fields)
        logging.info("Price saved to prices.csv")
    except IOError as e:
        logging.error(f"Failed to write to file: {e}")

# main
if __name__ == "__main__":
    link = input("Enter the eBay search link: ")
    print()
    if not link.strip():
        logging.error("No link provided. Please provide a valid eBay search link.")
        exit(1)
    prices = get_prices_by_link(link)
    prices_without_outliers = remove_outliers(prices)
    average_price = get_average(prices_without_outliers)
    print(f"Average price: {average_price}")
    save_to_file(prices_without_outliers)
