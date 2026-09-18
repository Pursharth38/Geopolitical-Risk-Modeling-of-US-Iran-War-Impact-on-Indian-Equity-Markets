-- War Shock Stress Lab — Milestone 2, Part A: analytical views (MySQL 8).
-- Run after schema.sql + load. Demonstrates multi-table joins, window functions,
-- correlated (as-of) subqueries, and date-range phase tagging.

USE war_shock_lab;

-- ---------------------------------------------------------------------------
-- daily_panel — the core per-trading-day table. NO macro (per Step-2 design).
-- Base grid = Nifty trading days; everything else LEFT JOINed on date.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW daily_panel AS
SELECT
    n.date,
    p.phase_id,
    p.name                       AS phase_name,
    o.brent_close,
    o.wti_close,
    n.level                      AS nifty_level,
    n.daily_return               AS nifty_return,
    s.level                      AS sensex_level,
    s.daily_return               AS sensex_return,
    f.net_equity_flow_inr        AS fii_net_flow,
    x.usd_inr_close              AS usd_inr,
    -- nearest war event severity within +/- 1 day (most severe if several)
    (SELECT MAX(w.severity_score) FROM war_events w
      WHERE w.date BETWEEN n.date - INTERVAL 1 DAY AND n.date + INTERVAL 1 DAY
    )                            AS event_severity
FROM index_levels n
LEFT JOIN index_levels s
       ON s.date = n.date AND s.index_name = 'sensex'
LEFT JOIN oil_prices o ON o.date = n.date
LEFT JOIN fii_flows  f ON f.date = n.date AND f.asset_class = 'equity'
LEFT JOIN fx_rates   x ON x.date = n.date
LEFT JOIN phases     p ON n.date BETWEEN p.start_date
                                     AND COALESCE(p.end_date, '9999-12-31')
WHERE n.index_name = 'nifty50';

-- ---------------------------------------------------------------------------
-- india_stress_panel — extends daily_panel with macro (forward-filled from
-- native frequency via as-of subqueries), oil-supply shocks, and rolling
-- window calcs. Forward-fill = the last published value on/before each day.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW india_stress_panel AS
SELECT
    dp.*,
    (SELECT m.cpi FROM macro_india m
       WHERE m.cpi IS NOT NULL AND m.date <= dp.date
       ORDER BY m.date DESC LIMIT 1)                        AS cpi,
    (SELECT m.wpi FROM macro_india m
       WHERE m.wpi IS NOT NULL AND m.date <= dp.date
       ORDER BY m.date DESC LIMIT 1)                        AS wpi,
    (SELECT m.gsec_10y_yield FROM macro_india m
       WHERE m.gsec_10y_yield IS NOT NULL AND m.date <= dp.date
       ORDER BY m.date DESC LIMIT 1)                        AS gsec_10y_yield,
    (SELECT m.cad_estimate FROM macro_india m
       WHERE m.cad_estimate IS NOT NULL AND m.date <= dp.date
       ORDER BY m.date DESC LIMIT 1)                        AS cad_estimate,
    oss.lost_bpd_estimate,
    -- 30-day rolling average FII flow and rolling Nifty-return volatility
    AVG(dp.fii_net_flow)      OVER w                        AS fii_flow_30d_avg,
    STDDEV_SAMP(dp.nifty_return) OVER w                     AS nifty_vol_30d
FROM daily_panel dp
LEFT JOIN oil_supply_shocks oss
       ON oss.date = dp.date AND oss.scenario = 'actual'
WINDOW w AS (ORDER BY dp.date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW);
