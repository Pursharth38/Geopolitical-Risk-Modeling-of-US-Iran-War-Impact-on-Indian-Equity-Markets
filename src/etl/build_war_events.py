"""
Milestone 1 — Track 2A, Step 2: build the curated war-events + Hormuz CSVs.

The classification (raw 384-entry scrape -> ~30 market-relevant milestones and a
Hormuz status timeline) was done by hand in two Excel workbooks. Those .xlsx are
the editable source of truth; this script does NOT re-do the judgment. It:

  1. reads the two workbooks,
  2. VALIDATES them against the raw scrape and the coding scheme, then
  3. emits clean, ISO-dated, snake_case pipeline CSVs the SQL/ETL layer can load.

Validation is the point: every curated event must trace back to a real scraped
row, scores must sit in range (channel scores are SIGNED — negative = de-escalation),
and the Hormuz timeline must be contiguous. Anything off is reported and fails
the run, so a bad edit in Excel can't slip silently into the pipeline.

Outputs: data_raw/war_events/war_events.csv, hormuz_status.csv,
and data_raw/_manifest_war_events.csv.

Usage:
    py src/etl/build_war_events.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime

import pandas as pd

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build_war_events")

# xlsx column -> clean pipeline column, in output order.
EVENT_COLS = {
    "Event ID": "event_id", "Rank": "rank", "Date": "date",
    "Days_Since_Start": "days_since_start", "Event": "event",
    "Severity (1-5)": "severity", "Category": "category",
    "Oil_Shock (0-3)": "oil_shock", "Gas_LNG_Shock (0-3)": "gas_lng_shock",
    "Shipping_Insurance (0-3)": "shipping_insurance", "India_Direct (0/1)": "india_direct",
    "Escalation_Dir (-1..1)": "escalation_dir", "Energy_Target (0/1)": "energy_target",
    "Countries_Count": "countries_count", "Est_NIFTY_Dir (-1..1)*": "est_nifty_dir",
    "Reasoning": "reasoning",
}
HORMUZ_COLS = {
    "Period ID": "period_id", "Date From": "date_from", "Date To": "date_to",
    "Days From Start": "days_from_start", "Days To (from start)": "days_to_start",
    "Strait Status": "strait_status", "Status Code (0-4)": "status_code",
    "Est. Lost bpd": "est_lost_bpd", "Is Estimate (Y/N)": "is_estimate",
    "Stranded Ships": "stranded_ships", "Source Row IDs": "source_row_ids",
    "Notes": "notes",
}


def _iso(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.strftime("%Y-%m-%d")


def _raw_ids() -> set[str]:
    raw = pd.read_csv(config.WIKI_TIMELINE_RAW_CSV)
    return set(raw["raw_id"].astype(str))


def build_events(raw_ids: set[str]) -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_excel(config.WAR_EVENTS_XLSX, sheet_name="Top 30 Events")
    df = df.rename(columns=EVENT_COLS)[list(EVENT_COLS.values())].copy()
    df["date"] = _iso(df["date"])
    df["provenance"] = "manual_curated"

    problems: list[str] = []
    # id linkage
    missing = [i for i in df["event_id"] if i not in raw_ids]
    if missing:
        problems.append(f"{len(missing)} event_id(s) not in raw scrape: {missing[:5]}")
    if df["event_id"].duplicated().any():
        problems.append("duplicate event_id(s) present")
    # score bounds (channel scores are signed)
    checks = {
        "severity": (1, 5), "oil_shock": (-3, 3), "gas_lng_shock": (-3, 3),
        "shipping_insurance": (-3, 3), "india_direct": (0, 1),
        "escalation_dir": (-1, 1), "energy_target": (0, 1), "est_nifty_dir": (-1, 1),
    }
    for col, (lo, hi) in checks.items():
        bad = df[(df[col] < lo) | (df[col] > hi)]
        if len(bad):
            problems.append(f"{col}: {len(bad)} value(s) outside [{lo},{hi}]")
    return df, problems


def build_hormuz(raw_ids: set[str]) -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_excel(config.HORMUZ_XLSX, sheet_name="Hormuz Status Timeline")
    df = df.rename(columns=HORMUZ_COLS)[list(HORMUZ_COLS.values())].copy()
    df["date_from"] = _iso(df["date_from"])
    df["date_to"] = _iso(df["date_to"])
    df["provenance"] = "manual_curated"

    problems: list[str] = []
    # id linkage (comma-separated)
    ids: list[str] = []
    for s in df["source_row_ids"].dropna():
        ids += [x.strip() for x in str(s).split(",") if x.strip()]
    miss = sorted({i for i in ids if i not in raw_ids})
    if miss:
        problems.append(f"{len(miss)} source_row_id(s) not in raw scrape: {miss[:5]}")
    # status code range
    bad = df[(df["status_code"] < 0) | (df["status_code"] > 4)]
    if len(bad):
        problems.append(f"status_code: {len(bad)} value(s) outside [0,4]")
    # contiguity
    d_from = pd.to_datetime(df["date_from"]); d_to = pd.to_datetime(df["date_to"])
    for i in range(1, len(df)):
        gap = (d_from.iloc[i] - d_to.iloc[i - 1]).days
        if gap != 1:
            problems.append(
                f"non-contiguous at {df['period_id'].iloc[i]}: "
                f"{d_to.iloc[i-1].date()} -> {d_from.iloc[i].date()} (gap {gap}d)"
            )
    return df, problems


def main() -> int:
    now = datetime.now().isoformat(timespec="seconds")
    raw_ids = _raw_ids()
    log.info("Raw scrape has %d ids for linkage checks.", len(raw_ids))

    events, ev_problems = build_events(raw_ids)
    hormuz, hz_problems = build_hormuz(raw_ids)

    manifest = []
    ok = True
    for name, df, probs, path, note in [
        ("war_events", events, ev_problems, config.WAR_EVENTS_CSV,
         "30 curated milestones, ID-linked to raw scrape. Channel scores SIGNED (neg=de-escalation)."),
        ("hormuz_status", hormuz, hz_problems, config.HORMUZ_STATUS_CSV,
         "14 status periods, contiguous. est_lost_bpd = analyst estimate, not source-measured."),
    ]:
        if probs:
            ok = False
            log.error("%s validation FAILED:", name)
            for p in probs:
                log.error("   - %s", p)
            status = "invalid"
        else:
            df.to_csv(path, index=False)
            log.info("%s OK -> %d rows -> %s", name, len(df),
                     path.relative_to(config.PROJECT_ROOT))
            status = "ok"
        manifest.append({
            "dataset": name, "rows": len(df),
            "coverage": f"{df.iloc[0, df.columns.get_loc('date') if 'date' in df.columns else 1]}"
                        f" … {df.iloc[-1, df.columns.get_loc('date') if 'date' in df.columns else 2]}",
            "status": status, "problems": "; ".join(probs) if probs else "",
            "note": note, "built_at": now,
        })

    pd.DataFrame(manifest).to_csv(config.WAR_EVENTS_MANIFEST_PATH, index=False)
    log.info("Manifest -> %s", config.WAR_EVENTS_MANIFEST_PATH.relative_to(config.PROJECT_ROOT))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
