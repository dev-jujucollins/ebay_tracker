# eBay Price Tracker

Track eBay search prices, save local history, and run continuous price alerts from a watchlist.

This project uses Playwright to load eBay search pages, extracts listing prices, removes outliers, calculates averages, and can send Discord alerts when an item drops to or below a target price.

## What It Does

- Check one item from search terms or an eBay search URL
- Calculate average listed price
- Calculate average sold price when sold results exist
- Save single-item runs to `prices.csv`
- Monitor many items from `watchlist.yaml`
- Send Discord webhook alerts for below-target items
- Avoid duplicate alerts until an item rises back above target
- Retry transient page-load failures with exponential backoff
- Process watchlist items concurrently

## Quick Start

### 1. Install dependencies

```bash
uv sync
uv run playwright install chromium
```

### 2. Run single-item mode

Search by item name:

```bash
uv run python main.py "Steam Deck OLED 1TB"
```

Or paste an eBay search URL:

```bash
uv run python main.py
```

### 3. Run watch mode

```bash
uv run python main.py --watch
```

By default, watch mode runs forever and checks every 300 seconds.

## Modes

### Single-item mode

Single-item mode:

- Accepts search terms or an eBay search URL
- Fetches listed prices from provided or generated search page
- Fetches sold prices from a generated sold-results search
- Prints listed and sold averages to terminal
- Appends one row to `prices.csv`

Example:

```bash
uv run python main.py "Fujifilm X100V Black"
```

### Watch mode

Watch mode:

- Loads items from `watchlist.yaml`
- Checks each item against `target_price`
- Uses sold listings when `check_sold: true`
- Logs triggered alerts to `alerts.log`
- Optionally posts alerts to a Discord webhook
- Suppresses repeat alerts while an item remains below target

Examples:

```bash
uv run python main.py --watch
uv run python main.py --watch --watch-interval 120
uv run python main.py --watch --watch-once
uv run python main.py --watch --watchlist my_items.yaml
```

## Watchlist Format

Create `watchlist.yaml` in project root:

```yaml
# Optional: Discord webhook URL
webhook_url: "https://discord.com/api/webhooks/your-webhook-id/your-token"

items:
  - name: "Steam Deck OLED 1TB"
    target_price: 750.00
    check_sold: true

  - name: "Apple MacBook Air 13.6 A2681 M2 16GB 512GB"
    target_price: 780.00
    check_sold: true

  - name: "Fujifilm X100V Black"
    target_price: 2100.00
    check_sold: true
```

Rules:

- `items` must be present and must be a list
- Each item must have non-empty `name`
- Each item must have numeric `target_price`
- `check_sold` is optional and defaults to `false`
- `webhook_url` is optional

## Discord Alerts

To create Discord webhook:

1. Open Discord server settings for channel you want.
2. Go to `Integrations`.
3. Create webhook.
4. Paste URL into `watchlist.yaml`.

Alert payload looks like:

```text
🔔 Price Alert!
Steam Deck OLED 1TB average price is now $742.50
That's $7.50 below your target of $750.00!
View on eBay: https://www.ebay.com/...
```

## CLI Reference

| Option | Meaning |
| --- | --- |
| `<item>` | Item name to search, like `"Sony WH-1000XM5 Black"` |
| `--watch`, `-w` | Run continuous watch mode |
| `--watchlist` | Path to watchlist YAML file. Default: `watchlist.yaml` |
| `--watch-interval` | Seconds between watch checks. Default: `300` |
| `--watch-once` | Run one watch cycle, then exit |

## How It Works

1. Generate or validate eBay search URL.
2. Load page with Playwright Chromium.
3. Parse prices from search results HTML.
4. Filter outliers with a Z-score rule.
5. Compute averages with NumPy.
6. Save results or send alerts depending on mode.

Implementation details:

- URL validation only accepts known eBay hostnames
- Fetch retry uses exponential backoff
- Watchlist processing uses async tasks with concurrency limit `3`
- Sold-price checks use eBay sold/complete-results search parameters

## Files Created

| File | Purpose |
| --- | --- |
| `prices.csv` | History from single-item runs |
| `alerts.log` | Local log of triggered alerts |
| `watchlist.yaml` | User-defined watched items |

## Project Layout

```text
.
├── main.py
├── alerts.py
├── utils.py
├── watchlist.example.yaml
├── tests/
├── prices.csv
└── alerts.log
```

## Limitations

- Built around eBay search-result pages, not direct item pages
- Parsing depends on eBay HTML structure and may need updates if site changes
- Average price is heuristic, not market appraisal
- Outlier removal is lightweight and may not fit every niche market
- Watch mode keeps state in memory, so duplicate-alert suppression resets on restart

## Development

Install project plus dev tools:

```bash
uv sync
```

Run checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run pyright
```

## Notes

- Example watchlist lives in [watchlist.example.yaml](/Users/julius/Dev/ebay_tracker/watchlist.example.yaml)
- Main CLI entry is [main.py](/Users/julius/Dev/ebay_tracker/main.py)
