# Technical Analysis Findings - Hardened Strategy Baseline

This document serves as the standardized record for simulation results. Each run is analyzed to identify correlations between technical indicators and profitability to inform the next stage of hardening.

## Standardized Run Template

### Run [ID]: [Description]
**Duration**: [Time]
**Total Trades**: [Count]
**Win Rate**: [Total Win %]
**Net PnL**: [USDT]

| Metric | Side | Win Avg | Loss Avg | Delta | Win Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | - | - | - | % |
| **RSI** | **SELL** | - | - | - | % |
| **MACD** | **Overall**| - | - | - | - |
| **BTC 15m** | **Overall**| - | - | - | - |
| **DRT** | **Overall**| - | - | - | - |

**Strategic Observation**:
- [Insight 1]
- [Insight 2]

---

## Historical Performance & Strategic Evolution

### Phase 1: High-Frequency Baseline (Completed 2026-06-24)
- **Key Insight**: Fee attrition (0.12% round-trip) vs tight barriers (0.1% SL) makes random noise fatal.
- **Engagement**: Maker-fee optimization implemented. Target barriers moved to 0.3% / 0.2%.

### Phase 2: Strategy Hardening (Active)
- **Hardened Filter: RSI Floor**: Reject Buys if RSI < 15.0 to avoid "falling knives."
- **Hardened Filter: BTC Double-Gate**: Required BTC 15m/1H trend alignment.
- **Dynamic Optimization**: Leveraging `TARGET_NET_ROE` (5%) to calculate TP dynamically based on asset leverage and fee structure.

---

## Current Asset Performance Leaders
*Updated after each run to identify high-liquidity winners.*

| Asset | Win Rate | Net PnL | Recommended Action |
| :--- | :--- | :--- | :--- |
| - | - | - | - |

---

## Strategic Roadmap Progress
1. [x] **Maker-Fee Optimization**: Limit Entry/TP active.
2. [x] **RSI Buy Floor**: active at 15.0.
3. [x] **Leverage-Aware TP**: Dynamic Net ROE targeting.
4. [ ] **ATR-Based Stop Loss**: Pending verification in Phase 2.
5. [ ] **Short RSI Ceiling**: Pending analysis of "Rocket Ship" losses.
