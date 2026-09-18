# War Shock Stress Lab

**Quantifying how the 2026 US–Iran war and Strait of Hormuz crisis transmits into Indian financial markets — through oil prices, foreign investor flows, currency, and sector-level equity returns.**

An integrated analytics system: a SQL data warehouse, statistically rigorous event-study and regression models, a composite macro-stress index, and an interactive Power BI risk dashboard.

---

## Why this matters

In February 2026, the US–Iran war escalated into a crisis over the Strait of Hormuz — the chokepoint for roughly one-fifth of the world's seaborne crude oil and LNG. Brent crude spiked into the $90–106 range as the strait was closed, blockaded, briefly reopened, and closed again. India imports 85–90% of its crude oil, so the shock transmits directly into the rupee, bond yields, and foreign investor sentiment — and the crisis remains live: a ceasefire signed in June 2026 collapsed the following month, with renewed strikes since.

This is the kind of geopolitical-macro shock that investors, risk desks, and policymakers need to reason about in real time, not in hindsight. **The War Shock Stress Lab quantifies it directly: how much of the damage to Indian equities is explained by oil prices, versus foreign capital flight, versus currency weakness — and which sectors are genuinely resilient versus merely falling less than a collapsing market.**

---

## Analytical approach

The project isolates three distinct transmission channels and measures each with a method suited to the question:

**Absolute market impact.** An event study measures abnormal returns around ~25 curated war milestones — the war's start, the Hormuz closure declaration, ceasefires, blockade impositions, reopening flip-flops, and the eventual ceasefire collapse. Impact is decomposed into its market-wide and sector-specific components, so the analysis distinguishes genuine sector resilience from a sector simply falling less than a crashing benchmark. Abnormal returns are measured over cumulative multi-day windows to capture reactions to events that break after Indian market hours, and every result is tested for statistical significance via a permutation test suited to a small-sample, fat-tailed-returns setting — results are reported honestly, including where the data doesn't support a significant effect.

**Relative driver attribution.** A multi-factor regression isolates which of oil returns, FII net flows, or rupee movement explains the most variance in daily Nifty returns — answering directly whether the market damage is primarily an energy story, a capital-flight story, or a currency story.

**Composite macro stress.** A five-component India War Stress Index — normalized oil deviation, rupee deviation, bond yield spread, FII flow, and Nifty drawdown — tracks overall system stress across six defined war phases (pre-war, acute conflict, ceasefire, blockade, de-escalation, renewed conflict), benchmarked against the March 2020 Covid crash and the 2022 energy shock for a grounded sense of relative scale.

---

## Architecture

```
Data collection → SQL warehouse → Analysis notebooks → Advanced modeling → Interactive dashboard
```

**Data layer** — daily market data (Brent/WTI, Nifty/Sensex, sector indices, key single stocks, USD/INR) sourced via API; a fully source-linked war-events timeline built from a Wikipedia-sourced pipeline and keyword-based relevance scoring, refined to the ~25 milestones that are genuinely market-moving; FII/FPI flow data; India macro indicators (CPI, WPI, 10-year G-Sec yield, CAD).

**SQL warehouse** — a 10-table relational schema (MySQL) with materialized analytical views joining oil, equities, flows, FX, and macro data on a common daily grid, built with multi-table joins, window functions, CTEs, and phase-level aggregation.

**Analysis notebooks** — the event study, sector rotation (cumulative sector returns across six war phases), and the multi-factor oil/flows/currency regression described above.

**Advanced modeling** — the composite India War Stress Index, regime classification, and historical benchmarking.

**Dashboard** — a four-pane interactive Power BI report: Hormuz strait status and global energy overview, India macro stress index with live gauges, sector rotation with drill-down to individual stocks, and a scenario lab projecting downstream market impact under adjustable closure-duration and lost-supply assumptions.

---

## What the analysis is built to withstand

- **Mixed-frequency data (daily market data alongside monthly/quarterly macro releases) is forward-filled, not interpolated** — the analysis reflects only what was actually known to the market on a given date, never a smoothed anticipation of a future release.
- **Event severity is scored from each milestone's real-world scale and durability, independent of market reaction** — market response is then checked against the score as a validation step, not used to construct it, so the resulting "severity predicts impact" relationship is a genuine finding rather than a circular one.
- **The benchmark choice for measuring relative sector performance is deliberate** — Indian sectors are measured against the Nifty rather than a global index, because a global benchmark is itself oil-shocked and non-synchronous with Indian trading hours; the multi-factor regression handles global-driver attribution directly and more cleanly instead.
- **Scope is matched to what the data can actually support** — BRICS-wide comparative flows and a full sector-fundamentals layer are scoped to what reliable data availability allows, documented transparently rather than padded.

---

## Tech stack

Python (Pandas, NumPy, statsmodels/scipy) · SQL (MySQL) · Power BI · ACLED conflict-event API · web-sourced event timeline data

---

## What this project demonstrates

- **End-to-end data engineering** on a live, still-unfolding real-world event — sourcing, cleaning, and warehousing genuine time-series data rather than a static, pre-packaged dataset
- **Rigorous applied statistics** — event-study methodology, multi-factor regression, and permutation-based significance testing, used correctly rather than merely invoked
- **Decision-grade analytical output** — a composite stress index, regime-based comparison, and scenario modeling built to be genuinely useful to an investor or policymaker reasoning about geopolitical risk, not just descriptive charts