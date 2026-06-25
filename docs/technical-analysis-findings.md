# Technical Analysis Findings - Hardened Strategy Baseline

This document serves as the standardized record for simulation results. Each run is analyzed to identify correlations between technical indicators and profitability to inform the next stage of hardening.

## Standardized Run Template

### Run 27: RSI Ceiling & Barrier Expansion (0.6%/0.4%)
**Duration**: 18m
**Total Trades**: 9 (Exits)
**Win Rate**: 33.3%
**Net PnL**: +0.02 USDT (Break-even)

| Metric | Side | Win Avg | Loss Avg | Delta | Win Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | 31.0 | 25.4 | +5.6 | 33% |
| **RSI** | **SELL** | 77.6 | 77.5 | +0.1 | 50% |
| **MACD** | **Overall**| 0.001 | 0.15 | - | - |
| **BTC 15m** | **Overall**| -0.024 | -0.015 | - | - |
| **DRT** | **Overall**| 0.55 | 0.61 | - | - |

**Strategic Observation**:
- **Stabilization Achieved**: Run 27 successfully broke the drawdown spiral of Run 26.
- **RSI Ceiling Success**: GRTUSDT (the prior killer) was 100% avoided despite high signals, thanks to the 80.0 RSI Ceiling.
- **Cooldown Success**: Re-entry cooldown (60s) prevented rapid-fire losses on BGB and POL.
- **Winning Assets**: WLDUSDT (100% WR, 2 trades) and POLUSDT (50% WR, 2 trades) were the top performers.
- **Problematic Assets**: AAVE and PEPE had outsized losses (-3.63 and -2.61) compared to the standard profit target (+2.8). This is likely due to slippage or gaps during high-volatility events where the Market SL failed to execute at the precise barrier.

---

## Historical Performance & Strategic Evolution

### Phase 1: High-Frequency Baseline (Completed 2026-06-24)
- **Key Insight**: Fee attrition (0.12% round-trip) vs tight barriers (0.1% SL) makes random noise fatal.
- **Engagement**: Maker-fee optimization implemented. Target barriers moved to 0.3% / 0.2%.

### Phase 2: Strategy Hardening (Active)
- **Hardened Filter: RSI Floor**: Reject Buys if RSI < 15.0 to avoid "falling knives."
- **Hardened Filter: RSI Ceiling**: Reject Shorts if RSI > 80.0 to avoid "rocket ships." (Added Run 27)
- **Hardened Filter: Re-entry Cooldown**: 60s delay to prevent churn. (Added Run 27)
- **Dynamic Optimization**: Leveraging `TARGET_NET_ROE` (5%) to calculate TP dynamically.

---

## Current Asset Performance Leaders

| Asset | Win Rate | Net PnL | Recommended Action |
| :--- | :--- | :--- | :--- |
| WLDUSDT | 100% | +5.62 | Maintain Current Logic. |
| POLUSDT | 50% | +2.05 | Monitor Spread impact on SL. |
| BGBUSDT | 0% | -1.40 | Check if RSI floor is too low for BGB. |
| AAVEUSDT | 0% | -3.63 | Investigation: High Slippage on SL? |

---

## Strategic Roadmap Progress
1. [x] **Maker-Fee Optimization**: Limit Entry/TP active.
2. [x] **RSI Buy Floor**: active at 15.0.
3. [x] **RSI Short Ceiling**: active at 80.0.
4. [x] **Re-entry Cooldown**: active at 60.0.
5. [x] **Leverage-Aware TP**: Dynamic Net ROE targeting.
6. [ ] **ATR-Based Stop Loss**: Pending verification for Run 28.
