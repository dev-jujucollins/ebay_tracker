import asyncio
import csv
import logging
from pathlib import Path
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlparse

import numpy as np
from bs4 import BeautifulSoup
import httpx
from playwright.async_api import (
    async_playwright,
    TimeoutError as AsyncPlaywrightTimeoutError,
)
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ebay_api import get_prices_from_ebay_api, get_prices_from_ebay_api_async

logger = logging.getLogger(__name__)
ACCESS_DENIED_STATUSES = {403, 429}
ALLOWED_EBAY_DOMAINS = {
    "ebay.com",
    "ebay.ca",
    "ebay.com.au",
    "ebay.co.uk",
    "ebay.de",
    "ebay.fr",
    "ebay.it",
    "ebay.es",
    "ebay.nl",
    "ebay.be",
    "ebay.ie",
    "ebay.ch",
    "ebay.at",
    "ebay.pl",
    "ebay.com.hk",
    "ebay.com.sg",
    "ebay.com.my",
    "ebay.ph",
    "ebay.co.jp",
}


class EbayAccessDeniedError(RuntimeError):
    """Raised when eBay blocks the request before returning search results."""


def is_ebay_access_denied(content: str, status_code: Optional[int] = None) -> bool:
    """Return whether eBay returned an access-denied page."""
    if status_code in ACCESS_DENIED_STATUSES:
        return True

    normalized_content = content.casefold()
    return (
        "access denied" in normalized_content
        and "permission to access" in normalized_content
        and "ebay" in normalized_content
    )


