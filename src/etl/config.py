"""
Central configuration for the War Shock Stress Lab data-collection layer.

Everything that a collection script needs to know but that might change
(date window, tickers, output locations, phase boundaries) lives here so the
fetch scripts stay logic-only and there is a single place to edit.

Milestone 1 scope: this module supports the API-available market data pull
(oil, indices, sectors, FX, story stocks). War events, FII flows and macro
data are collected by other means and are not driven from this file.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# Project root = two levels up from this file (src/etl/config.py -> project/).
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_RAW: Path = PROJECT_ROOT / "data_raw"

# One output directory per data category, matching the Milestone 1 plan.
DIRS: dict[str, Path] = {
    "oil": DATA_RAW / "oil",
    "indices": DATA_RAW / "indices",
    "stocks": DATA_RAW / "stocks",
    "fx": DATA_RAW / "fx",
    "war_events": DATA_RAW / "war_events",
    "fii_flows": DATA_RAW / "fii_flows",
    "macro_india": DATA_RAW / "macro_india",
}

# --------------------------------------------------------------------------- #
# War-events scraping (Track 2A, Step 1 — raw dated-entry dump)
# --------------------------------------------------------------------------- #
# The war has no API. This is the highest-coverage, best-structured public
# source: Wikipedia's day-by-day timeline. The scraper pulls EVERY dated entry
# (far more than are market-relevant); classification into the curated
# war_events table is a later, judgment step — not part of scraping.
WIKI_TIMELINE_URL: str = "https://en.wikipedia.org/wiki/Timeline_of_the_2026_Iran_war"
WAR_EVENTS_YEAR: int = 2026  # every date header on the page is in 2026
WIKI_TIMELINE_RAW_CSV: Path = DATA_RAW / "war_events" / "wiki_timeline_raw.csv"

# Track 2A, Step 2 — human-curated classification (built manually in Excel from
# the raw scrape). The .xlsx are the editable source of truth; build_war_events.py
# validates them (every id must resolve to the raw scrape) and emits clean
# pipeline CSVs. NOTE: channel sub-scores are SIGNED (negative = de-escalation),
# despite the "(0-3)" header text; est_lost_bpd is an analyst estimate.
WAR_EVENTS_XLSX: Path = DATA_RAW / "war_events" / "Iran_War_2026_Top30_Events.xlsx"
HORMUZ_XLSX: Path = DATA_RAW / "war_events" / "Hormuz_Status_Timeline.xlsx"
WAR_EVENTS_CSV: Path = DATA_RAW / "war_events" / "war_events.csv"
HORMUZ_STATUS_CSV: Path = DATA_RAW / "war_events" / "hormuz_status.csv"
WAR_EVENTS_MANIFEST_PATH: Path = DATA_RAW / "_manifest_war_events.csv"

# Polite identifying User-Agent (Wikipedia asks scrapers to identify themselves).
SCRAPER_USER_AGENT: str = (
    "WarShockStressLab/1.0 (educational research project; "
    "contact: Kaushalpurusharth45@gmail.com)"
)

# A machine-readable record of every file written, for traceability / QA.
MANIFEST_PATH: Path = DATA_RAW / "_manifest_market_data.csv"

# --------------------------------------------------------------------------- #
# FII/FPI flows (Milestone 1, Category 3 — the hardest source)
# --------------------------------------------------------------------------- #
# Source = NSDL FPI net investment (secondary + primary + bulk deals, all
# exchanges) — the comprehensive, authoritative series the analysis is built on
# (matches the ~ -1.85 lakh crore total outflow for 2026). Verified 2026-07:
# NSDL is reachable with browser headers.
#
# Two frequencies, both from NSDL:
#   * Monthly  — from the yearwise report (single fetch).
#   * Daily    — from the Archive report, one ASP.NET postback per trading date
#                (btnSubmit1 with the date in hdnDate). Trading dates are taken
#                from the already-collected Nifty series so the daily FII panel
#                lines up 1:1 with the market panel.
NSDL_YEARWISE_URL: str = "https://www.fpi.nsdl.co.in/Reports/Yearwise.aspx?RptType=6"
NSDL_ARCHIVE_URL: str = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
FII_YEAR: int = 2026

# Source of the trading-date list for the daily loop (an existing market file).
FII_TRADING_DATES_CSV: Path = DATA_RAW / "indices" / "nifty50_daily.csv"

FII_MONTHLY_CSV: Path = DATA_RAW / "fii_flows" / "nsdl_fpi_monthly.csv"
FII_DAILY_CSV: Path = DATA_RAW / "fii_flows" / "nsdl_fpi_daily.csv"
FII_MANIFEST_PATH: Path = DATA_RAW / "_manifest_fii_flows.csv"

# A desktop browser UA — NSDL rejects the default requests UA (the fix for the
# ECONNRESET/refused-connection we first hit).
BROWSER_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# --------------------------------------------------------------------------- #
# Indian macro & rates (Milestone 1, Category 4 — lowest priority, low-frequency)
# --------------------------------------------------------------------------- #
# Context leg (real economy / policy), not a daily-regression input. Feeds the
# Milestone-3 stress index and the dashboard macro pane.
#
# Frequency reality (verified 2026-07): free PROGRAMMATIC historical series are
# unavailable in this environment — FRED times out, investing.com 403s,
# TradingEconomics exposes only current snapshots, MOSPI is a JS shell. So the
# monthly/quarterly series are MANUALLY COMPILED from official releases (MOSPI,
# Office of Economic Adviser/PIB, RBI, CCIL) via web research, each value
# source-cited in fetch_macro_india.py. Daily G-Sec history is not obtainable
# (like FII daily) and is left for manual sourcing. A best-effort LIVE current
# G-Sec value is scraped from TradingEconomics for freshness.
TE_GSEC_URL: str = "https://tradingeconomics.com/india/government-bond-yield"

MACRO_CPI_CSV: Path = DATA_RAW / "macro_india" / "cpi_monthly.csv"
MACRO_WPI_CSV: Path = DATA_RAW / "macro_india" / "wpi_monthly.csv"
MACRO_GSEC_CSV: Path = DATA_RAW / "macro_india" / "gsec_10y.csv"
MACRO_CAD_CSV: Path = DATA_RAW / "macro_india" / "cad_quarterly.csv"
MACRO_MANIFEST_PATH: Path = DATA_RAW / "_manifest_macro_india.csv"

# --------------------------------------------------------------------------- #
# Time window
# --------------------------------------------------------------------------- #
# Start of the pre-war baseline. End is rolling ("today") because the war is
# ongoing and collection is meant to be re-runnable. yfinance treats `end` as
# exclusive, so the fetcher adds one day when it calls the API.
START_DATE: str = "2026-01-01"
END_DATE: str = _dt.date.today().isoformat()

# --------------------------------------------------------------------------- #
# War phases (kept here so any script can tag/annotate by phase without
# re-deriving them). Boundaries are a working draft — see MEMORY.md.
# --------------------------------------------------------------------------- #
PHASES: list[dict] = [
    {"phase_id": 1, "name": "Pre-war baseline",            "start": "2026-01-01", "end": "2026-02-27"},
    {"phase_id": 2, "name": "Acute war I",                 "start": "2026-02-28", "end": "2026-04-07"},
    {"phase_id": 3, "name": "First ceasefire",             "start": "2026-04-08", "end": "2026-04-12"},
    {"phase_id": 4, "name": "Naval blockade / brinkmanship","start": "2026-04-13", "end": "2026-06-13"},
    {"phase_id": 5, "name": "MoU / de-escalation",         "start": "2026-06-14", "end": "2026-07-06"},
    # Phase 6 starts on the ceasefire break itself: wt_0374 (2026-07-07, severity 4,
    # escalation_dir=+1, "Iran strikes Qatari LNG tanker; US revokes Iran oil deal").
    # It previously sat on the last day of phase 5, i.e. a severity-4 ESCALATION event
    # classified inside the "MoU / de-escalation" window. Note the market reaction lands
    # on 2026-07-08 (nifty50 -2.12%; 07-07 was flat at -0.13%) because a 07-07 US-time
    # event breaks after the 15:30 IST close — the event date and the reaction date are
    # legitimately different, and the phase is defined on the EVENT date.
    {"phase_id": 6, "name": "Renewed conflict",            "start": "2026-07-07", "end": None},  # open-ended
]

# --------------------------------------------------------------------------- #
# Instruments
# --------------------------------------------------------------------------- #
# Each entry: (category, yahoo_ticker, human_label, output_slug)
#   category    -> which data_raw/ subfolder it lands in (must be a key in DIRS)
#   yahoo_ticker-> the symbol passed to yfinance
#   human_label -> readable name kept in the manifest
#   output_slug -> base filename (…_daily.csv) so files are named by instrument,
#                  not by exchange symbol (which can contain ^, =, . characters)
#
# Note on Yahoo NSE sector-index symbols: several use the legacy "^CNX*" form
# and Yahoo's coverage of them is inconsistent. They are attempted here on
# purpose; the fetcher records which ones return no data rather than silently
# dropping them, so gaps are documented (per the Milestone 1 quality bar).
INSTRUMENTS: list[tuple[str, str, str, str]] = [
    # --- Crude oil (front-month futures) ---
    ("oil",     "BZ=F",       "Brent Crude front-month",   "brent"),
    ("oil",     "CL=F",       "WTI Crude front-month",     "wti"),

    # --- Currency ---
    ("fx",      "INR=X",      "USD/INR spot",              "usd_inr"),

    # --- Headline Indian equity indices ---
    ("indices", "^NSEI",      "Nifty 50",                  "nifty50"),
    ("indices", "^BSESN",     "BSE Sensex",                "sensex"),

    # --- Nifty sector indices (legacy Yahoo symbols; coverage varies) ---
    ("indices", "^NSEBANK",   "Nifty Bank",                "nifty_bank"),
    ("indices", "^CNXENERGY", "Nifty Energy",              "nifty_energy"),
    ("indices", "^CNXAUTO",   "Nifty Auto",                "nifty_auto"),
    ("indices", "^CNXIT",     "Nifty IT",                  "nifty_it"),
    ("indices", "^CNXPHARMA", "Nifty Pharma",              "nifty_pharma"),
    ("indices", "^CNXMETAL",  "Nifty Metal",               "nifty_metal"),

    # --- Story stocks (NSE tickers use the .NS suffix) ---
    # Oil marketing companies (expected "war losers")
    ("stocks",  "IOC.NS",       "Indian Oil Corp (OMC)",   "ioc"),
    ("stocks",  "BPCL.NS",      "Bharat Petroleum (OMC)",  "bpcl"),
    ("stocks",  "HINDPETRO.NS", "Hindustan Petroleum (OMC)","hpcl"),
    # Defence (expected "war winners")
    ("stocks",  "HAL.NS",       "Hindustan Aeronautics",   "hal"),
    ("stocks",  "BEL.NS",       "Bharat Electronics",      "bel"),
    # Airlines (expected "war losers" — fuel cost)
    ("stocks",  "INDIGO.NS",    "InterGlobe / IndiGo",     "indigo"),
    # SpiceJet is not quoted on Yahoo under its NSE symbol; use the BSE listing.
    ("stocks",  "SPICEJET.BO",  "SpiceJet (BSE listing)",  "spicejet"),
]


# --------------------------------------------------------------------------- #
# Milestone 2 — MySQL warehouse connectivity
# --------------------------------------------------------------------------- #
# Credentials are read from environment variables first, then from a local
# gitignored file `db_local.json` at the project root (copy db_local.example.json).
# The password is NEVER hardcoded in tracked source.
import json as _json
import os as _os
from urllib.parse import quote_plus as _quote

DB_NAME: str = "war_shock_lab"
DB_LOCAL_FILE: Path = PROJECT_ROOT / "db_local.json"

# Directory for the SQL files (schema / views / analytics).
SQL_DIR: Path = PROJECT_ROOT / "sql"


def _db_creds() -> dict:
    creds = {
        "host": _os.environ.get("MYSQL_HOST", "localhost"),
        "port": int(_os.environ.get("MYSQL_PORT", "3306")),
        "user": _os.environ.get("MYSQL_USER"),
        "password": _os.environ.get("MYSQL_PASSWORD"),
        "database": _os.environ.get("MYSQL_DB", DB_NAME),
    }
    if (not creds["user"] or creds["password"] is None) and DB_LOCAL_FILE.exists():
        f = _json.loads(DB_LOCAL_FILE.read_text())
        for k, v in f.items():
            if creds.get(k) in (None, ""):
                creds[k] = v
    return creds


def get_engine(with_db: bool = True):
    """SQLAlchemy engine for the MySQL warehouse.

    with_db=False connects to the server without selecting a database (used to
    CREATE DATABASE on first run).
    """
    from sqlalchemy import create_engine

    c = _db_creds()
    if not c["user"] or c["password"] is None:
        raise RuntimeError(
            "MySQL credentials not found. Create db_local.json (see "
            "db_local.example.json) or set MYSQL_USER / MYSQL_PASSWORD env vars."
        )
    db = c["database"] if with_db else ""
    url = (f"mysql+mysqlconnector://{c['user']}:{_quote(str(c['password']))}"
           f"@{c['host']}:{c['port']}/{db}")
    return create_engine(url)
