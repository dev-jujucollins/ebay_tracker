# eBay Price Tracker

Track what things actually cost on eBay over time, and get a Discord alert
when a specific listing shows up at or under your target price.

- Searches the official eBay Browse API with real filters (condition, price
  range, category, excluded words), so cases, parts and broken units do not
  pollute the numbers
- Fixed-price listings only: an auction's current bid is not a price
- Reports the **median**, 25th percentile and low, including shipping
- Stores every check in SQLite, so you build a price history
- Alerts once per listing (again only if its price drops), and remembers
  what it already sent across restarts

## Quick start

```bash
uv sync
cp .env.example .env                              # add your eBay keys
cp watchlist.example.yaml watchlist.yaml          # add your items
uv run ebay-tracker check "Steam Deck OLED 1TB" --min-price 250 --condition used
uv run ebay-tracker watch
```

eBay application keys are free: <https://developer.ebay.com/my/keys>. Use the
production keys; sandbox returns mock data.

## Configuration

Settings come from environment variables. A `.env` file in the working
directory is read as a fallback, and real environment variables win.

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `EBAY_CLIENT_ID` | yes | | eBay application client ID |
| `EBAY_CLIENT_SECRET` | yes | | eBay application client secret |
| `EBAY_ENVIRONMENT` | | `production` | `production` or `sandbox` |
| `DISCORD_WEBHOOK_URL` | | | Where alerts are posted. Without it alerts are only logged |
| `EBAY_MARKETPLACE` | | `EBAY_US` | eBay marketplace ID |
| `EBAY_CURRENCY` | | `USD` | Listings in other currencies are skipped |
| `EBAY_TRACKER_DB` | | `ebay_tracker.db` | SQLite file for history and sent alerts |

To get a webhook URL: Discord channel settings → Integrations → Webhooks.

## Watchlist

```yaml
items:
  - name: "Steam Deck OLED 1TB"
    target_price: 450.00
    condition: [used, open_box]
    min_price: 250
    exclude: ["for parts", "box only", "case"]
```

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Label in alerts and history. Also the search keywords unless `query` is set |
| `target_price` | yes | Alert when price + shipping is at or under this |
| `query` | | Search keywords, if different from the name |
| `condition` | | Any of `new`, `open_box`, `certified_refurbished`, `seller_refurbished`, `used`, `for_parts` |
| `min_price` / `max_price` | | Ignore listings outside this range |
| `exclude` | | Skip listings whose title contains any of these phrases |
| `category_id` | | Restrict to one eBay category |

`min_price` is the most effective filter: set it just under the lowest price a
real, working unit could plausibly sell for.

## Commands

```bash
ebay-tracker check <keywords> [--target N] [--condition C] [--min-price N]
                              [--max-price N] [--exclude TEXT]
ebay-tracker watch [--watchlist FILE] [--every SECONDS] [--no-alerts]
ebay-tracker history [NAME] [--limit N]
```

- `check` looks up one item, prints the summary and cheapest listings, and
  records the result. It never sends alerts.
- `watch` checks every watchlist item once and exits. Add `--every 1800` to
  keep it running instead.
- `history` lists tracked items, or shows recorded checks for one item.

Global options: `--db FILE`, `-v`.

## Running on a schedule

`watch` exits after one pass, so any scheduler works. With cron, every 30
minutes:

```cron
*/30 * * * * cd /path/to/ebay_tracker && /path/to/uv run ebay-tracker watch >> watch.log 2>&1
```

With Docker:

```bash
docker build -t ebay-tracker .
docker run --rm --env-file .env -v "$PWD:/data" ebay-tracker
```

The container reads `/data/watchlist.yaml` and writes `/data/ebay_tracker.db`.

## How a check works

1. Search up to 200 fixed-price listings matching the item's filters, drop
   excluded titles, and summarize price + shipping. This is the market
   snapshot that gets stored.
2. Search again sorted by price and capped at the target. Anything at or
   under target is a deal.
3. For each deal not already alerted at that price, post to Discord and
   record it. At most 3 alerts per item per run.

## The database

Three tables: `items`, `checks` (one row per snapshot) and `alerts`. It is a
plain SQLite file, so you can query it directly:

```bash
sqlite3 ebay_tracker.db "
  SELECT i.name, date(c.checked_at) AS day, ROUND(AVG(c.median), 2) AS median
  FROM checks c JOIN items i ON i.id = c.item_id
  GROUP BY i.name, day ORDER BY i.name, day;"
```

## Limitations

- No sold prices. eBay's only sold-price API (Marketplace Insights) is
  restricted, so everything here is based on active listings.
- Asking prices are not selling prices. The median of active listings runs
  higher than what items actually sell for.
- Each search reads one page (up to 200 listings), not the whole market.
- Unknown shipping cost is treated as zero.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
uv run pyright
```

```text
src/ebay_tracker/
├── cli.py        argument parsing and output
├── config.py     settings from the environment
├── watchlist.py  YAML loading and validation
├── ebay.py       eBay API client and search filters
├── stats.py      median and percentiles
├── storage.py    SQLite history and sent alerts
├── alerts.py     deal selection and Discord
└── tracker.py    ties a check together
```

## Upgrading from 0.1

- `python main.py "item"` is now `ebay-tracker check "item"`.
- `python main.py --watch --watch-once` is now `ebay-tracker watch`;
  `--watch-interval N` is now `--every N`.
- The Playwright scraper is gone, so API keys are required.
- Move `webhook_url` from `watchlist.yaml` to `DISCORD_WEBHOOK_URL`. The old
  key still works for now.
- `prices.csv` and `alerts.log` are no longer written. History lives in
  `ebay_tracker.db`.
