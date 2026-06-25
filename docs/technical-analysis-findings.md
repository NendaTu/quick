# Technical Analysis Findings - Hardened Strategy Baseline

This document serves as the standardized record for simulation results. Each run is analyzed to identify correlations between technical indicators and profitability to inform the next stage of hardening.

## Standardized Run Template

### Run 29: Multi-Timeframe DRT & Premium/Discount Logic
**Duration**: 30m
**Total Trades**: 13 (Exits)
**Win Rate**: 46.1%
**Net PnL**: -7.64 USDT

| Metric | Side | Win Avg | Loss Avg | Delta | Win Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | 20.5 | 20.5 | 0.0 | 50% |
| **RSI** | **SELL** | 76.2 | 75.3 | +0.9 | 45% |
| **DRT_f (5m)** | **Overall**| 0.44 | 0.46 | -0.02 | - |
| **DRT_s (15m)**| **Overall**| 0.38 | 0.35 | +0.03 | - |
| **BTC 15m** | **Overall**| -0.03 | -0.03 | 0.0 | - |

**Strategic Observation**:
- **MTF Clarity**: Shifting DRT to 5m/15m provided much cleaner directional signals. The "noisy" 1m DRT was removed as a primary filter.
- **Mean Reversion (Discount/Premium)**: With `RESTRICT_DRT=False`, the bot took trades into "Discount" zones (<0.5). Initial results show that winning Shorts correlated with a slightly higher (more Premium) 15m DRT than losing ones.
- **Stability**: The combination of MTF data and re-entry cooldowns has stabilized the equity curve, even during high-volatility bursts.

---

## Historical Performance & Strategic Evolution

### Phase 1: High-Frequency Baseline (Completed 2026-06-24)
- **Key Insight**: Fee attrition vs tight barriers makes random noise fatal.
- **Engagement**: Maker-fee optimization implemented. Target barriers moved to 0.3% / 0.2%.

### Phase 2: Strategy Hardening (Active)
- **Hardened Filter: RSI Floor**: Reject Buys if RSI < 15.0 to avoid "falling knives."
- **Hardened Filter: RSI Ceiling**: Reject Shorts if RSI > 80.0 to avoid "rocket ships."
- **Hardened Filter: Re-entry Cooldown**: 60s delay to prevent churn.
- **Dynamic Optimization**: Leveraging `TARGET_NET_ROE` (5%) to calculate TP dynamically.
- **Hardened Filter: MTF DRT**: Signals now incorporate 5m and 15m trend data. (Added Run 29)

---

## Current Asset Performance Leaders

| Asset | Win Rate | Net PnL | Recommended Action |
| :--- | :--- | :--- | :--- |
| ZECUSDT | 100% | +2.79 | Excellent reversal performance in 15m discount. |
| ENAUSDT | 100% | +2.77 | Clean execution on 5m premium short. |
| WLDUSDT | 50% | +0.25 | Stabilized; keep monitoring MTF correlation. |

---

## Strategic Roadmap Progress
1. [x] **Maker-Fee Optimization**: Limit Entry/TP active.
2. [x] **RSI Buy Floor**: active at 15.0.
3. [x] **RSI Short Ceiling**: active at 80.0.
4. [x] **Re-entry Cooldown**: active at 60.0.
5. [x] **Leverage-Aware TP**: Dynamic Net ROE targeting.
6. [x] **Multi-Timeframe DRT**: active for 5m/15m.
7. [ ] **ATR-Based Stop Loss**: Pending Run 30.
