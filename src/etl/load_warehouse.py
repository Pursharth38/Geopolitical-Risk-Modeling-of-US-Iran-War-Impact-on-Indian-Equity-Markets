"""
Milestone 2, Part A — build and populate the MySQL warehouse.

This is the Transform + Load step that Milestone 1 deliberately deferred:
reshape the raw per-instrument CSVs into the relational schema, compute daily
returns, expand the Hormuz periods to daily rows, derive supply shocks, and load
macro at its native frequency. Then a row-count sanity check.

Steps:
  1. CREATE DATABASE, run sql/schema.sql (9 tables + phases dimension).
  2. Build each table's DataFrame from data_raw/ and append it.
  3. Report row counts.

Credentials come from db_local.json / env vars via config.get_engine() — never
hardcoded. See db_local.example.json.

Usage:
    py src/etl/load_warehouse.py
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
import sys

import pandas as pd
from sqlalchemy import text

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("load_warehouse")

STOCK_SECTOR = {
    "ioc": "OMC", "bpcl": "OMC", "hpcl": "OMC",
    "hal": "Defence", "bel": "Defence",
    "indigo": "Airline", "spicejet": "Airline",
}


def _read_market(slug: str, category: str) -> pd.DataFrame:
    path = config.DIRS[category] / f"{slug}_daily.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df["date"] = df["Date"].dt.date
    # Drop the current session: fetch_market_data runs with END_DATE = today, so
    # Yahoo returns a live in-session bar whose close/volume are mid-day values
    # (e.g. Brent volume 3,751 against a typical 48,567). Loading it would put a
    # partial trading day into the returns series and the phase windows.
    today = _dt.date.today()
    partial = df["date"] == today
    if partial.any():
        log.info("  %s: dropping %d unsettled row(s) dated %s",
                 slug, int(partial.sum()), today.isoformat())
        df = df[~partial]
    return df


# --------------------------------------------------------------------------- #
# Table builders
# --------------------------------------------------------------------------- #
def build_oil() -> pd.DataFrame:
    b = _read_market("brent", "oil")[["date", "Close", "Volume"]]
    w = _read_market("wti", "oil")[["date", "Close"]]
    out = b.merge(w, on="date", how="outer", suffixes=("_b", "_w"))
    out = out.rename(columns={"Close_b": "brent_close", "Close_w": "wti_close",
                              "Volume": "volume"})
    return out[["date", "brent_close", "wti_close", "volume"]].sort_values("date")


def build_indices() -> pd.DataFrame:
    slugs = [s for (cat, _t, _l, s) in config.INSTRUMENTS if cat == "indices"]
    frames = []
    for slug in slugs:
        d = _read_market(slug, "indices").sort_values("date")
        d = d[d["Close"].notna()]  # drop Yahoo gap days before computing returns
        d["level"] = d["Close"]
        d["daily_return"] = d["Close"].pct_change()
        d["index_name"] = slug
        frames.append(d[["date", "index_name", "level", "daily_return"]])
    return pd.concat(frames, ignore_index=True)


def build_stocks() -> pd.DataFrame:
    slugs = [s for (cat, _t, _l, s) in config.INSTRUMENTS if cat == "stocks"]
    frames = []
    for slug in slugs:
        d = _read_market(slug, "stocks").sort_values("date")
        d = d[d["Close"].notna()]
        d["symbol"] = slug
        d["close"] = d["Close"]
        d["volume"] = d["Volume"]
        d["sector"] = STOCK_SECTOR.get(slug)
        frames.append(d[["date", "symbol", "close", "volume", "sector"]])
    return pd.concat(frames, ignore_index=True)


def build_fx() -> pd.DataFrame:
    d = _read_market("usd_inr", "fx")
    return d.rename(columns={"Close": "usd_inr_close"})[["date", "usd_inr_close"]]


def build_fii() -> pd.DataFrame:
    d = pd.read_csv(config.FII_DAILY_CSV, parse_dates=["date"])
    d["date"] = d["date"].dt.date
    d["net_equity_flow_inr"] = d["fpi_equity_net_cr"]
    d["asset_class"] = "equity"
    d["source"] = "NSDL_FPI_archive"
    return d[["date", "net_equity_flow_inr", "asset_class", "source"]]


def build_war_events() -> pd.DataFrame:
    ev = pd.read_csv(config.WAR_EVENTS_CSV, parse_dates=["date"])
    ev["date"] = ev["date"].dt.date
    raw = pd.read_csv(config.WIKI_TIMELINE_RAW_CSV, usecols=["raw_id", "source_url"])
    url = dict(zip(raw["raw_id"], raw["source_url"]))
    out = pd.DataFrame({
        "event_id": ev["event_id"],
        "date": ev["date"],
        "type": ev["category"],
        "description": ev["event"].str.slice(0, 500),
        "severity_score": ev["severity"],
        "source_url": ev["event_id"].map(url),
    })
    return out


def build_hormuz_daily() -> pd.DataFrame:
    h = pd.read_excel(config.HORMUZ_XLSX, sheet_name="Hormuz Status Timeline")
    rows = []
    for _, r in h.iterrows():
        for d in pd.date_range(r["Date From"], r["Date To"], freq="D"):
            rows.append({
                "date": d.date(),
                "status": r["Strait Status"],
                "status_code": int(r["Status Code (0-4)"]),
                "lost_bpd_estimate": int(r["Est. Lost bpd"]),
                "ships_stranded": (None if pd.isna(r["Stranded Ships"])
                                   else int(r["Stranded Ships"])),
                "source_row_ids": r["Source Row IDs"],
            })
    return pd.DataFrame(rows).drop_duplicates(subset="date", keep="first")


def build_oil_supply_shocks(hormuz: pd.DataFrame) -> pd.DataFrame:
    out = hormuz[["date", "lost_bpd_estimate"]].copy()
    out["source"] = "hormuz_status"
    out["scenario"] = "actual"
    return out


def build_macro() -> pd.DataFrame:
    cpi = pd.read_csv(config.MACRO_CPI_CSV)
    cpi["date"] = pd.to_datetime(cpi["month"] + "-01").dt.date
    cpi = cpi[["date", "inflation_yoy_pct"]].rename(columns={"inflation_yoy_pct": "cpi"})

    wpi = pd.read_csv(config.MACRO_WPI_CSV)
    wpi["date"] = pd.to_datetime(wpi["month"] + "-01").dt.date
    wpi = wpi[["date", "inflation_yoy_pct"]].rename(columns={"inflation_yoy_pct": "wpi"})

    gsec = pd.read_csv(config.MACRO_GSEC_CSV, parse_dates=["date"])
    gsec["date"] = gsec["date"].dt.date
    gsec = gsec[["date", "yield_pct"]].rename(columns={"yield_pct": "gsec_10y_yield"})

    cad = pd.read_csv(config.MACRO_CAD_CSV)
    # Keep only true quarterly points (skip the FY26 annual aggregate).
    cad = cad[cad["period"].str.startswith("Q")].copy()
    # Q4-FY26 (Jan-Mar 2026) -> quarter-end date.
    q_end = {"Q4-FY26": "2026-03-31"}
    cad["date"] = pd.to_datetime(cad["period"].map(q_end)).dt.date
    cad = cad[["date", "cad_usd_bn"]].rename(columns={"cad_usd_bn": "cad_estimate"})

    macro = cpi.merge(wpi, on="date", how="outer") \
               .merge(gsec, on="date", how="outer") \
               .merge(cad, on="date", how="outer")
    return macro.sort_values("date").reset_index(drop=True)


def build_phases() -> pd.DataFrame:
    return pd.DataFrame([{
        "phase_id": p["phase_id"], "name": p["name"],
        "start_date": pd.to_datetime(p["start"]).date(),
        "end_date": (None if p["end"] is None else pd.to_datetime(p["end"]).date()),
    } for p in config.PHASES])


# --------------------------------------------------------------------------- #
# Schema + load orchestration
# --------------------------------------------------------------------------- #
def _run_schema() -> None:
    """CREATE DATABASE, then run the table DDL from sql/schema.sql."""
    sql = (config.SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    # strip line comments
    sql = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    # 1) create the database on a server-level connection
    eng0 = config.get_engine(with_db=False)
    with eng0.begin() as conn:
        for st in statements:
            if st.upper().startswith("CREATE DATABASE"):
                conn.execute(text(st))
    eng0.dispose()

    # 2) run the rest (DROP/CREATE TABLE) inside the database
    eng = config.get_engine(with_db=True)
    with eng.begin() as conn:
        for st in statements:
            u = st.upper()
            if u.startswith("CREATE DATABASE") or u.startswith("USE "):
                continue
            conn.execute(text(st))
    eng.dispose()
    log.info("Schema created (database %s).", config.DB_NAME)


def main() -> int:
    _run_schema()
    hormuz = build_hormuz_daily()

    tables = {
        "phases": build_phases(),
        "oil_prices": build_oil(),
        "index_levels": build_indices(),
        "stock_prices": build_stocks(),
        "fx_rates": build_fx(),
        "fii_flows": build_fii(),
        "war_events": build_war_events(),
        "hormuz_status": hormuz,
        "oil_supply_shocks": build_oil_supply_shocks(hormuz),
        "macro_india": build_macro(),
    }

    eng = config.get_engine(with_db=True)
    for name, df in tables.items():
        df.to_sql(name, eng, if_exists="append", index=False)
        log.info("loaded %-18s %4d rows", name, len(df))

    # Row-count sanity check
    log.info("--- verification (DB counts) ---")
    with eng.connect() as conn:
        for name in tables:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
            log.info("  %-18s %4d", name, n)
    eng.dispose()
    log.info("Warehouse load complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
