# eBay Price Tracker

A Python tool that monitors eBay prices and sends alerts when items drop below your target price. Features automatic retry logic, concurrent processing, and Discord/Slack notifications.

## Features

- **Price Tracking** - Scrapes eBay search results and calculates average prices (with outlier removal)
- **Price Alerts** - Get notified when items drop below your target price
- **Webhook Notifications** - Send alerts to Discord, Slack, or any webhook endpoint
- **Retry Logic** - Automatic retry with exponential backoff for reliable scraping
- **Async Processing** - Check multiple items concurrently (up to 3 at a time)

## Installation

1. **Install uv** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

3. **Install browser** (Playwright uses Chromium to bypass bot protection):
   ```bash
   uv run playwright install chromium
   ```

## Usage

### Single Item Mode

Check the price of a single item:

```bash
uv run main.py "nintendo switch 2"
```

<img width="948" alt="Screenshot 2025-04-24 at 8 05 29 PM" src="https://github.com/user-attachments/assets/9425b8d9-0d4f-4c45-8224-854a882aa8d4" />

Or run without arguments to enter a URL manually:

```bash
uv run main.py
```

<img width="948" alt="Screenshot 2025-04-12 at 6 40 08 PM" src="https://github.com/user-attachments/assets/04169a9c-4a68-4324-a917-aeec97598cbe" />

Results are saved to `prices.csv`:

<img width="1043" alt="Screenshot 2025-04-13 at 12 09 57 PM" src="https://github.com/user-attachments/assets/536a602a-c63c-4260-8bc7-de9ea572fe52" />

### Watch Mode (Price Alerts)

Monitor multiple items and get notified when prices drop below your targets:

```bash
uv run main.py --watch
```

#### Setting Up Your Watchlist

Create a `watchlist.yaml` file:

```yaml
# Optional: Discord/Slack webhook for notifications
webhook_url: "https://discord.com/api/webhooks/your-webhook-id/your-token"

items:
  - name: "Nintendo Switch 2"
    target_price: 400.00

  - name: "RTX 5090"
    target_price: 1800.00
    check_sold: true  # Monitor sold prices instead of listings
```

#### Setting Up Discord Webhooks

1. Open Discord and go to your server
2. Right-click on a channel → **Edit Channel**
3. Go to **Integrations** → **Webhooks** → **New Webhook**
4. Copy the webhook URL and paste it in `watchlist.yaml`

When an item drops below your target, you'll receive an alert:

**Discord notification:**
> 🔔 **Price Alert!**
> **Nintendo Switch 2** average price is now **$389.99**
> That's $10.01 below your target of $400.00!
> [View on eBay](https://www.ebay.com/sch/i.html?_nkw=Nintendo+Switch+2)

Alerts are also logged to `alerts.log` for local tracking.

#### Custom Watchlist Path

```bash
uv run main.py --watch --watchlist my_items.yaml
```

## How It Works

1. **Scraping** - Uses Playwright (headless Chromium) to load eBay pages and bypass bot protection
2. **Price Extraction** - Parses search results and extracts prices from listings
3. **Outlier Removal** - Uses Z-score method to filter out anomalous prices
4. **Average Calculation** - Computes the mean of remaining prices
5. **Retry Logic** - Automatically retries failed requests with exponential backoff (2s → 4s → 8s)

## CLI Options

| Option | Description |
|--------|-------------|
| `<item>` | Item name to search (e.g., `"playstation 5"`) |
| `--watch`, `-w` | Run in watch mode to check watchlist for alerts |
| `--watchlist` | Path to watchlist YAML file (default: `watchlist.yaml`) |

## Project Structure

```
ebay_tracker/
├── main.py           # CLI entry point
├── utils.py          # Core scraping and price utilities
├── alerts.py         # Alert system and notifications
├── watchlist.yaml    # Your items to monitor
├── prices.csv        # Historical price data
├── alerts.log        # Alert history
└── tests/            # Test suite
```

## Development

Run tests:
```bash
uv run pytest -v
```

Lint and format:
```bash
uv run ruff check .
uv run ruff format .
```

Type checking:
```bash
uv run pyright
```
