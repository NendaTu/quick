# Technical Analysis Findings - Hardened Strategy Baseline

This document serves as the standardized record for simulation results. Each run is analyzed to identify correlations between technical indicators and profitability to inform the next stage of hardening.

## Standardized Run Template

### Run 26: Hardened Baseline Verification
**Duration**: 1m 34s
**Total Trades**: 297
**Win Rate**: 0.0%
**Net PnL**: -493.76 USDT

| Metric | Side | Win Avg | Loss Avg | Delta | Win Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | - | - | - | 0.0% |
| **RSI** | **SELL** | - | 90.5 | - | 0.0% |
| **MACD** | **Overall**| - | 0.000 | - | - |
| **BTC 15m** | **Overall**| - | -0.025 | - | - |
| **DRT** | **Overall**| - | 0.554 | - | - |

**Strategic Observation**:
- **The "High RSI Trap"**: GRTUSDT (289 trades) proved that selling into extreme momentum (RSI 90.5) is as dangerous as buying into a crash.
- **Stop Loss Churn**: The 0.2% SL was repeatedly hit as the price continued upward.
- **Dynamic Targeting**: Leverage-aware TP worked but was irrelevant as SLs were hit first.

---

## Historical Performance & Strategic Evolution

### Phase 1: High-Frequency Baseline (Completed 2026-06-24)
- **Key Insight**: Fee attrition (0.12% round-trip) vs tight barriers (0.1% SL) makes random noise fatal.
- **Engagement**: Maker-fee optimization implemented. Target barriers moved to 0.3% / 0.2%.

### Phase 2: Strategy Hardening (Active)
- **Hardened Filter: RSI Floor**: Reject Buys if RSI < 15.0 to avoid "falling knives."
- **Hardened Filter: BTC Double-Gate**: Required BTC 15m/1H trend alignment.
- **Dynamic Optimization**: Leveraging `TARGET_NET_ROE` (5%) to calculate TP dynamically based on asset leverage and fee structure.
- **Action Required: RSI Ceiling**: Implement Short RSI Ceiling (reject if RSI > 85.0) to avoid "rocket ship" shorts.
- **Action Required: Re-entry Cooldown**: Add a delay between consecutive trades on the same asset to prevent rapid-fire losses during parabolic moves.

---

## Current Asset Performance Leaders

| Asset | Win Rate | Net PnL | Recommended Action |
| :--- | :--- | :--- | :--- |
| XLMUSDT | 0% | -0.91 | Monitor liquidity. |
| CROUSDT | 0% | -61.09 | Engage RSI Ceiling. |
| PIUSDT | 0% | -61.29 | Monitor BTC Confluence. |
| GRTUSDT | 0% | -466.22 | CRITICAL: Implement RSI Ceiling and Cooldown. |

---

## Strategic Roadmap Progress
1. [x] **Maker-Fee Optimization**: Limit Entry/TP active.
2. [x] **RSI Buy Floor**: active at 15.0.
3. [x] **Leverage-Aware TP**: Dynamic Net ROE targeting.
4. [ ] **ATR-Based Stop Loss**: Pending verification in Phase 2.
5. [ ] **Short RSI Ceiling**: **PRIORITY FOR NEXT RUN.**
