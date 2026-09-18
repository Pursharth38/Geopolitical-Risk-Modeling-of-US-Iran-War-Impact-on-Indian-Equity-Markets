-- War Shock Stress Lab — Milestone 2, Part A: warehouse schema (MySQL 8).
--
-- 9 data tables (per the updated Step-2 plan: policy_rate excluded from
-- macro_india; sector_fundamentals NOT built this milestone) + 1 helper
-- dimension `phases`. Each data table maps to a Step-1 raw dataset.
--
-- Note: the index return column is named `daily_return` (not `return`, which is
-- reserved in MySQL) to keep views/queries clean.

CREATE DATABASE IF NOT EXISTS war_shock_lab
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE war_shock_lab;

-- Idempotent: drop in FK-safe order (no FKs declared, but keep tidy for re-runs).
DROP TABLE IF EXISTS oil_supply_shocks;
DROP TABLE IF EXISTS macro_india;
DROP TABLE IF EXISTS fii_flows;
DROP TABLE IF EXISTS fx_rates;
DROP TABLE IF EXISTS stock_prices;
DROP TABLE IF EXISTS index_levels;
DROP TABLE IF EXISTS oil_prices;
DROP TABLE IF EXISTS hormuz_status;
DROP TABLE IF EXISTS war_events;
DROP TABLE IF EXISTS phases;

-- ---------------------------------------------------------------------------
-- Dimension: the 6 war phases (from config.PHASES). Lets daily views tag a
-- phase by a date-range join. end_date NULL = open-ended (current phase).
-- ---------------------------------------------------------------------------
CREATE TABLE phases (
  phase_id   INT          PRIMARY KEY,
  name       VARCHAR(64)  NOT NULL,
  start_date DATE         NOT NULL,
  end_date   DATE         NULL
);

-- ---------------------------------------------------------------------------
-- Market tables
-- ---------------------------------------------------------------------------
CREATE TABLE oil_prices (
  date        DATE          PRIMARY KEY,
  brent_close DECIMAL(10,4),
  wti_close   DECIMAL(10,4),
  volume      BIGINT
);

-- Long format: one row per (date, index). `level` = close, `daily_return` = pct change.
CREATE TABLE index_levels (
  date         DATE         NOT NULL,
  index_name   VARCHAR(32)  NOT NULL,
  level        DOUBLE,
  daily_return DOUBLE,
  PRIMARY KEY (date, index_name)
);

-- Long format: one row per (date, stock).
CREATE TABLE stock_prices (
  date   DATE          NOT NULL,
  symbol VARCHAR(24)   NOT NULL,
  close  DECIMAL(12,4),
  volume BIGINT,
  sector VARCHAR(32),
  PRIMARY KEY (date, symbol)
);

CREATE TABLE fx_rates (
  date          DATE          PRIMARY KEY,
  usd_inr_close DECIMAL(10,4)
);

-- FII/FPI net flows (NSDL). Daily equity is the panel series; asset_class in the
-- PK leaves room to add debt/total later without schema change.
CREATE TABLE fii_flows (
  date                DATE           NOT NULL,
  net_equity_flow_inr DECIMAL(14,2),   -- INR crore (negative = outflow)
  asset_class         VARCHAR(16)    NOT NULL DEFAULT 'equity',
  source              VARCHAR(32),
  PRIMARY KEY (date, asset_class)
);

-- Curated war events (30 milestones). event_id links back to wiki_timeline_raw.
CREATE TABLE war_events (
  event_id       VARCHAR(16)  PRIMARY KEY,
  date           DATE         NOT NULL,
  type           VARCHAR(64),          -- event category
  description    VARCHAR(512),
  severity_score INT,                  -- 1..5
  source_url     VARCHAR(512),         -- recovered from the raw scrape via event_id
  INDEX idx_war_events_date (date)
);

-- Hormuz status expanded to one row per calendar day (schema is date-keyed).
-- source_row_ids references the wiki_timeline_raw rows that define the period.
CREATE TABLE hormuz_status (
  date              DATE         PRIMARY KEY,
  status            VARCHAR(64),
  status_code       INT,                -- 0 Open .. 4 Blockade (map colour)
  lost_bpd_estimate BIGINT,             -- analyst estimate, not source-measured
  ships_stranded    INT,
  source_row_ids    VARCHAR(128)
);

-- ---------------------------------------------------------------------------
-- Supplementary tables
-- ---------------------------------------------------------------------------
-- Derived from hormuz_status lost-bpd; scenario allows future what-if rows.
CREATE TABLE oil_supply_shocks (
  date              DATE         NOT NULL,
  lost_bpd_estimate BIGINT,
  source            VARCHAR(32),
  scenario          VARCHAR(32)  NOT NULL DEFAULT 'actual',
  PRIMARY KEY (date, scenario)
);

-- Macro at NATIVE frequency (monthly CPI/WPI, sparse G-Sec, quarterly CAD).
-- Columns are sparse by design; do NOT forward-fill here — that happens only
-- when joined into india_stress_panel. One row per published observation date.
CREATE TABLE macro_india (
  date           DATE    PRIMARY KEY,
  cpi            DOUBLE,               -- CPI headline inflation YoY %
  wpi            DOUBLE,               -- WPI inflation YoY %
  gsec_10y_yield DOUBLE,               -- 10Y G-Sec yield %
  cad_estimate   DOUBLE                -- current account, USD bn (neg = deficit)
);
