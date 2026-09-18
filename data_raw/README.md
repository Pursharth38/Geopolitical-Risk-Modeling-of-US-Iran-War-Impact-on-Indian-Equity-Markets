# data_raw/ — raw collected data & sourcing notes

Raw, untransformed data only. **No cleaning, joining, or transformation happens here** — that belongs to the ETL/SQL milestone. Files are kept exactly as pulled from the source.

## Market data (API — Yahoo Finance via `yfinance`)

Collected by `src/etl/fetch_market_data.py`. One CSV per instrument, daily frequency, window **2026-01-01 → present** (rolling, re-runnable). Every run rewrites `_manifest_market_data.csv`, which records rows, date span, a weekday-gap count, and status for each instrument — the authoritative QA record.

| Folder | Instruments | Yahoo symbols |
|---|---|---|
| `oil/` | Brent, WTI front-month futures | `BZ=F`, `CL=F` |
| `fx/` | USD/INR spot | `INR=X` |
| `indices/` | Nifty 50, Sensex, Nifty Bank/Energy/Auto/IT/Pharma/Metal | `^NSEI`, `^BSESN`, `^NSEBANK`, `^CNXENERGY`, `^CNXAUTO`, `^CNXIT`, `^CNXPHARMA`, `^CNXMETAL` |
| `stocks/` | OMCs (IOC, BPCL, HPCL), defence (HAL, BEL), airlines (IndiGo, SpiceJet) | `IOC.NS`, `BPCL.NS`, `HINDPETRO.NS`, `HAL.NS`, `BEL.NS`, `INDIGO.NS`, `SPICEJET.BO` |

**CSV columns:** `Date, Adj Close, Close, High, Low, Open, Volume`. Dates are ISO `YYYY-MM-DD`. Prices are as reported by Yahoo (`auto_adjust=False`, so `Close` is raw and `Adj Close` is dividend/split-adjusted).

### Known limitations / notes
- **Weekday "gaps"** in the manifest are almost entirely **Indian & commodity market holidays**, not missing data. They are flagged for eyeballing, not treated as errors.
- **SpiceJet** is not quoted on Yahoo under its NSE symbol (`SPICEJET.NS` → 404); the **BSE listing `SPICEJET.BO`** is used instead. Noted for consistency when joining later.
- Yahoo NSE **sector-index** symbols use the legacy `^CNX*` form; all six requested returned data in this run. If Yahoo drops coverage on a future re-run, the manifest will mark it `empty` rather than silently omit it.
- Indian macro data is **not** in this folder yet — a separate collection pass (see `STEP1_DATA_MILESTONE_PLAN.md`).

### How to re-run
```bash
py src/etl/fetch_market_data.py            # full pull, all instruments
py src/etl/fetch_market_data.py --dry-run  # list planned fetches only
```

## War events (scraped — Track 2A, Step 1)

Collected by `src/etl/scrape_war_events.py` from Wikipedia's **"Timeline of the 2026 Iran war"** page.

- `war_events/wiki_timeline_raw.csv` — **384 raw dated entries**, 2026-02-27 → present, 95 distinct dates. One row per event with `event_date` (ISO), `date_header`, `section` (sub-theme), `entry_type` (`p`/`li`), `text`, and an anchored `source_url` (deep-links to the exact date section).

**This is the raw, high-recall base — the Wikipedia timeline logs almost every day of the war.** The curated analysis tables below are derived from it (Track 2A Step 2). Minor cleaning applied during scrape (documented, non-destructive): inline citation superscripts (`[1]`) and edit-section links stripped; table/infobox/reference containers skipped. No facts altered.

### Curated tables (Track 2A, Step 2 — classification)

The market-relevant milestones and the Hormuz status timeline were **hand-classified** from the raw scrape in two Excel workbooks (the editable source of truth), then converted to pipeline CSVs by `src/etl/build_war_events.py`, which **validates every row against the raw scrape** before writing.

| File | Rows | Content |
|---|---|---|
| `war_events/war_events.csv` | 30 | Ranked market-moving events. Each `event_id` links back to `wiki_timeline_raw.csv`. Scoring: `severity` (1–5) + three **signed** channel axes (`oil_shock`, `gas_lng_shock`, `shipping_insurance`; negative = de-escalation) + `escalation_dir` (−1..1), `india_direct`, `energy_target`, `est_nifty_dir`, `reasoning`. |
| `war_events/hormuz_status.csv` | 14 | Contiguous Hormuz status periods (2026-02-27 → 07-16), `status_code` 0–4 (Open→Blockade) for the map, `est_lost_bpd`, `stranded_ships`, `source_row_ids` linking back to the raw scrape. |

