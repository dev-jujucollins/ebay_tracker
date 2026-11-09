"""Command line interface: check one item, run the watchlist, show history."""

import argparse
import asyncio
import logging
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path

import httpx

from ebay_tracker import __version__
from ebay_tracker.alerts import money, send_discord
from ebay_tracker.config import ConfigError, Settings, load_settings
from ebay_tracker.ebay import CONDITION_IDS, EbayClient
from ebay_tracker.models import WatchItem
from ebay_tracker.storage import Store
from ebay_tracker.tracker import ItemReport, Notifier, Tracker
from ebay_tracker.watchlist import WatchlistError, load_watchlist

logger = logging.getLogger(__name__)


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ebay-tracker",
        description="Track eBay prices over time and alert on listings under target.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--db", type=Path, help="SQLite file (default: $EBAY_TRACKER_DB)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check one item now and record it")
    check.add_argument("name", nargs="+", help="search keywords")
    check.add_argument("--target", type=float, help="show listings at or under this")
    check.add_argument(
        "--condition", action="append", choices=sorted(CONDITION_IDS), default=[]
    )
    check.add_argument("--category-id")
    check.add_argument("--min-price", type=float)
    check.add_argument("--max-price", type=float)
    check.add_argument(
        "--exclude", action="append", default=[], help="skip titles containing this"
    )

    watch = commands.add_parser("watch", help="check the watchlist and send alerts")
    watch.add_argument("--watchlist", type=Path, default=Path("watchlist.yaml"))
    watch.add_argument(
        "--every",
        type=positive_seconds,
        metavar="SECONDS",
        help="keep running, checking this often (default: run once and exit)",
    )
    watch.add_argument(
        "--no-alerts", action="store_true", help="record prices but send nothing"
    )

    history = commands.add_parser("history", help="show recorded prices")
    history.add_argument("name", nargs="*", help="item name (omit to list items)")
    history.add_argument("--limit", type=int, default=20)
    return parser


def log_report(report: ItemReport, currency: str) -> None:
    item = report.item
    if report.error:
        return  # already logged by the tracker
    if report.summary is None:
        logger.warning("%s: no listings matched the filters", item.name)
        return

    summary = report.summary
    line = (
        f"{item.name}: median {money(summary.median, currency)} "
        f"(p25 {money(summary.p25, currency)}, low {money(summary.low, currency)}, "
        f"n={summary.count})"
    )
    if item.target_price is not None:
        line += (
            f"; {len(report.deals)} at/under {money(item.target_price, currency)}"
            f", {len(report.new_deals)} new"
        )
    logger.info(line)


async def run_check(args: argparse.Namespace, settings: Settings) -> int:
    settings.require_credentials()
    item = WatchItem(
        name=" ".join(args.name),
        target_price=args.target,
        condition=tuple(args.condition),
        category_id=args.category_id,
        min_price=args.min_price,
        max_price=args.max_price,
        exclude=tuple(args.exclude),
    )
    with Store(settings.db_path) as store:
        async with EbayClient(settings) as client:
            [report] = await Tracker(client, store).run([item], alert=False)

    if report.error:
        return 1
    if report.summary is None:
        print("No listings matched.")
        return 1

    currency = settings.currency
    summary = report.summary
    print(f"{item.name}: {summary.count} fixed-price listings")
    print(f"  median  {money(summary.median, currency)}")
    print(f"  p25     {money(summary.p25, currency)}")
    print(f"  low     {money(summary.low, currency)}")

    shown = report.deals if item.target_price is not None else report.cheapest
    label = "At or under target" if item.target_price is not None else "Cheapest"
    print(f"\n{label}:" if shown else f"\n{label}: none")
    for listing in shown[:5]:
        print(f"  {money(listing.total, currency):>12}  {listing.title[:70]}")
        print(f"  {'':>12}  {listing.url}")
    return 0


async def run_watch(args: argparse.Namespace, settings: Settings) -> int:
    settings.require_credentials()
    with Store(settings.db_path) as store:
        async with (
            EbayClient(settings) as client,
            httpx.AsyncClient(timeout=10.0) as discord_http,
        ):
            while True:
                # Reloaded every cycle so watchlist edits apply without a restart.
                watchlist = load_watchlist(args.watchlist)
                if not watchlist.items:
                    logger.warning("Watchlist has no items")

                webhook_url = settings.webhook_url or watchlist.webhook_url
                notify: Notifier | None = None
                if webhook_url:
                    notify = partial(send_discord, discord_http, webhook_url)

                tracker = Tracker(client, store, notify)
                reports = await tracker.run(watchlist.items, alert=not args.no_alerts)
                for report in reports:
                    log_report(report, settings.currency)

                failed = sum(1 for report in reports if report.error)
                if args.every is None:
                    return 1 if reports and failed == len(reports) else 0
                logger.info("Next check in %.0fs", args.every)
                await asyncio.sleep(args.every)


def run_history(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.db_path.is_file():
        print(f"No history yet ({settings.db_path} does not exist).")
        return 1

    currency = settings.currency
    with Store(settings.db_path) as store:
        if not args.name:
            for row in store.items():
                print(f"{row.name}  ({row.checks} checks, last {row.last_checked_at})")
            return 0

        name = " ".join(args.name)
        rows = store.history(name, limit=args.limit)
        if not rows:
            print(f"No history for {name!r}. Run 'ebay-tracker history' to list items.")
            return 1

        print(f"{'checked (UTC)':<20} {'n':>4} {'low':>11} {'p25':>11} {'median':>11}")
        for row in rows:
            print(
                f"{row.checked_at[:19].replace('T', ' '):<20} "
                f"{row.sample_size:>4} {money(row.low, currency):>11} "
                f"{money(row.p25, currency):>11} {money(row.median, currency):>11}"
            )
        lowest = store.lowest_median(name, days=30)
        if lowest is not None:
            print(
                f"\nLowest listed median in the last 30 days: {money(lowest, currency)}"
            )
    return 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # httpx logs full request URLs at INFO, which would leak the webhook URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        settings = load_settings()
        if args.db is not None:
            settings = replace(settings, db_path=args.db)

        if args.command == "history":
            code = run_history(args, settings)
        else:
            runner = run_check if args.command == "check" else run_watch
            code = asyncio.run(runner(args, settings))
    except (ConfigError, WatchlistError) as error:
        logger.error("%s", error)
        code = 2
    except KeyboardInterrupt:
        logger.info("Stopped")
        code = 130
    sys.exit(code)
