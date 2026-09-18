"""
Milestone 1 — Category 3: FII/FPI flow collection (NSDL, the hardest source).

FII/FPI equity flows are the biggest transmission channel in the project's
story. Both outputs come from NSDL FPI net investment — the comprehensive,
authoritative series the analysis is built on (secondary + primary + bulk
deals, all exchanges):

  1. nsdl_fpi_monthly.csv  — monthly net investment (equity/debt/total), from
     the yearwise report. One fetch. Good for headline totals.

  2. nsdl_fpi_daily.csv    — DAILY equity/total net investment, from NSDL's
     Archive report. This is the series the daily Milestone-2 regression needs
     (~130 trading days). Collected one ASP.NET postback per trading date; the
     trading-date list is taken from the already-collected Nifty series so the
     daily FII panel aligns 1:1 with the market panel.

Access note: NSDL rejects the default `requests` User-Agent (connection reset),
so a desktop-browser UA is used. Tables are parsed with pandas.read_html, which
forward-fills the report's rowspan date/category cells into clean columns.

Usage:
    py src/etl/fetch_fii_flows.py                 # monthly + full daily
    py src/etl/fetch_fii_flows.py --skip-daily    # monthly only (fast)
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from datetime import date, datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_fii_flows")

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 3.0
DAILY_REQUEST_PAUSE = 0.4  # polite delay between NSDL postbacks


def _safe_to_csv(df: pd.DataFrame, path) -> None:
    """Write CSV, retrying a couple times on transient locks (OneDrive sync)."""
    for attempt in range(1, 4):
        try:
            df.to_csv(path, index=False)
            return
        except PermissionError as exc:
            if attempt == 3:
                raise
            log.warning("  write locked (%s) — retrying in 2s ...", path.name)
            time.sleep(2)


def _num(x) -> float | None:
    """Coerce an NSDL cell to a number. '(1,234.5)' -> -1234.5; blanks -> None."""
    if x is None:
        return None
    s = str(x).replace(",", "").replace("Rs.", "").replace("\xa0", "").strip()
    if s in ("", "-", "nan", "NaN"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# NSDL monthly
# --------------------------------------------------------------------------- #
def _get(session: requests.Session, url: str) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("  attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            time.sleep(RETRY_SLEEP_SECONDS)
    assert last_exc is not None
    raise last_exc


def fetch_nsdl_monthly(session: requests.Session) -> pd.DataFrame:
    """Parse the NSDL yearwise report into a clean monthly FPI table for FII_YEAR."""
    log.info("Fetching NSDL yearwise monthly FPI report (%d) ...", config.FII_YEAR)
    html = _get(session, config.NSDL_YEARWISE_URL)

    tables = pd.read_html(io.StringIO(html))
    target = None
    for t in tables:
        flat = " ".join(str(c) for c in t.columns.to_flat_index())
        if "Equity" in flat and str(config.FII_YEAR) in flat:
            target = t
            break
    if target is None:
        raise RuntimeError("Could not locate the monthly FPI table on the NSDL page.")

    raw = target.copy()
    raw.columns = range(raw.shape[1])
    rows = []
    for _, r in raw.iterrows():
        month = str(r[0]).strip()
        clean = month.replace(" **", "").strip()
        if clean not in MONTHS or month.lower().startswith("total"):
            continue
        rows.append({
            "year": config.FII_YEAR,
            "month": clean,
            "month_num": MONTHS.index(clean) + 1,
            "fpi_equity_net_cr": _num(r[1]),
            "fpi_debt_general_cr": _num(r[2]),
            "fpi_total_net_cr": _num(r[raw.shape[1] - 2]),
            "unit": "INR_crore",
            "source": "NSDL_FPI_yearwise",
            "source_url": config.NSDL_YEARWISE_URL,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        })
    return pd.DataFrame(rows).sort_values("month_num").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# NSDL daily (Archive report, one postback per trading date)
# --------------------------------------------------------------------------- #
def _viewstate(html: str) -> dict[str, str]:
    sp = BeautifulSoup(html, "lxml")
    out = {}
    for k in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        tag = sp.find("input", {"id": k})
        out[k] = tag.get("value", "") if tag else ""
    return out


def _trading_dates() -> list[date]:
    """Trading dates to query = the dates present in the collected Nifty series."""
    df = pd.read_csv(config.FII_TRADING_DATES_CSV)
    dates = pd.to_datetime(df["Date"]).dt.date.tolist()
    return sorted(d for d in dates if d <= date.today())


def _parse_daily_report(html: str, dmy: str) -> dict | None:
    """Extract the day's Equity Sub-total and grand Total net from one report."""
    tables = pd.read_html(io.StringIO(html))
    # The detail table is the wide one with >=8 columns and the date in col 0.
    detail = None
    for t in tables:
        if t.shape[1] >= 8 and (t.iloc[:, 0].astype(str) == dmy).any():
            detail = t
            break
    if detail is None:
        return None
    d = detail.copy()
    d.columns = range(d.shape[1])
    day = d[d[0].astype(str) == dmy]  # only that day's block (not month/year totals)

    eq = day[(day[1].astype(str) == "Equity") & (day[2].astype(str) == "Sub-total")]
    tot = day[day[2].astype(str) == "Total"]
    if eq.empty:
        return None
    return {
        "fpi_equity_net_cr": _num(eq.iloc[0][5]),
        "fpi_equity_net_usd_mn": _num(eq.iloc[0][6]),
        "fpi_total_net_cr": _num(tot.iloc[0][5]) if not tot.empty else None,
    }


