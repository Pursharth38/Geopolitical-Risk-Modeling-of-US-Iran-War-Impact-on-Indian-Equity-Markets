"""
Milestone 1 — Category 4: Indian macro & rates data (lowest priority).

This is the macro / policy leg of the story — it feeds the Milestone-3 stress
index and the dashboard macro pane, NOT the core daily regression. It is
inherently low-frequency and, per the Step-1 plan, allowed to be partial.

IMPORTANT — provenance. Free programmatic historical macro series are not
available in this environment (FRED times out, investing.com 403s,
TradingEconomics exposes only current snapshots, MOSPI is a JS shell). So the
monthly/quarterly figures below are **manually compiled from official releases**
(MOSPI, Office of Economic Adviser / PIB, RBI, CCIL) via web research on
2026-07-21, with each value carrying its own source URL. Holding them here (not
in a live scrape) makes the dataset reproducible and fully source-cited, and is
the curated approach the milestone plan sanctions for hard sources. They are
labelled `manual_compiled` in the CSVs so they are never mistaken for live data.

One thing IS fetched live: a best-effort current 10Y G-Sec yield from
TradingEconomics, for freshness (and to prove the source is reachable).

Outputs (data_raw/macro_india/): cpi_monthly.csv, wpi_monthly.csv,
gsec_10y.csv, cad_quarterly.csv, plus _manifest_macro_india.csv.

Usage:
    py src/etl/fetch_macro_india.py
"""

from __future__ import annotations

import io
import logging
import re
import sys
from datetime import datetime

import pandas as pd
import requests

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_macro_india")

_NOW = datetime.now().isoformat(timespec="seconds")

# --------------------------------------------------------------------------- #
# Curated official figures (manually researched 2026-07-21; each value sourced)
# --------------------------------------------------------------------------- #
# CPI headline inflation, YoY % (MOSPI; base rebased to 2024 in Jan 2026).
_CPI_SRC = "https://www.mospi.gov.in/themes/product/9-consumer-price-index-cpi"
CPI_MONTHLY = [
    # (month, inflation_yoy_pct)
    ("2026-01", 2.75), ("2026-02", 3.21), ("2026-03", 3.40),
    ("2026-04", 3.48), ("2026-05", 3.93), ("2026-06", 4.38),
]

# WPI inflation, YoY % (Office of Economic Adviser / PIB; base 2011-12).
# The Mar->Apr jump (3.88 -> 8.36) is the oil->wholesale-inflation war signal.
_WPI_SRC = "https://eaindustry.nic.in/pdf_files/cmonthly.pdf"
WPI_MONTHLY = [
    ("2026-01", 1.81), ("2026-02", 2.13), ("2026-03", 3.88),
    ("2026-04", 8.36), ("2026-05", 9.68), ("2026-06", 9.87),
]

# 10Y G-Sec benchmark yield, % (CCIL benchmark / TradingEconomics).
# Sparse on purpose — daily/full-monthly history is not freely obtainable
# (see module docstring); these are the verified points.
_GSEC_SRC = "https://tradingeconomics.com/india/government-bond-yield"
GSEC_POINTS = [
    # (date, yield_pct, note)
    ("2026-05-31", 7.03, "CCIL benchmark, May month-end"),
    ("2026-06-30", 7.00, "CCIL benchmark, Jun"),
    ("2026-07-20", 6.78, "TradingEconomics, intraday"),
]

# Current account balance (RBI). FY26 = Apr 2025 - Mar 2026; Q4 FY26 = Jan-Mar 2026.
# Positive cad_usd_bn = surplus.
_CAD_SRC = "https://www.business-standard.com/markets/capital-market-news/india-posts-usd-7-1-billion-current-account-surplus-in-q4-fy26-says-rbi-126060900331_1.html"
CAD_ROWS = [
    # (period, cad_usd_bn, cad_pct_gdp, note)
    ("Q4-FY26", 7.1, 0.7, "Surplus; Jan-Mar 2026 (pre/early-war quarter)"),
    ("FY26", -25.2, -0.6, "Full-year deficit Apr2025-Mar2026"),
]


def _write(df: pd.DataFrame, path) -> None:
    for attempt in range(1, 4):
        try:
            df.to_csv(path, index=False)
            return
        except PermissionError:
            if attempt == 3:
                raise
            import time
            time.sleep(2)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def build_cpi() -> pd.DataFrame:
    return pd.DataFrame([{
        "month": m, "inflation_yoy_pct": v, "measure": "CPI headline (YoY)",
        "unit": "percent", "provenance": "manual_compiled",
        "source": "MOSPI", "source_url": _CPI_SRC, "compiled_at": _NOW,
    } for m, v in CPI_MONTHLY])


