# Technical Analysis Findings - Hardened Strategy Baseline

This document serves as the standardized record for simulation results. Each run is analyzed to identify correlations between technical indicators and profitability to inform the next stage of hardening.

## Standardized Run Template

### Run 30: Adaptive RSI & Capital Protection (Breakeven Trigger)
**Duration**: 25m
**Total Trades**: 18 (Exits)
**Win Rate**: 0.0% (Realized Wins), 72% (Breakeven Saves)
**Net PnL**: -37.85 USDT

| Metric | Side | Win Avg | Loss Avg | Delta | Win Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | - | 24.6 | - | 0.0% |
| **RSI** | **SELL** | - | 77.2 | - | 0.0% |
| **DRT_f (5m)** | **Overall**| - | 0.48 | - | - |
| **DRT_s (15m)**| **Overall**| - | 0.36 | - | - |
| **BTC 15m** | **Overall**| - | -0.05 | - | - |

**Strategic Observation**:
- **Breakeven Success**: 13 out of 18 trades hit the Breakeven Trigger. Instead of full -20% ROE losses, these trades exited at roughly -1% to -2% ROE (covering fees), drastically slowing the drawdown speed.
- **Adaptive RSI**: Correctly narrowed the entry window, preventing the bot from entering "neutral high/low" noise.
- **Market Resistance**: The 0% win rate was due to a sustained market-wide flush (BTC -5%) where reversals (Longs) failed to reach the full 5% target before the pulse died.
- **Recommendation**: During extreme BTC momentum (e.g. 15m < -0.001), the bot should strictly disable the opposite side (Longs) to avoid "catching knives" even with RSI protection.

---

## Historical Performance & Strategic Evolution

### Phase 1: High-Frequency Baseline (Completed 2026-06-24)
- **Key Insight**: Fee attrition vs tight barriers makes random noise fatal.
- **Engagement**: Maker-fee optimization implemented. Target barriers moved to 0.3% / 0.2%.

### Phase 2: Strategy Hardening (Active)
- **Hardened Filter: RSI Floor/Ceiling**: active at 15.0 / 80.0.
- **Hardened Filter: Re-entry Cooldown**: 60s delay to prevent churn.
- **Hardened Filter: MTF DRT**: Signals now incorporate 5m and 15m trend data.
- **Capital Protection: Breakeven Trigger**: SL moves to entry at +2.5% ROE. (Added Run 30)
- **Adaptive RSI**: Filters tighten to 25/75 in low-momentum zones. (Added Run 30)

---

## Current Asset Performance Leaders

| Asset | Win Rate | Net PnL | Recommended Action |
| :--- | :--- | :--- | :--- |
| WLDUSDT | 0% | -0.48 | Multiple Breakeven Saves; logic is sound. |
| ZECUSDT | 0% | -0.92 | Breakeven save successful. |
| NEARUSDT | 0% | -5.71 | High slippage on SL; check beta/liquidity. |

---

## Strategic Roadmap Progress
1. [x] **Maker-Fee Optimization**: Limit Entry/TP active.
2. [x] **RSI Buy Floor**: active at 15.0.
3. [x] **RSI Short Ceiling**: active at 80.0.
4. [x] **Re-entry Cooldown**: active at 60.0.
5. [x] **Leverage-Aware TP**: Dynamic Net ROE targeting.
6. [x] **Multi-Timeframe DRT**: active for 5m/15m.
7. [x] **Breakeven Trigger**: active at 2.5% ROE.
8. [ ] **Global Momentum Gate**: Disable counter-trend trades during BTC flushes.
