# eBay Price Tracker

Track eBay search prices, save local history, and run price alerts from a watchlist.

The tracker uses eBay Buy APIs when credentials are configured. Without API
credentials, it loads eBay search pages with Playwright, extracts listing
prices, removes outliers, calculates averages, and can send Discord alerts when
an item drops to or below a target price.

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

### 2. Configure eBay API credentials

API credentials are optional but recommended because eBay may block automated
HTML page loads.

Create `.env` from `.env.example` and fill in your eBay application keys:

```bash
cp .env.example .env
```

```dotenv
EBAY_CLIENT_ID=your-ebay-client-id
EBAY_CLIENT_SECRET=your-ebay-client-secret
EBAY_ENVIRONMENT=production
```

Use `sandbox` only when testing against eBay sandbox APIs. Sandbox responses use
eBay mock data, so real-world searches may return no useful listings until you
switch to production keys.

### 3. Run single-item mode

Search by item name:

```bash
uv run python main.py "Steam Deck OLED 1TB"
```

Or paste an eBay search URL:

```bash
uv run python main.py
```

### 4. Run watch mode

```bash
uv run python main.py --watch
```

By default, watch mode runs until stopped and checks every 300 seconds.

## Modes

### Single-item mode

Single-item mode:

- Accepts search terms or an eBay search URL
- Fetches listed prices from provided or generated search page
- Fetches sold prices from a generated sold-results search
- Prints listed and sold averages to terminal
- Appends one row to `prices.csv` when prices are found

Example:

```bash
uv run python main.py "Fujifilm X100V Black"
```

### Watch mode

Watch mode:

- Loads items from `watchlist.yaml`
- Checks each item against `target_price`
- Uses sold/completed results when `check_sold: true`
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
  - name: "Nintendo Switch 2"
    target_price: 400.00

  - name: "RTX 5090"
    target_price: 1800.00
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
Nintendo Switch 2 average price is now $389.50
That's $10.50 below your target of $400.00!
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
2. Use the eBay Browse API for active listings when `.env` credentials exist.
3. Use the Marketplace Insights API for sold/completed prices when credentials
   exist and the eBay application has access.
4. Load search pages with Playwright Chromium when API credentials are not
   configured.
5. Parse prices from API JSON or search results HTML.
6. Filter outliers with a Z-score rule.
7. Compute averages with NumPy.
8. Save results or send alerts depending on mode.

Implementation details:

- URL validation only accepts known eBay hostnames
- Active listings use `GET /buy/browse/v1/item_summary/search`
- Sold/completed listings use `GET /buy/marketplace_insights/v1_beta/item_sales/search`
  when the eBay application has access to that API
- API request failures are logged and return no prices for that check
- Fetch retry uses exponential backoff
- Watchlist processing uses async tasks with concurrency limit `3`
- HTML sold-price checks use eBay sold/complete-results search parameters

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
├── ebay_api.py
├── utils.py
├── pyproject.toml
├── watchlist.example.yaml
├── uv.lock
└── tests/
```

## Limitations

- Marketplace Insights access can be restricted by eBay; if your key lacks access,
  sold/completed prices will be unavailable
- Sandbox uses mock API data and will not represent production marketplace results
- Playwright fallback depends on eBay HTML structure and may be blocked by eBay
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