def build_wpi() -> pd.DataFrame:
    return pd.DataFrame([{
        "month": m, "inflation_yoy_pct": v, "measure": "WPI (YoY)",
        "unit": "percent", "provenance": "manual_compiled",
        "source": "Office of Economic Adviser / PIB", "source_url": _WPI_SRC,
        "compiled_at": _NOW,
    } for m, v in WPI_MONTHLY])


def build_cad() -> pd.DataFrame:
    return pd.DataFrame([{
        "period": p, "cad_usd_bn": usd, "cad_pct_gdp": pct, "note": note,
        "provenance": "manual_compiled", "source": "RBI", "source_url": _CAD_SRC,
        "compiled_at": _NOW,
    } for p, usd, pct, note in CAD_ROWS])


def fetch_live_gsec() -> tuple[float | None, str]:
    """Best-effort current 10Y G-Sec yield from TradingEconomics."""
    try:
        r = requests.get(config.TE_GSEC_URL,
                         headers={"User-Agent": config.BROWSER_USER_AGENT}, timeout=40)
        r.raise_for_status()
        # The India 10Y row on the bonds table; grab the first plausible 6-7% value.
        m = re.search(r"India\D{0,40}?([67]\.\d{2})", r.text)
        if m:
            return float(m.group(1)), "live_tradingeconomics"
    except Exception as exc:  # noqa: BLE001
        log.warning("Live G-Sec fetch failed (using curated points only): %s", str(exc)[:80])
    return None, ""


def build_gsec() -> pd.DataFrame:
    rows = [{
        "date": d, "yield_pct": v, "note": note, "provenance": "manual_compiled",
        "source": "CCIL / TradingEconomics", "source_url": _GSEC_SRC, "compiled_at": _NOW,
    } for d, v, note in GSEC_POINTS]

    live_val, live_src = fetch_live_gsec()
    if live_val is not None:
        today = datetime.now().date().isoformat()
        rows = [r for r in rows if r["date"] != today]  # avoid dup on same day
        rows.append({
            "date": today, "yield_pct": live_val, "note": "auto-fetched current value",
            "provenance": "live_fetched", "source": "TradingEconomics",
            "source_url": _GSEC_SRC, "compiled_at": _NOW,
        })
        log.info("Live 10Y G-Sec fetched: %.2f%%", live_val)

    return pd.DataFrame(rows).drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main() -> int:
    config.DIRS["macro_india"].mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    jobs = [
        ("cpi_monthly", "monthly", config.MACRO_CPI_CSV, build_cpi,
         "CPI headline YoY, Jan-Jun 2026 (MOSPI). Manually compiled."),
        ("wpi_monthly", "monthly", config.MACRO_WPI_CSV, build_wpi,
         "WPI YoY, Jan-Jun 2026 (OEA/PIB). War signal in Apr. Manually compiled."),
        ("gsec_10y", "sparse/daily-live", config.MACRO_GSEC_CSV, build_gsec,
         "10Y G-Sec: 3 curated points + live current value. Full history not freely obtainable."),
        ("cad_quarterly", "quarterly", config.MACRO_CAD_CSV, build_cad,
         "Current account (RBI): Q4 FY26 + FY26 annual. Manually compiled."),
    ]

    for name, freq, path, builder, note in jobs:
        try:
            df = builder()
            _write(df, path)
            cov = (f"{df['month'].iloc[0]}–{df['month'].iloc[-1]}" if "month" in df.columns
                   else f"{df.iloc[0, 0]}…{df.iloc[-1, 0]}")
            log.info("%-13s -> %d rows (%s) -> %s", name, len(df), cov,
                     path.relative_to(config.PROJECT_ROOT))
            manifest.append({"dataset": name, "frequency": freq, "rows": len(df),
                             "coverage": cov, "status": "ok", "note": note,
                             "fetched_at": _NOW})
        except Exception as exc:  # noqa: BLE001
            log.error("%s FAILED: %s", name, exc)
            manifest.append({"dataset": name, "frequency": freq, "rows": 0, "coverage": "",
                             "status": "error", "note": str(exc)[:200], "fetched_at": _NOW})

    _write(pd.DataFrame(manifest), config.MACRO_MANIFEST_PATH)
    log.info("Manifest -> %s", config.MACRO_MANIFEST_PATH.relative_to(config.PROJECT_ROOT))
    return 0 if all(m["status"] == "ok" for m in manifest) else 1


if __name__ == "__main__":
    sys.exit(main())
