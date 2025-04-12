from bs4 import BeautifulSoup
import requests
import numpy as np
import csv
from datetime import datetime
import logging
from requests.exceptions import RequestException
from urllib.parse import urlparse, parse_qs

# logging
logging.basicConfig(
    level=logging.INFO,
    format='\033[91m%(asctime)s\033[0m - \033[92m%(levelname)s\033[0m - \033[96m%(message)s\033[0m'
)

# gets prices from eBay search link
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

    # loops through search results
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

# removes outlier prices
def remove_outliers(prices, m=2):
    data = np.array(prices)
    mask = abs(data - np.mean(data)) < m * np.std(data)
    return data[mask]

def get_average(prices):
    return np.mean(prices)

# extracts item name
def extract_item_name(link):
    try:
        query_params = parse_qs(urlparse(link).query)
        item_name = query_params.get('_nkw', [None])[0]
        if item_name:
            return item_name.replace('+', ' ')
    except Exception as e:
        logging.warning(f"Failed to extract item name: {e}")
    return None

# saves prices to .csv
def save_to_file(prices, item_name):
    if prices.size == 0:
        logging.warning("No price to save.")
        return

    fields = [datetime.today().strftime("%Y-%m-%d"), item_name, f"${np.around(get_average(prices), 2)}"]
    try:
        with open("prices.csv", "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(fields)
        logging.info("Price saved to prices.csv")
    except IOError as e:
        logging.error(f"Failed to write to file: {e}")