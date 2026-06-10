"""eBay REST API client helpers."""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE_ID = "EBAY_US"
DEFAULT_LIMIT = 50
_TOKEN_SKEW_SECONDS = 60


@dataclass(frozen=True)
class EbayApiConfig:
    """eBay API configuration loaded from environment files."""

    client_id: str
    client_secret: str
    environment: str

    @property
    def api_base_url(self) -> str:
        """Return the API base URL for the configured environment."""
        if self.environment == "sandbox":
            return "https://api.sandbox.ebay.com"
        return "https://api.ebay.com"

    @property
    def oauth_url(self) -> str:
        """Return the OAuth token URL for the configured environment."""
        return f"{self.api_base_url}/identity/v1/oauth2/token"


@dataclass
class EbayToken:
    """Cached eBay OAuth token."""

    access_token: str
    expires_at: float

    def is_valid(self) -> bool:
        """Return whether the token can still be reused."""
        return time.time() < self.expires_at - _TOKEN_SKEW_SECONDS


# Not thread-safe: the sync path runs single-threaded. The async path guards
# refreshes with _async_token_lock.
_token_cache: dict[EbayApiConfig, EbayToken] = {}
_async_token_lock = asyncio.Lock()


def load_env_file(path: Path = Path(".env")) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from an env file."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key.strip()] = value

    return values


def get_ebay_api_config() -> EbayApiConfig | None:
    """Load eBay API configuration from .env."""
    values = load_env_file()
    client_id = values.get("EBAY_CLIENT_ID", "").strip()
    client_secret = values.get("EBAY_CLIENT_SECRET", "").strip()
    environment = values.get("EBAY_ENVIRONMENT", "production").strip().lower()

    if not client_id or not client_secret:
        return None

    if environment not in {"sandbox", "production"}:
        logger.warning("Invalid EBAY_ENVIRONMENT=%s; using production", environment)
        environment = "production"

    return EbayApiConfig(
        client_id=client_id,
        client_secret=client_secret,
        environment=environment,
    )


def _extract_price_value(money: Any) -> float | None:
    """Extract a float from an eBay money object."""
    if not isinstance(money, dict):
        return None

    value = money.get("value")
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _token_from_response(data: dict[str, Any]) -> EbayToken:
    """Build cached token from OAuth response data."""
    access_token = data.get("access_token")
    expires_in = data.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("eBay OAuth response did not include access_token")

    if isinstance(expires_in, int | float | str):
        expires_in_seconds = float(expires_in)
    else:
        expires_in_seconds = 7200

    return EbayToken(
        access_token=access_token,
        expires_at=time.time() + expires_in_seconds,
    )


def get_application_token(config: EbayApiConfig) -> str:
    """Mint or reuse an eBay application access token."""
    cached = _token_cache.get(config)
    if cached and cached.is_valid():
        return cached.access_token

    response = httpx.post(
        config.oauth_url,
        auth=(config.client_id, config.client_secret),
        data={
            "grant_type": "client_credentials",
            "scope": API_SCOPE,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    token = _token_from_response(response.json())
    _token_cache[config] = token
    return token.access_token


async def get_application_token_async(config: EbayApiConfig) -> str:
    """Async version of get_application_token."""
    cached = _token_cache.get(config)
    if cached and cached.is_valid():
        return cached.access_token

    async with _async_token_lock:
        cached = _token_cache.get(config)
        if cached and cached.is_valid():
            return cached.access_token

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                config.oauth_url,
                auth=(config.client_id, config.client_secret),
                data={
                    "grant_type": "client_credentials",
                    "scope": API_SCOPE,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            response.raise_for_status()
            token = _token_from_response(response.json())
            _token_cache[config] = token
            return token.access_token


def _request_headers(token: str) -> dict[str, str]:
    """Build headers for eBay Buy API requests."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
    }


def parse_browse_prices(data: dict[str, Any]) -> list[float]:
    """Extract active listing prices from Browse API search data."""
    item_summaries = data.get("itemSummaries")
    if not isinstance(item_summaries, list):
        return []

    prices: list[float] = []
    for item in item_summaries:
        if not isinstance(item, dict):
            continue

        price = _extract_price_value(item.get("price"))
        if price is None:
            price = _extract_price_value(item.get("currentBidPrice"))
        if price is not None:
            prices.append(price)

    return prices


def parse_sold_prices(data: dict[str, Any]) -> list[float]:
    """Extract sold prices from Marketplace Insights item sales data."""
    item_sales = data.get("itemSales")
    if not isinstance(item_sales, list):
        return []

    prices: list[float] = []
    for item in item_sales:
        if not isinstance(item, dict):
            continue

        price = _extract_price_value(item.get("lastSoldPrice"))
        if price is not None:
            prices.append(price)

    return prices


def get_prices_from_ebay_api(
    query: str, sold_only: bool = False, limit: int = DEFAULT_LIMIT
) -> list[float] | None:
    """Fetch prices from eBay REST APIs, if credentials are configured."""
    config = get_ebay_api_config()
    if config is None:
        return None

    token = get_application_token(config)
    endpoint = (
        "/buy/marketplace_insights/v1_beta/item_sales/search"
        if sold_only
        else "/buy/browse/v1/item_summary/search"
    )
    response = httpx.get(
        f"{config.api_base_url}{endpoint}",
        headers=_request_headers(token),
        params={
            "q": query,
            "limit": str(limit),
        },
        timeout=20.0,
    )
    response.raise_for_status()
    data = response.json()

    if sold_only:
        return parse_sold_prices(data)
    return parse_browse_prices(data)


async def get_prices_from_ebay_api_async(
    query: str, sold_only: bool = False, limit: int = DEFAULT_LIMIT
) -> list[float] | None:
    """Async version of get_prices_from_ebay_api."""
    config = get_ebay_api_config()
    if config is None:
        return None

    token = await get_application_token_async(config)
    endpoint = (
        "/buy/marketplace_insights/v1_beta/item_sales/search"
        if sold_only
        else "/buy/browse/v1/item_summary/search"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{config.api_base_url}{endpoint}",
            headers=_request_headers(token),
            params={
                "q": query,
                "limit": str(limit),
            },
        )
        response.raise_for_status()
        data = response.json()

    if sold_only:
        return parse_sold_prices(data)
    return parse_browse_prices(data)
