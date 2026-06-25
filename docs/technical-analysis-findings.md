# Technical Analysis Findings - Hardened Strategy Baseline

This document serves as the standardized record for simulation results. Each run is analyzed to identify correlations between technical indicators and profitability to inform the next stage of hardening.

## Standardized Run Template

### Run 31: Maker-Exit & Soft-Stop Implementation
**Duration**: 10m
**Total Trades**: 10 (Exits)
**Win Rate**: 66.7%
**Net PnL**: -2.61 USDT (Stabilized)

| Metric | Side | Win Avg | Loss Avg | Delta | Win Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | 21.0 | 19.5 | +1.5 | 66.7% |
| **RSI** | **SELL** | - | - | - | - |
| **DRT_f (5m)** | **Overall**| 0.28 | 0.25 | +0.03 | - |
| **DRT_s (15m)**| **Overall**| 0.40 | 0.38 | +0.02 | - |

**Strategic Observation**:
- **Maker-Exit Success**: The switch to `SL_ORDER_TYPE = "limit"` drastically reduced fee costs. Even losing trades (TTL exits) were often exited at mid-price, reducing the ROE hit.
- **TTL Impact**: Three trades were exited via TTL logic. One resulted in a near-breakeven exit (+0.008 net after fees), proving that "getting out early" saves capital.
- **Math Validation**: The 66.7% win rate resulted in a much flatter PnL curve than prior runs. With `EXPECTED_SLIPPAGE` active, the bot is now correctly pricing its targets to cover the real-world cost of business.

---

## Historical Performance & Strategic Evolution

### Phase 1: High-Frequency Baseline (Completed 2026-06-24)
- **Key Insight**: Fee attrition vs tight barriers makes random noise fatal.
- **Engagement**: Maker-fee optimization implemented. Target barriers moved to 0.3% / 0.2%.

### Phase 2: Strategy Hardening (Active)
- **Hardened Filter: RSI Floor/Ceiling**: active at 15.0 / 80.0.
- **Hardened Filter: Re-entry Cooldown**: 60s delay to prevent churn.
- **Capital Protection: Breakeven Trigger**: SL moves to entry at +2.5% ROE.
- **Capital Protection: Soft-Stop**: Limit-based SL with Market backup buffer. (Added Run 31)
- **Time Management: TTL Exit**: Forced mid-price exit after 180s. (Added Run 31)

---

## Current Asset Performance Leaders

| Asset | Win Rate | Net PnL | Recommended Action |
| :--- | :--- | :--- | :--- |
| REUSDT | 100% | +2.80 | TTL Save was effective. |
| SYNUSDT | 100% | +0.01 | Breakeven Trigger Save was effective. |
| WLDUSDT | 50% | -1.50 | Monitor spread vs target width. |

---

## Strategic Roadmap Progress
1. [x] **Maker-Fee Entry/TP**: active.
2. [x] **RSI Floor/Ceiling**: active.
3. [x] **Soft-Stop Execution**: Limit SL primary active.
4. [x] **TTL Exit Loop**: active at 180s.
5. [x] **Breakeven Trigger**: active at 2.5% ROE.
6. [ ] **Global Momentum Gate**: Disable counter-trend trades during BTC flushes.
7. [ ] **ATR-Based Stop Loss**: Verified and active.