**Provenance & caveats:** both tables are `provenance = manual_curated` (human judgment, not scraped). Channel sub-scores are **signed** despite the "(0-3)" label in the source workbook. `est_lost_bpd` is an **analyst estimate** for relative intensity, not a source-measured figure; only the ~3,200 stranded-ships figure (IMO, 18 Mar) is sourced. Source workbooks (`.xlsx`) are kept as the editable origin; re-running the build script re-validates and regenerates the CSVs.

### How to re-run
```bash
py src/etl/scrape_war_events.py     # (re)build the raw timeline dump
py src/etl/build_war_events.py      # validate the .xlsx and emit war_events.csv + hormuz_status.csv
```

## FII/FPI flows (Category 3)

Collected by `src/etl/fetch_fii_flows.py`. Single authoritative source: **NSDL FPI net investment** (secondary + primary + bulk deals, all exchanges) — the comprehensive series the analysis narrative is built on. Two frequencies, both from NSDL:

| File | Frequency | Coverage | Content |
|---|---|---|---|
| `fii_flows/nsdl_fpi_monthly.csv` | Monthly | Jan–Jul 2026 (7 rows) | Equity / debt / total net investment, ₹ crore. Headline totals. |
| `fii_flows/nsdl_fpi_daily.csv` | Daily | 2026-01-01 → latest (127 rows) | Per-date equity net (₹ cr + USD mn) and total net, from NSDL's Archive report. This is the series the daily Milestone-2 regression uses. |

The daily loop takes its **trading-date list from the collected Nifty series** (`indices/nifty50_daily.csv`), so the daily FII panel lines up 1:1 with the market panel.

**Scale check (and a cross-validation):** 2026 equity net = −₹2.63 lakh cr; total net = −₹1.85 lakh cr — consistent with the "₹1.8–1.9 lakh crore outflow" narrative. March (acute-war month) is the worst at −₹1.18 lakh cr equity. **The sum of daily equity net for March equals the monthly equity figure exactly (−₹1,17,775 cr)** — confirming the daily parse is correct.

### Access + known gaps (documented, not hidden)
- **Access:** NSDL rejects the default `requests` User-Agent (connection reset), so a desktop-browser UA is used. The daily report is an ASP.NET form — one postback per date, chaining the viewstate.
- **3 missing daily dates** (2026-02-19, 2026-03-19, 2026-04-01): NSDL itself returns "not available" for these — genuine no-data days, not a scrape error. 127/130 trading days captured.
- No news/mirror substitute is used (project decision) — NSDL is the only FII source.

### How to re-run
```bash
py src/etl/fetch_fii_flows.py                # monthly + daily (daily is incremental — only fetches missing dates)
py src/etl/fetch_fii_flows.py --skip-daily   # monthly only
```

## Indian macro & rates (Category 4)

Collected by `src/etl/fetch_macro_india.py`. The macro / policy leg of the story — feeds the Milestone-3 **stress index** and the dashboard macro pane; **not** a core-regression input, so it is low-priority and low-frequency by nature.

| File | Frequency | Coverage | Source |
|---|---|---|---|
| `macro_india/cpi_monthly.csv` | Monthly | Jan–Jun 2026 | MOSPI (CPI headline YoY) |
| `macro_india/wpi_monthly.csv` | Monthly | Jan–Jun 2026 | Office of Economic Adviser / PIB (WPI YoY) |
| `macro_india/gsec_10y.csv` | Sparse + live | 3 points (May–Jul) + live current | CCIL / TradingEconomics |
| `macro_india/cad_quarterly.csv` | Quarterly | Q4 FY26 + FY26 annual | RBI |

**The war signal is clearly visible:** WPI jumps **Mar 3.88% → Apr 8.36% → Jun 9.87%** (Fuel & Power +27%), and CPI climbs 2.75% → 4.38% — imported inflation from the oil shock.

### Provenance (important — read before using)
Free **programmatic** historical macro series are unavailable in this environment (FRED times out, investing.com 403s, TradingEconomics gives only current snapshots, MOSPI is a JS shell). So the monthly/quarterly values are **manually compiled from official releases** via web research (2026-07-21) — every row is tagged `provenance = manual_compiled` and carries its own `source_url`. They are *not* live-scraped. Only the current 10Y G-Sec value is fetched live (best-effort, tagged `live_fetched`).

### Known gaps (documented, not faked)
- **10Y G-Sec** is only 3 historical points — a full daily/monthly series is not freely obtainable (like FII daily); fuller history would need manual sourcing from CCIL/RBI.
- **CAD** is quarterly and the oil-shock quarter (Q1 FY27, Apr–Jun 2026) may not be released yet; only Q4 FY26 + the FY26 annual are in.
- This category is intentionally **partial**, per the Milestone 1 plan.

### How to re-run
```bash
py src/etl/fetch_macro_india.py
```
