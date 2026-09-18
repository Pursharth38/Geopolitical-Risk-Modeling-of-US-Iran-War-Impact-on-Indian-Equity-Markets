-- War Shock Stress Lab — Milestone 3, Component 2: the India War Stress Index.
--
-- One composite daily number for macro-financial stress, built from FOUR channels:
--     oil  ·  rupee  ·  foreign flows  ·  equity drawdown
--
-- WHY FOUR AND NOT FIVE (the milestone plan names five):
-- the fifth component, the 10Y G-Sec yield spread, is NOT built. The yield series
-- has 3 published values in total (earliest 2026-05-31), so the pre-war window
-- (phase 1) contains ZERO observations and no reference mean/sd exists to z-score
-- against. A targeted source spike on 2026-08-01 confirmed no daily history is
-- obtainable here: Yahoo has no India 10Y ticker, stooq has no bond symbols, FRED
-- times out, investing.com 403s, MarketWatch 401s, worldgovernmentbonds is a JS
-- shell; CCIL and RBI both publish the figure but expose only a current snapshot
-- and a rolling 5-week window respectively. The rates channel is therefore
-- documented as unavailable at daily frequency rather than proxied or filled.
--
-- METHOD
--   1. Reference distribution = PHASE 1 ONLY (2026-01-01 -> 2026-02-27, the pre-war
--      baseline). Each channel's mean and standard deviation are computed once from
--      that window and never re-fit. This is what makes the index a measure of
--      deviation from "normal" rather than from its own history.
--   2. Every channel is z-scored: z = (value - prewar_mean) / prewar_sd, i.e. "how
--      many typical pre-war moves away from normal is today".
--   3. SIGNS are oriented so that HIGHER ALWAYS MEANS MORE STRESS:
--        oil     +z   (dearer crude = stress)
--        rupee   +z   (more INR per USD = weaker rupee = stress)
--        flows   -z   (NEGATIVE flow is stress, so the z-score is inverted)
--        equity  +z   (larger drawdown below the pre-war peak = stress)
--   4. Equal weighting, combined as a MEAN of the available z-scores. Equal weights
--      are the defensible default per the plan — no reason to privilege a channel
--      a priori, and any unequal scheme would need justification the data has not
--      yet supplied. The mean (rather than the sum) keeps the index in interpretable
--      units: 0 = pre-war normal, +2 = two pre-war standard deviations of stress,
--      and it degrades gracefully on days when a channel is missing.
--
-- NOT CIRCULAR: the formula is defined entirely from these four inputs. War events
-- and severity scores are used ONLY to sanity-check the finished index in the
-- notebook; no weight, sign or threshold is tuned to make events line up.

USE war_shock_lab;

-- ---------------------------------------------------------------------------
-- 1. stress_baseline — the pre-war reference distribution. ONE row.
--    Everything downstream is measured against these numbers.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW stress_baseline AS
SELECT
    (SELECT MAX(nifty_level) FROM daily_panel WHERE phase_id = 1) AS prewar_peak,
    COUNT(*)                                    AS baseline_days,
    AVG(brent_close)                            AS brent_mu,
    STDDEV_SAMP(brent_close)                    AS brent_sd,
    AVG(usd_inr)                                AS fx_mu,
    STDDEV_SAMP(usd_inr)                        AS fx_sd,
    AVG(fii_net_flow)                           AS fii_mu,
    STDDEV_SAMP(fii_net_flow)                   AS fii_sd,
    -- drawdown below the pre-war peak, in %, over the baseline window itself
    AVG(100 * ((SELECT MAX(nifty_level) FROM daily_panel WHERE phase_id = 1) - nifty_level)
        / (SELECT MAX(nifty_level) FROM daily_panel WHERE phase_id = 1))         AS dd_mu,
    STDDEV_SAMP(100 * ((SELECT MAX(nifty_level) FROM daily_panel WHERE phase_id = 1) - nifty_level)
        / (SELECT MAX(nifty_level) FROM daily_panel WHERE phase_id = 1))         AS dd_sd
FROM daily_panel
WHERE phase_id = 1;

-- ---------------------------------------------------------------------------
-- 2. stress_components — the four sign-oriented z-scores, per trading day.
--    Kept as its own view so the composite can be audited channel by channel:
--    any index reading can be decomposed into which channel produced it.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW stress_components AS
SELECT
    d.date,
    d.phase_id,
    d.phase_name,
    d.brent_close,
    d.usd_inr,
    d.fii_net_flow,
    d.nifty_level,
    ROUND(100 * (b.prewar_peak - d.nifty_level) / b.prewar_peak, 4) AS nifty_drawdown_pct,
    -- higher = more stress, in pre-war standard deviations
    (d.brent_close - b.brent_mu) / b.brent_sd                       AS z_oil,
    (d.usd_inr    - b.fx_mu)    / b.fx_sd                           AS z_inr,
    -((d.fii_net_flow - b.fii_mu) / b.fii_sd)                       AS z_fii,
    ((100 * (b.prewar_peak - d.nifty_level) / b.prewar_peak) - b.dd_mu) / b.dd_sd AS z_equity
FROM daily_panel d
CROSS JOIN stress_baseline b;

-- ---------------------------------------------------------------------------
-- 3. india_stress_index — the headline composite.
--    n_components exposes how many channels were actually available that day, so
--    a reading built on 3 of 4 is never silently presented as a full one.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW india_stress_index AS
SELECT
    date,
    phase_id,
    phase_name,
    ROUND(z_oil, 4)    AS z_oil,
    ROUND(z_inr, 4)    AS z_inr,
    ROUND(z_fii, 4)    AS z_fii,
    ROUND(z_equity, 4) AS z_equity,
    (z_oil IS NOT NULL) + (z_inr IS NOT NULL)
      + (z_fii IS NOT NULL) + (z_equity IS NOT NULL)              AS n_components,
    ROUND(
      (COALESCE(z_oil, 0) + COALESCE(z_inr, 0)
       + COALESCE(z_fii, 0) + COALESCE(z_equity, 0))
      / NULLIF((z_oil IS NOT NULL) + (z_inr IS NOT NULL)
               + (z_fii IS NOT NULL) + (z_equity IS NOT NULL), 0)
    , 4)                                                          AS stress_index,
    nifty_drawdown_pct
FROM stress_components;
