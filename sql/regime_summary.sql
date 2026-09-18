-- War Shock Stress Lab — Milestone 3, Component 1: regime classification.
--
-- Purpose: formalise the 6 war phases into a reference table of "what does each
-- regime typically look like", so the stress index (Component 2) and historical
-- benchmarking (Component 3) have an agreed reference point instead of
-- re-deriving phase characteristics from scratch.
--
-- These are SAVED VIEWS, not a static result: re-running load_warehouse.py and
-- selecting from them reproduces the table against refreshed data (the exit
-- criterion for this component).
--
-- Source: india_stress_panel (which already tags phase_id by date-range join and
-- forward-fills macro from its native frequency).
--
-- Three views:
--   regime_summary         wide  — one row per phase, one column per variable (means)
--   regime_summary_detail  long  — per (phase, variable): n, mean, sd, min, max
--   regime_dynamics        path  — entry/exit levels and the move across each phase
--
-- Honesty notes carried into the output:
--   * n_obs is reported next to every statistic. The 10Y G-Sec series has only 3
--     published points (first on 2026-05-31), so phases 1-3 have ZERO observations
--     and their yield statistics are NULL by construction — not zero, not filled.
--   * cpi / wpi are monthly series forward-filled inside india_stress_panel, so a
--     phase "mean" is the average of the prevailing published value across the
--     phase's trading days, not an average of distinct monthly prints.
--   * nifty_return is stored as a FRACTION; it is multiplied by 100 here and the
--     unit column says so.

USE war_shock_lab;

-- ---------------------------------------------------------------------------
-- 1. regime_summary — the headline reference table.
--    One row per phase, one column per variable, showing the phase mean.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW regime_summary AS
SELECT
    phase_id,
    phase_name,
    MIN(date)                                   AS start_date,
    MAX(date)                                   AS end_date,
    COUNT(*)                                    AS n_trading_days,
    ROUND(AVG(brent_close), 2)                  AS brent_avg_usd,
    ROUND(AVG(usd_inr), 3)                      AS usd_inr_avg,
    ROUND(AVG(fii_net_flow), 0)                 AS fii_avg_daily_cr,
    ROUND(AVG(nifty_return) * 100, 3)           AS nifty_ret_avg_pct,
    ROUND(STDDEV_SAMP(nifty_return) * 100, 3)   AS nifty_vol_daily_pct,
    ROUND(AVG(gsec_10y_yield), 3)               AS gsec_10y_avg_pct,
    COUNT(gsec_10y_yield)                       AS gsec_n_obs,  -- 0 for phases 1-3
    ROUND(AVG(cpi), 3)                          AS cpi_avg_pct,
    ROUND(AVG(wpi), 3)                          AS wpi_avg_pct
FROM india_stress_panel
GROUP BY phase_id, phase_name;

-- ---------------------------------------------------------------------------
-- 2. regime_summary_detail — the same data in long format with a spread measure.
--    One row per (phase, variable): observation count, mean, sd, min, max.
--    UNION ALL rather than a pivot so each variable's coverage is explicit.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW regime_summary_detail AS
SELECT phase_id, phase_name, 1 AS var_order, 'brent' AS variable, 'USD/bbl' AS unit,
       COUNT(*) AS n_days, COUNT(brent_close) AS n_obs,
       ROUND(AVG(brent_close), 2) AS mean_val,
       ROUND(STDDEV_SAMP(brent_close), 2) AS sd_val,
       ROUND(MIN(brent_close), 2) AS min_val,
       ROUND(MAX(brent_close), 2) AS max_val
FROM india_stress_panel GROUP BY phase_id, phase_name
UNION ALL
SELECT phase_id, phase_name, 2, 'usd_inr', 'INR per USD',
       COUNT(*), COUNT(usd_inr),
       ROUND(AVG(usd_inr), 3), ROUND(STDDEV_SAMP(usd_inr), 3),
       ROUND(MIN(usd_inr), 3), ROUND(MAX(usd_inr), 3)
FROM india_stress_panel GROUP BY phase_id, phase_name
UNION ALL
SELECT phase_id, phase_name, 3, 'fii_net_flow', 'INR crore/day',
       COUNT(*), COUNT(fii_net_flow),
       ROUND(AVG(fii_net_flow), 0), ROUND(STDDEV_SAMP(fii_net_flow), 0),
       ROUND(MIN(fii_net_flow), 0), ROUND(MAX(fii_net_flow), 0)
FROM india_stress_panel GROUP BY phase_id, phase_name
UNION ALL
SELECT phase_id, phase_name, 4, 'nifty_return', '% per day',
       COUNT(*), COUNT(nifty_return),
       ROUND(AVG(nifty_return) * 100, 3), ROUND(STDDEV_SAMP(nifty_return) * 100, 3),
       ROUND(MIN(nifty_return) * 100, 3), ROUND(MAX(nifty_return) * 100, 3)