def parse_arguments_and_generate_link(
    args: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Parses command line arguments and generate an eBay search link.

    Args:
        args: List of command line arguments

    Returns:
        Tuple of (link, item_name) or (None, None) if no arguments provided
    """
    if len(args) > 1:
        item_name = " ".join(args[1:])
        link = generate_ebay_search_link(item_name)
        logger.info(f"Generated eBay search link: {link}")
        return link, item_name
    return None, None


def validate_url(link: str) -> bool:
    """
    Validates the given URL for scheme and domain.

    Args:
        link: URL to validate

    Returns:
        bool: True if URL is valid, False otherwise
    """
    parsed_url = urlparse(link)
    if not parsed_url.scheme:
        logger.error(
            "The URL is missing a scheme (e.g., https://). Please provide a valid URL."
        )
        return False
    if not parsed_url.netloc:
        logger.error(
            "The URL is missing a domain (e.g., www.example.com). Please provide a valid URL."
        )
        return False
    hostname = (parsed_url.hostname or "").casefold()
    if not any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ALLOWED_EBAY_DOMAINS
    ):
        logger.error(
            "The URL must be an eBay domain (e.g., ebay.com, ebay.co.uk). Please provide a valid eBay URL."
        )
        return False
    return True


def get_item_name(link: str, item_name: Optional[str] = None) -> Optional[str]:
    """
    Extracts the item name from the link or use the provided argument.

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
        logger.error(
            "Failed to extract item name from the provided URL. Please provide a valid eBay search link."
        )
        return None
    return item_name


# Cached pages expire so long-lived watch mode sees fresh prices each cycle.
_PAGE_CACHE_TTL_SECONDS = 300.0
_PageCache = dict[str, tuple[float, str]]
_page_cache: _PageCache = {}


def _cache_get(cache: _PageCache, link: str) -> Optional[str]:
    """Return cached page content for the link, or None if missing/expired."""
    entry = cache.get(link)
    if entry is None:
        return None
    fetched_at, content = entry
    if time.monotonic() - fetched_at > _PAGE_CACHE_TTL_SECONDS:
        del cache[link]
        return None
    return content


def _cache_set(cache: _PageCache, link: str, content: str) -> None:
    """Store page content for the link with the current timestamp."""
    cache[link] = (time.monotonic(), content)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(
        (PlaywrightTimeoutError, TimeoutError, ConnectionError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _fetch_page_content_with_retry(link: str) -> str:
    """
    Internal function that fetches page content with retry logic.

    Args:
        link: URL to fetch

    Returns:
        str: Page content

    Raises:
        PlaywrightTimeoutError: If page fails to load after retries
        Exception: For other failures after retries
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            response = page.goto(link, timeout=30000)
            status_code = response.status if response else None

            if status_code in ACCESS_DENIED_STATUSES:
                content = page.content()
                if is_ebay_access_denied(content, status_code):
                    raise EbayAccessDeniedError(
                        f"eBay returned HTTP {status_code} Access Denied"
                    )

            # Wait for search results to load
            page.wait_for_selector("ul.srp-results", timeout=15000)

            content = page.content()
            if is_ebay_access_denied(content, status_code):
                raise EbayAccessDeniedError("eBay returned an Access Denied page")

            return content
        finally:
            browser.close()


def fetch_page_content(link: str) -> Optional[str]:
    """
    Fetches page content using Playwright to bypass bot protection.

    Uses exponential backoff retry (3 attempts) for transient failures.

    Args:
        link: URL to fetch

    Returns:
        str: Page content if successful, None otherwise
    """
    cached = _cache_get(_page_cache, link)
    if cached is not None:
        return cached

    try:
        content = _fetch_page_content_with_retry(link)
        _cache_set(_page_cache, link, content)
        return content
    except EbayAccessDeniedError as e:
        logger.error(
            "%s. eBay is blocking this automated Playwright request; use the official eBay API, a permitted proxy, or a real browser session.",
            e,
        )
        return None
    except PlaywrightTimeoutError:
        logger.error("Timeout waiting for eBay page to load after 3 attempts")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch data from eBay after 3 attempts: {e}")
        return None


def parse_price(price_text: str) -> Optional[float]:
    """
    Parses price text into a float value.

    Args:
        price_text: Price text to parse

    Returns:
        float: Parsed price if valid, None otherwise
    """
    cleaned = re.sub(r"[^\d.,]", "", price_text)
    if not any(c.isdigit() for c in cleaned):
        return None

    last_dot = cleaned.rfind(".")
    last_comma = cleaned.rfind(",")

    if last_dot != -1 and last_comma != -1:
        # Both separators present: the one appearing last is the decimal point
        if last_dot > last_comma:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(".", "").replace(",", ".")
    elif last_dot != -1 or last_comma != -1:
        # One separator type: repeated occurrences or exactly 3 trailing
        # digits ("1,500", "1.500") mean grouping, otherwise decimal
        sep = "." if last_dot != -1 else ","
        digits_after = len(cleaned) - max(last_dot, last_comma) - 1
        if cleaned.count(sep) > 1 or digits_after == 3:
            cleaned = cleaned.replace(sep, "")
        else:
            cleaned = cleaned.replace(sep, ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_prices_from_html(content: str, sold_only: bool = False) -> List[float]:
    """
    Parses prices from eBay search HTML content.

    Args:
        content: Raw HTML content
        sold_only: Checks whether to get sold prices only or not

    Returns:
        List[float]: List of valid prices found
    """
    page_parse = BeautifulSoup(content, "html.parser")
    search_results = page_parse.find("ul", {"class": "srp-results"})
    if not search_results:
        logger.warning("No search results found on the page.")
        return []

    # Try new eBay structure (s-card) first, fall back to old (s-item)
    items = search_results.find_all("li", {"class": "s-card"})
    if not items:
        items = search_results.find_all("li", {"class": "s-item"})

    def process_result(result) -> Optional[float]:
        # Try new price class first, then fall back to old
        price_tag = result.find("span", {"class": "s-card__price"})
        if not price_tag:
            price_tag = result.find("span", {"class": "s-item__price"})
        if not price_tag:
            price_tag = result.select_one("span[class*='price']")

        if not price_tag or not price_tag.text or "to" in price_tag.text.lower():
            return None

        if sold_only:
            # For sold items, check for sold indicator
            sold_tag = result.find("span", {"class": "POSITIVE"})
            if not sold_tag:
                sold_tag = result.find(string=re.compile(r"sold", re.I))
            if not sold_tag:
                return None

        return parse_price(price_tag.text)

    with ThreadPoolExecutor(max_workers=4) as executor:
        prices = list(filter(None, executor.map(process_result, items)))

    if not prices:
        logger.warning("No valid prices found.")
    return prices


def get_prices_by_link(link: str, sold_only: bool = False) -> List[float]:
    """
    Gets prices from eBay search link using parallel processing.

    Args:
        link: eBay search URL
        sold_only: Checks whether to get sold prices only or not

    Returns:
        List[float]: List of valid prices found
    """
    item_name = extract_item_name(link)
    if item_name:
        try:
            api_prices = get_prices_from_ebay_api(item_name, sold_only=sold_only)
            if api_prices is not None:
                return api_prices
        except httpx.HTTPStatusError as e:
            if sold_only and e.response.status_code == 403:
                logger.warning(
                    "Sold/completed prices are unavailable because Marketplace Insights access is not enabled."
                )
                return []

            logger.error(
                "eBay API request failed with HTTP %s: %s",
                e.response.status_code,
                e.response.text,
            )
            return []
        except httpx.HTTPError as e:
            logger.error(f"eBay API request failed: {e}")
            return []

    content = fetch_page_content(link)
    if not content:
        return []

    return parse_prices_from_html(content, sold_only=sold_only)


def remove_outliers(
    prices: Union[List[float], np.ndarray], m: float = 2.0
) -> np.ndarray:
    """
    Removes outlier prices using the Z-score method.

    Args:
        prices: List or array of prices
        m: Number of standard deviations to use as threshold

    Returns:
        np.ndarray: Array of prices with outliers removed
    """
    if isinstance(prices, list):
        if not prices:
            return np.array([])
        data = np.array(prices)
    else:  # numpy array
        if prices.size == 0:
            return np.array([])
        data = prices

    if len(data) < 4:  # Need at least 4 points for meaningful statistics
        return data

    std_dev = np.std(data)
    if std_dev == 0:
        return data

    z_scores = np.abs((data - np.mean(data)) / std_dev)
    return data[z_scores < m]


def get_average(prices: Union[List[float], np.ndarray]) -> Optional[float]:
    """
    Calculates the average price.

    Args:
        prices: List/array of prices

    Returns:
        float: Average price, or None when no prices exist
    """
    if isinstance(prices, list):
        if not prices:
            return None
        data = np.array(prices)
    else:
        if prices.size == 0:
            return None
        data = prices

    return float(np.mean(data))


def save_to_file(
    listed_prices: np.ndarray,
    sold_prices: np.ndarray,
    item_name: str,
    output_path: str = "prices.csv",
) -> None:
    """
    Saves prices to CSV file.

    Args:
        listed_prices: Array of listed prices
        sold_prices: Array of sold prices
        item_name: Name of the item
        output_path: Output CSV path
    """
    if listed_prices.size == 0 and sold_prices.size == 0:
        logger.warning("No prices to save.")
        return

    listed_avg = (
        get_average(remove_outliers(listed_prices)) if listed_prices.size > 0 else None
    )
    sold_avg = (
        get_average(remove_outliers(sold_prices)) if sold_prices.size > 0 else None
    )

    fields = [
        datetime.today().strftime("%Y-%m-%d"),
        item_name,
        f"${np.around(listed_avg, 2)}" if listed_avg is not None else "N/A",
        f"${np.around(sold_avg, 2)}" if sold_avg is not None else "N/A",
    ]

    # Checks if file exists to determine if we need to write headers
    output_file = Path(output_path)
    file_exists = output_file.is_file()

    try:
        with output_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(
                    ["Date", "Item", "Average Listed Price", "Average Sold Price"]
                )
            writer.writerow(fields)
        logger.info(f"Prices saved to {output_path}")
    except IOError as e:
        logger.error(f"Failed to write to file: {e}")


def generate_ebay_search_link(item_name: str, sold_only: bool = False) -> str:
    """
    Generates eBay search link based on item name.

    Args:
        item_name: Name of the item to search for
        sold_only: Whether to search for sold items only

    Returns:
        str: Generated eBay search URL
    """
    base_url = "https://www.ebay.com/sch/i.html"
    query = f"?_nkw={item_name.replace(' ', '+')}"
    if sold_only:
        query += "&_sop=13&LH_Sold=1&LH_Complete=1"  # Sort by sold date, show sold items only
    return base_url + query


def extract_item_name(link: str) -> Optional[str]:
    """
    Extracts item name from eBay search URL.

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
        logger.warning(f"Failed to extract item name: {e}")
    return None


# =============================================================================
# Async Functions for Concurrent Processing
# =============================================================================

_async_page_cache: _PageCache = {}


async def fetch_page_content_async(link: str) -> Optional[str]:
    """
    Async version of fetch_page_content using Playwright.

    Uses exponential backoff retry (3 attempts) for transient failures.

    Args:
        link: URL to fetch

    Returns:
        str: Page content if successful, None otherwise
    """
    cached = _cache_get(_async_page_cache, link)
    if cached is not None:
        return cached

    attempts = 0
    max_attempts = 3
    last_error = None

    while attempts < max_attempts:
        attempts += 1
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                    page = await context.new_page()
                    await page.goto(link, timeout=30000)
                    await page.wait_for_selector("ul.srp-results", timeout=15000)
                    content = await page.content()
                    _cache_set(_async_page_cache, link, content)
                    return content
                finally:
                    await browser.close()
        except (AsyncPlaywrightTimeoutError, TimeoutError, ConnectionError) as e:
            last_error = e
            if attempts < max_attempts:
                wait_time = 2**attempts  # Exponential backoff: 2, 4, 8 seconds
                logger.warning(
                    f"Attempt {attempts}/{max_attempts} failed, retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
        except Exception as e:
            logger.error(f"Failed to fetch data from eBay: {e}")
            return None

    logger.error(
        f"Failed to fetch eBay page after {max_attempts} attempts: {last_error}"
    )
    return None


async def get_prices_by_link_async(link: str, sold_only: bool = False) -> List[float]:
    """
    Async version of get_prices_by_link.

    Args:
        link: eBay search URL
        sold_only: Whether to get sold prices only

    Returns:
        List[float]: List of valid prices found
    """
    item_name = extract_item_name(link)
    if item_name:
        try:
            api_prices = await get_prices_from_ebay_api_async(
                item_name,
                sold_only=sold_only,
            )
            if api_prices is not None:
                return api_prices
        except httpx.HTTPStatusError as e:
            if sold_only and e.response.status_code == 403:
                logger.warning(
                    "Sold/completed prices are unavailable because Marketplace Insights access is not enabled."
                )
                return []

            logger.error(
                "eBay API request failed with HTTP %s: %s",
                e.response.status_code,
                e.response.text,
            )
            return []
        except httpx.HTTPError as e:
            logger.error(f"eBay API request failed: {e}")
            return []

    content = await fetch_page_content_async(link)
    if not content:
        return []

    # parse_prices_from_html is CPU-bound, so we run it in a thread pool
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, parse_prices_from_html, content, sold_only)