def _post_date(session: requests.Session, dmy: str, state: dict) -> tuple[dict | None, dict]:
    """POST one date with a small backoff retry; return (parsed_or_None, new_state)."""
    for attempt in range(1, 3):
        try:
            payload = {
                "__EVENTTARGET": "btnSubmit1", "__EVENTARGUMENT": "",
                "txtDate": dmy, "hdnDate": dmy, "HdnValexceldata": "", "hdnFlag": "",
                **state,
            }
            resp = session.post(config.NSDL_ARCHIVE_URL, data=payload, timeout=30)
            resp.raise_for_status()
            return _parse_daily_report(resp.text, dmy), _viewstate(resp.text)
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                log.warning("  %s failed: %s", dmy, str(exc)[:80])
                return None, state
            time.sleep(3)  # back off, then refresh viewstate and retry
            try:
                state = _viewstate(_get(session, config.NSDL_ARCHIVE_URL))
            except Exception:  # noqa: BLE001
                pass
    return None, state


def fetch_nsdl_daily(session: requests.Session) -> pd.DataFrame:
    """Collect daily FPI net flows, INCREMENTALLY — only fetch dates not already
    saved, so re-runs are cheap and top up any earlier gaps."""
    dates = _trading_dates()

    existing = pd.DataFrame()
    have: set[str] = set()
    if config.FII_DAILY_CSV.exists():
        existing = pd.read_csv(config.FII_DAILY_CSV)
        have = set(existing["date"].astype(str))

    todo = [d for d in dates if d.isoformat() not in have]
    log.info("Daily FPI: %d trading dates total, %d already saved, %d to fetch ...",
             len(dates), len(have), len(todo))
    if not todo:
        return existing.sort_values("date").reset_index(drop=True)

    state = _viewstate(_get(session, config.NSDL_ARCHIVE_URL))
    rows, misses = [], []
    for i, dt in enumerate(todo, 1):
        dmy = dt.strftime("%d-%b-%Y")
        parsed, state = _post_date(session, dmy, state)
        if parsed is None:
            misses.append(dt.isoformat())
        else:
            rows.append({
                "date": dt.isoformat(), **parsed,
                "unit": "INR_crore (USD mn for *_usd_mn)",
                "source": "NSDL_FPI_archive", "source_url": config.NSDL_ARCHIVE_URL,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            })
        if i % 25 == 0:
            log.info("  ... %d/%d fetched (%d captured)", i, len(todo), len(rows))
        time.sleep(DAILY_REQUEST_PAUSE)

    if misses:
        log.warning("Daily: %d dates still returned no data: %s%s",
                    len(misses), ", ".join(misses[:8]), " ..." if len(misses) > 8 else "")

    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    combined = combined.drop_duplicates(subset="date", keep="last")
    return combined.sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect FII/FPI flows from NSDL.")
    parser.add_argument("--skip-daily", action="store_true",
                        help="Fetch monthly only (skip the per-date daily loop).")
    args = parser.parse_args(argv)

    config.DIRS["fii_flows"].mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": config.BROWSER_USER_AGENT})
    manifest: list[dict] = []
    now = datetime.now().isoformat(timespec="seconds")

    # 1) Monthly (headline totals).
    try:
        monthly = fetch_nsdl_monthly(session)
        _safe_to_csv(monthly, config.FII_MONTHLY_CSV)
        log.info("Monthly FPI: %d months, equity net YTD = %.0f cr -> %s",
                 len(monthly), monthly["fpi_equity_net_cr"].sum(),
                 config.FII_MONTHLY_CSV.relative_to(config.PROJECT_ROOT))
        manifest.append({
            "dataset": "nsdl_fpi_monthly", "frequency": "monthly", "rows": len(monthly),
            "coverage": f"{monthly['month'].iloc[0]}–{monthly['month'].iloc[-1]} {config.FII_YEAR}",
            "status": "ok", "note": "Headline monthly net investment.",
            "source": "NSDL_FPI_yearwise", "fetched_at": now,
        })
    except Exception as exc:  # noqa: BLE001
        log.error("NSDL monthly FAILED: %s", exc)
        manifest.append({"dataset": "nsdl_fpi_monthly", "frequency": "monthly", "rows": 0,
                         "coverage": "", "status": "error", "note": str(exc)[:200],
                         "source": "NSDL_FPI_yearwise", "fetched_at": now})

    # 2) Daily (the regression series).
    if args.skip_daily:
        log.info("Skipping daily (--skip-daily).")
    else:
        try:
            daily = fetch_nsdl_daily(session)
            if daily.empty:
                raise RuntimeError("no daily rows captured")
            _safe_to_csv(daily, config.FII_DAILY_CSV)
            log.info("Daily FPI: %d rows (%s -> %s) -> %s",
                     len(daily), daily["date"].iloc[0], daily["date"].iloc[-1],
                     config.FII_DAILY_CSV.relative_to(config.PROJECT_ROOT))
            manifest.append({
                "dataset": "nsdl_fpi_daily", "frequency": "daily", "rows": len(daily),
                "coverage": f"{daily['date'].iloc[0]} -> {daily['date'].iloc[-1]}",
                "status": "ok", "note": "Per-date NSDL Archive; equity + total net. "
                                        "Trading dates aligned to Nifty series.",
                "source": "NSDL_FPI_archive", "fetched_at": now,
            })
        except Exception as exc:  # noqa: BLE001
            log.error("NSDL daily FAILED: %s", exc)
            manifest.append({"dataset": "nsdl_fpi_daily", "frequency": "daily", "rows": 0,
                             "coverage": "", "status": "error", "note": str(exc)[:200],
                             "source": "NSDL_FPI_archive", "fetched_at": now})

    pd.DataFrame(manifest).to_csv(config.FII_MANIFEST_PATH, index=False)
    log.info("Manifest -> %s", config.FII_MANIFEST_PATH.relative_to(config.PROJECT_ROOT))

    ok = any(m["status"] == "ok" and m["dataset"] == "nsdl_fpi_monthly" for m in manifest)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
