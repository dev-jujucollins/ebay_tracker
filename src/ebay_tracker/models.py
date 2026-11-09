"""Plain data types shared across the package."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WatchItem:
    """One thing to track, plus the filters that keep the search honest."""

    name: str
    target_price: float | None = None
    query: str | None = None
    condition: tuple[str, ...] = ()
    category_id: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    exclude: tuple[str, ...] = ()

    @property
    def search_query(self) -> str:
        """Keywords sent to eBay. Defaults to the item name."""
        return self.query or self.name


@dataclass(frozen=True)
class Listing:
    """One active eBay listing."""

    listing_id: str
    title: str
    price: float
    currency: str
    url: str
    shipping: float | None = None  # None means eBay did not say
    condition: str | None = None

    @property
    def total(self) -> float:
        """Price plus shipping, treating unknown shipping as zero."""
        return self.price + (self.shipping or 0.0)
