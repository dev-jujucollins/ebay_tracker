import requests
import numpy as np
import csv
import logging
import re
from bs4 import BeautifulSoup
from datetime import datetime
from requests.exceptions import RequestException
from urllib.parse import urlparse, parse_qs
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Optional, Union

# logging
logging.basicConfig(
    level=logging.INFO,
    format="\033[91m%(asctime)s\033[0m - \033[92m%(levelname)s\033[0m - \033[96m%(message)s\033[0m",
    datefmt="%H:%M:%S",
)


def parse_arguments_and_generate_link(
    args: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse command line arguments and generate an eBay search link.

    Args:
        args: List of command line arguments

    Returns:
        Tuple of (link, item_name) or (None, None) if no arguments provided
    """
    if len(args) > 1:
        item_name = " ".join(args[1:])
        link = generate_ebay_search_link(item_name)
        logging.info(f"Generated eBay search link: {link}")
        return link, item_name
    return None, None


def validate_url(link: str) -> bool:
    """
    Validate the given URL for scheme and domain.

    Args:
        link: URL to validate

    Returns:
        bool: True if URL is valid, False otherwise
    """
    parsed_url = urlparse(link)
    if not parsed_url.scheme:
        logging.error(
            "The URL is missing a scheme (e.g., https://). Please provide a valid URL."
        )
        return False
    if not parsed_url.netloc:
        logging.error(
            "The URL is missing a domain (e.g., www.example.com). Please provide a valid URL."
        )
        return False
    return True


def get_item_name(link: str, item_name: Optional[str] = None) -> Optional[str]:
    """
    Extract the item name from the link or use the provided argument.

    Args:
        link: eBay search URL
        item_name: Optional pre-provided item name

    Returns:
        str: Item name if found, None otherwise
    """
    if item_name:
        return item_name
    item_name = extract_item_name(link)
    if not item_name:
        logging.error(
            "Failed to extract item name from the provided URL. Please provide a valid eBay search link."
        )
        return None
    return item_name


@lru_cache(maxsize=128)
def fetch_page_content(link: str) -> Optional[str]:
    """
    Fetch and cache page content for a given URL.

    Args:
        link: URL to fetch

    Returns:
        str: Page content if successful, None otherwise
    """
    try:
        r = requests.get(link, timeout=10)
        r.raise_for_status()
        return r.text
    except RequestException as e:
        logging.error(f"Failed to fetch data from eBay: {e}")
        return None


def parse_price(price_text: str) -> Optional[float]:
    """
    Parse price text into a float value.

    Args:
        price_text: Price text to parse

    Returns:
        float: Parsed price if valid, None otherwise
    """
    try:
        # Remove currency symbol and commas, then convert to float
        price_text = re.sub(r"[^\d.]", "", price_text)
        return float(price_text)
    except ValueError:
        return None


def get_prices_by_link(link: str) -> List[float]:
    """
    Get prices from eBay search link using parallel processing.

    Args:
        link: eBay search URL

    Returns:
        List[float]: List of valid prices found
    """
    content = fetch_page_content(link)
    if not content:
        return []

    page_parse = BeautifulSoup(content, "html.parser")
    search_results = page_parse.find("ul", {"class": "srp-results"})
    if not search_results:
        logging.warning("No search results found on the page.")
        return []

    search_results = search_results.find_all("li", {"class": "s-item"})

    def process_result(result) -> Optional[float]:
        price_tag = result.find("span", {"class": "s-item__price"})
        if not price_tag or not price_tag.text or "to" in price_tag.text:
            return None
        return parse_price(price_tag.text)

    with ThreadPoolExecutor(max_workers=4) as executor:
        prices = list(filter(None, executor.map(process_result, search_results)))

    if not prices:
        logging.warning("No valid prices found.")
    return prices


def remove_outliers(prices: List[float], m: float = 2.0) -> np.ndarray:
    """
    Remove outlier prices using the Z-score method.

    Args:
        prices: List of prices
        m: Number of standard deviations to use as threshold

    Returns:
        np.ndarray: Array of prices with outliers removed
    """
    if not prices:
        return np.array([])

    data = np.array(prices)
    if len(data) < 4:  # Need at least 4 points for meaningful statistics
        return data

    z_scores = np.abs((data - np.mean(data)) / np.std(data))
    return data[z_scores < m]


def get_average(prices: Union[List[float], np.ndarray]) -> float:
    """
    Calculate the average price.

    Args:
        prices: List/array of prices

    Returns:
        float: Average price
    """
    return float(np.mean(prices))


def save_to_file(prices: np.ndarray, item_name: str) -> None:
    """
    Save prices to CSV file.

    Args:
        prices: Array of prices
        item_name: Name of the item
    """
    if prices.size == 0:
        logging.warning("No prices to save.")
        return

    fields = [
        datetime.today().strftime("%Y-%m-%d"),
        item_name,
        f"${np.around(get_average(prices), 2)}",
    ]
    try:
        with open("prices.csv", "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(fields)
        logging.info("Price saved to prices.csv")
    except IOError as e:
        logging.error(f"Failed to write to file: {e}")


def generate_ebay_search_link(item_name: str) -> str:
    """
    Generate eBay search link based on item name.

    Args:
        item_name: Name of the item to search for

    Returns:
        str: Generated eBay search URL
    """
    base_url = "https://www.ebay.com/sch/i.html"
    query = f"?_nkw={item_name.replace(' ', '+')}"
    return base_url + query


def extract_item_name(link: str) -> Optional[str]:
    """
    Extract item name from eBay search URL.

    Args:
        link: eBay search URL

    Returns:
        str: Extracted item name if found, None otherwise
    """
    try:
        query_params = parse_qs(urlparse(link).query)
        item_name = query_params.get("_nkw", [None])[0]
        if item_name:
            return item_name.replace("+", " ")
    except Exception as e:
        logging.warning(f"Failed to extract item name: {e}")
    return None
