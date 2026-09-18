-- War Shock Stress Lab — Milestone 2, Part A: analytics queries (MySQL 8).
-- Run after schema.sql, load, and views.sql. Each query is prefixed with the
-- question it answers. Technique coverage is called out per query.

USE war_shock_lab;

-- Q1 [AGGREGATE by category] Average & total FII net flow by war phase.
--     How hard did foreigners sell in each phase of the war?
SELECT phase_id, phase_name,
       COUNT(*)                       AS trading_days,
       ROUND(AVG(fii_net_flow), 1)    AS avg_daily_fii_cr,
       ROUND(SUM(fii_net_flow), 0)    AS total_fii_cr
FROM daily_panel
GROUP BY phase_id, phase_name
ORDER BY phase_id;

-- Q2 [AGGREGATE by category] Market behaviour grouped by oil-price band.
--     Do FII selling and Nifty returns worsen as Brent rises?
SELECT CASE WHEN brent_close < 80       THEN 'a. <80'
            WHEN brent_close <= 95      THEN 'b. 80-95'
            ELSE                             'c. >95' END AS oil_band,
       COUNT(*)                          AS days,
       ROUND(AVG(brent_close), 2)        AS avg_brent,
       ROUND(AVG(fii_net_flow), 1)       AS avg_fii_cr,
       ROUND(AVG(nifty_return) * 100, 3) AS avg_nifty_ret_pct
FROM daily_panel
WHERE brent_close IS NOT NULL
GROUP BY oil_band
ORDER BY oil_band;

-- Q3 [CTE + WINDOW + 3-table JOIN] Sector-index cumulative return per phase, ranked.
--     Which sectors won/lost in each phase? (uses the 6 sector indices)
WITH phase_bounds AS (
    SELECT il.index_name, p.phase_id, p.name AS phase_name,
           MIN(il.date) AS d0, MAX(il.date) AS d1
    FROM index_levels il
    JOIN phases p ON il.date BETWEEN p.start_date
                                 AND COALESCE(p.end_date, '9999-12-31')
    WHERE il.index_name NOT IN ('nifty50', 'sensex')
    GROUP BY il.index_name, p.phase_id, p.name
)
SELECT b.phase_id, b.phase_name, b.index_name,
       ROUND((l1.level / l0.level - 1) * 100, 2)                       AS cum_return_pct,
       RANK() OVER (PARTITION BY b.phase_id ORDER BY l1.level / l0.level DESC) AS rank_in_phase
FROM phase_bounds b
JOIN index_levels l0 ON l0.index_name = b.index_name AND l0.date = b.d0
JOIN index_levels l1 ON l1.index_name = b.index_name AND l1.date = b.d1
ORDER BY b.phase_id, rank_in_phase;

-- Q4 [WINDOW function] 30-day rolling average of FII net flow across the timeline.
--     The smoothed foreign-selling trend.
SELECT date,
       ROUND(fii_net_flow, 1)                                           AS fii_cr,
       ROUND(AVG(fii_net_flow) OVER (ORDER BY date
             ROWS BETWEEN 29 PRECEDING AND CURRENT ROW), 1)             AS fii_30d_avg_cr
FROM daily_panel
ORDER BY date;

-- Q5 [multi-condition filter] Days with Brent>95 AND net FII selling: avg Nifty return.
--     When both stressors hit together, how bad was the market?
SELECT COUNT(*)                          AS stress_days,
       ROUND(AVG(nifty_return) * 100, 3) AS avg_nifty_ret_pct,
       ROUND(AVG(fii_net_flow), 1)       AS avg_fii_cr,
       ROUND(AVG(brent_close), 2)        AS avg_brent
FROM daily_panel
WHERE brent_close > 95 AND fii_net_flow < 0;

-- Q6 [CTE + 3-table JOIN] Top/bottom story-stock movers during the acute-war phase (2).
--     Which single names swung most while Hormuz was blocked?
WITH bounds AS (
    SELECT sp.symbol, sp.sector, MIN(sp.date) AS d0, MAX(sp.date) AS d1
    FROM stock_prices sp
    JOIN phases p ON p.phase_id = 2
                 AND sp.date BETWEEN p.start_date AND p.end_date
    GROUP BY sp.symbol, sp.sector
)
SELECT b.symbol, b.sector,
       ROUND((p1.close / p0.close - 1) * 100, 2) AS acute_war_return_pct
FROM bounds b
JOIN stock_prices p0 ON p0.symbol = b.symbol AND p0.date = b.d0
JOIN stock_prices p1 ON p1.symbol = b.symbol AND p1.date = b.d1
ORDER BY acute_war_return_pct DESC;

-- Q7 [3-table JOIN + AGGREGATE] Average sector-index return on high-oil days (Brent>95).
--     Which sectors move most on oil-spike days?
SELECT il.index_name,
       COUNT(*)                            AS high_oil_days,
       ROUND(AVG(il.daily_return) * 100, 3) AS avg_ret_pct
FROM index_levels il
JOIN daily_panel dp ON dp.date = il.date
WHERE dp.brent_close > 95
  AND il.index_name NOT IN ('nifty50', 'sensex')
GROUP BY il.index_name
ORDER BY avg_ret_pct;

-- Q8 [CTE aggregate then join back to detail] Each war event vs its phase's avg Nifty return.
--     Contextualises every milestone against how the market did in that phase.
WITH phase_avg AS (
    SELECT phase_id, AVG(nifty_return) AS avg_ret
    FROM daily_panel
    GROUP BY phase_id
)
SELECT w.event_id, w.date, w.severity_score, LEFT(w.description, 60) AS event,
       p.phase_id, p.name AS phase_name,
       ROUND(pa.avg_ret * 100, 3) AS phase_avg_nifty_ret_pct
FROM war_events w
JOIN phases p ON w.date BETWEEN p.start_date AND COALESCE(p.end_date, '9999-12-31')
JOIN phase_avg pa ON pa.phase_id = p.phase_id
ORDER BY w.date;
