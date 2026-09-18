"""
Milestone 1 — fetch API-available market data from Yahoo Finance.

Pulls daily OHLCV series for every instrument declared in ``config.INSTRUMENTS``
(oil, FX, Indian indices/sectors, story stocks) over the project window and
writes one raw CSV per instrument into the matching ``data_raw/<category>/``
folder. A manifest CSV summarises every attempt (rows, date span, trading-day
gap check, status) so data quality is documented rather than assumed.

Design choices (kept deliberately "raw"):
  * One ticker per file — matches the folder-per-category layout and the
    Milestone 1 exit criterion of one complete series per instrument.
  * ``auto_adjust=False`` so both Close and Adj Close are preserved untouched;
    no cleaning, joining or transformation happens here (that is the ETL/SQL
    milestone's job).
  * Each ticker is fetched independently with a small retry loop, so one bad
    symbol never aborts the whole run.
  * Failures and empty responses are reported, not swallowed.

Usage:
    py src/etl/fetch_market_data.py            # full run, all instruments
    py src/etl/fetch_market_data.py --dry-run  # show what would be fetched
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

import config  # local module (run from project root or src/etl)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_market_data")

MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 2.0


def _download_one(ticker: str, start: str, end_exclusive: str) -> pd.DataFrame:
    """Download a single ticker's daily history, with a short retry loop.

    Returns a DataFrame indexed by Date (may be empty if Yahoo has no data for
    the window). Raises the last exception only if every retry errored.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = yf.download(
                ticker,
                start=start,
                end=end_exclusive,
                interval="1d",
                auto_adjust=False,   # keep Close and Adj Close both, untouched
                actions=False,
                progress=False,
                threads=False,
            )
            # yfinance can return column MultiIndex for a single ticker; flatten.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as exc:  # noqa: BLE001 - report and retry any API error
            last_exc = exc
            log.warning("  attempt %d/%d failed for %s: %s",
                        attempt, MAX_RETRIES, ticker, exc)
            time.sleep(RETRY_SLEEP_SECONDS)
    assert last_exc is not None
    raise last_exc


def _gap_check(df: pd.DataFrame) -> tuple[int, int]:
    """Return (n_rows, n_missing_business_days) for a quick QA signal.

    Missing business days = weekday sessions between the first and last date
    that have no row. This over-counts (market holidays are legitimately
    missing), so it is a flag to eyeball, not a hard failure.
    """
    if df.empty:
        return 0, 0
    idx = pd.to_datetime(df.index)
    all_bdays = pd.bdate_range(idx.min(), idx.max())
    missing = len(all_bdays.difference(idx.normalize()))
    return len(df), int(missing)


def fetch_all(dry_run: bool = False) -> list[dict]:
    """Fetch every configured instrument. Returns a list of manifest rows."""
    start = config.START_DATE
    # yfinance `end` is exclusive; add a day so today's session is included.
    end_exclusive = (date.fromisoformat(config.END_DATE) + timedelta(days=1)).isoformat()

    log.info("Window: %s -> %s (end exclusive %s)", start, config.END_DATE, end_exclusive)
    log.info("Instruments to fetch: %d", len(config.INSTRUMENTS))

    for d in config.DIRS.values():
        d.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []

    for category, ticker, label, slug in config.INSTRUMENTS:
        out_dir = config.DIRS[category]
        out_path = out_dir / f"{slug}_daily.csv"

        if dry_run:
            log.info("[dry-run] %-8s %-11s -> %s", category, ticker, out_path.name)
            continue

        log.info("Fetching %-11s (%s) ...", ticker, label)
        status = "ok"
        note = ""
        rows = missing = 0
        first = last = ""

        try:
            df = _download_one(ticker, start, end_exclusive)
        except Exception as exc:  # noqa: BLE001
            status, note = "error", str(exc)[:200]
            log.error("  FAILED %s: %s", ticker, note)
            df = pd.DataFrame()

        if status == "ok" and df.empty:
            status = "empty"
            note = "Yahoo returned no rows for this window/ticker"
            log.warning("  EMPTY  %s — %s", ticker, note)

        if not df.empty:
            df = df.sort_index()
            df.index.name = "Date"
            df.to_csv(out_path, index=True, date_format="%Y-%m-%d")
            rows, missing = _gap_check(df)
            first = pd.to_datetime(df.index).min().date().isoformat()
            last = pd.to_datetime(df.index).max().date().isoformat()
            log.info("  saved %d rows (%s -> %s), %d weekday gaps -> %s",
                     rows, first, last, missing, out_path.name)

        manifest.append({
            "category": category,
            "ticker": ticker,
            "label": label,
            "file": str(out_path.relative_to(config.PROJECT_ROOT)) if not df.empty else "",
            "rows": rows,
            "first_date": first,
            "last_date": last,
            "weekday_gaps": missing,
            "status": status,
            "note": note,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        })

    return manifest


def _write_manifest(manifest: list[dict]) -> None:
    if not manifest:
        return
    df = pd.DataFrame(manifest)
    config.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.MANIFEST_PATH, index=False)
    log.info("Manifest written -> %s", config.MANIFEST_PATH.relative_to(config.PROJECT_ROOT))


def _print_summary(manifest: list[dict]) -> None:
    counts: dict[str, int] = {}
    for row in manifest:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    log.info("Summary: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    problems = [m for m in manifest if m["status"] != "ok"]
    if problems:
        log.warning("%d instrument(s) need attention:", len(problems))
        for m in problems:
            log.warning("  %-11s [%s] %s", m["ticker"], m["status"], m["note"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch market data for the War Shock Stress Lab.")
    parser.add_argument("--dry-run", action="store_true",
                        help="List planned fetches without hitting the API.")
    args = parser.parse_args(argv)

    manifest = fetch_all(dry_run=args.dry_run)
    if args.dry_run:
        return 0

    _write_manifest(manifest)
    _print_summary(manifest)

    # Non-zero exit if nothing at all came back, so a scheduled/CI run can catch it.
    ok = sum(1 for m in manifest if m["status"] == "ok")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