FROM india_stress_panel GROUP BY phase_id, phase_name
UNION ALL
SELECT phase_id, phase_name, 5, 'gsec_10y_yield', '% yield',
       COUNT(*), COUNT(gsec_10y_yield),
       ROUND(AVG(gsec_10y_yield), 3), ROUND(STDDEV_SAMP(gsec_10y_yield), 3),
       ROUND(MIN(gsec_10y_yield), 3), ROUND(MAX(gsec_10y_yield), 3)
FROM india_stress_panel GROUP BY phase_id, phase_name
UNION ALL
SELECT phase_id, phase_name, 6, 'cpi', '% YoY (ffilled)',
       COUNT(*), COUNT(cpi),
       ROUND(AVG(cpi), 3), ROUND(STDDEV_SAMP(cpi), 3),
       ROUND(MIN(cpi), 3), ROUND(MAX(cpi), 3)
FROM india_stress_panel GROUP BY phase_id, phase_name
UNION ALL
SELECT phase_id, phase_name, 7, 'wpi', '% YoY (ffilled)',
       COUNT(*), COUNT(wpi),
       ROUND(AVG(wpi), 3), ROUND(STDDEV_SAMP(wpi), 3),
       ROUND(MIN(wpi), 3), ROUND(MAX(wpi), 3)
FROM india_stress_panel GROUP BY phase_id, phase_name;

-- ---------------------------------------------------------------------------
-- 3. regime_dynamics — supplementary: the PATH through each regime, not just its
--    average level. Averages alone hide direction (a phase can average Brent 95
--    while falling from 105 to 85), and the stress index is built on deviations,
--    so the entry/exit levels matter.
--
--    Nifty entry = the previous trading day's close (so the boundary-day gap move
--    is counted inside the phase it belongs to — e.g. the war-onset jump from the
--    27 Feb close into the first acute-war session).
--    Brent / USD-INR entry = the first AVAILABLE quote in the phase (these series
--    have occasional missing days, so a LAG could land on a NULL); nulls are
--    sorted last in the ROW_NUMBER so rn = 1 is always a real observation.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW regime_dynamics AS
WITH p AS (
    SELECT
        date, phase_id, phase_name, nifty_level, brent_close, usd_inr, fii_net_flow,
        LAG(nifty_level) OVER (ORDER BY date) AS prev_nifty,
        ROW_NUMBER() OVER (PARTITION BY phase_id ORDER BY date)      AS rn_first,
        ROW_NUMBER() OVER (PARTITION BY phase_id ORDER BY date DESC) AS rn_last,
        ROW_NUMBER() OVER (PARTITION BY phase_id
                           ORDER BY (brent_close IS NULL), date)      AS rn_brent_first,
        ROW_NUMBER() OVER (PARTITION BY phase_id
                           ORDER BY (brent_close IS NULL), date DESC) AS rn_brent_last,
        ROW_NUMBER() OVER (PARTITION BY phase_id
                           ORDER BY (usd_inr IS NULL), date)          AS rn_fx_first,
        ROW_NUMBER() OVER (PARTITION BY phase_id
                           ORDER BY (usd_inr IS NULL), date DESC)     AS rn_fx_last
    FROM daily_panel
),
e AS (
    SELECT
        phase_id, phase_name,
        MIN(date) AS start_date, MAX(date) AS end_date, COUNT(*) AS n_trading_days,
        MAX(CASE WHEN rn_first = 1 THEN COALESCE(prev_nifty, nifty_level) END) AS nifty_entry,
        MAX(CASE WHEN rn_last  = 1 THEN nifty_level END)                       AS nifty_exit,
        MAX(CASE WHEN rn_brent_first = 1 THEN brent_close END)                 AS brent_entry,
        MAX(CASE WHEN rn_brent_last  = 1 THEN brent_close END)                 AS brent_exit,
        MAX(CASE WHEN rn_fx_first = 1 THEN usd_inr END)                        AS usd_inr_entry,
        MAX(CASE WHEN rn_fx_last  = 1 THEN usd_inr END)                        AS usd_inr_exit,
        SUM(fii_net_flow)                                                      AS fii_total_cr
    FROM p GROUP BY phase_id, phase_name
)
SELECT
    phase_id, phase_name, start_date, end_date, n_trading_days,
    ROUND(nifty_entry, 1)   AS nifty_entry,
    ROUND(nifty_exit, 1)    AS nifty_exit,
    ROUND(100 * (nifty_exit / nifty_entry - 1), 2)       AS nifty_phase_return_pct,
    ROUND(brent_entry, 2)   AS brent_entry,
    ROUND(brent_exit, 2)    AS brent_exit,
    ROUND(100 * (brent_exit / brent_entry - 1), 2)       AS brent_phase_change_pct,
    ROUND(usd_inr_entry, 3) AS usd_inr_entry,
    ROUND(usd_inr_exit, 3)  AS usd_inr_exit,
    -- positive = rupee DEPRECIATED over the phase (more INR per USD)
    ROUND(100 * (usd_inr_exit / usd_inr_entry - 1), 2)   AS inr_depreciation_pct,
    ROUND(fii_total_cr, 0)  AS fii_total_cr
FROM e;
