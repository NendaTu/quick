# Technical Analysis Findings - Initial Baseline Run

This document summarizes the correlations between technical indicators and trade outcomes based on the 38-minute initial baseline simulation (~45 completed trades).

## Correlation Data

| Metric | Side | Winning Avg | Losing Avg | Correlation Strength |
| :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | **37.6** | 52.3 | **High**: Winning longs occurred during clearer oversold conditions. |
| **MACD** | **SELL** | **4.88** | 0.25 | **High**: Winning shorts entered on much higher momentum peaks. |
| **BTC 15m** | **Overall** | **-0.0001** | -0.0040 | **Medium**: Wins correlated with BTC stability; losses occurred during BTC drops. |
| **DRT** | **Overall** | **0.509** | 0.513 | **Low**: Trend alone (at the 0.1 threshold) did not distinguish winners. |

## Strategic Engagements

The following filters have been hardened based on the empirical evidence above:

1. **RSI Long Restriction**: **[ENGAGED]**
   - **Target**: Longs (BUYS) only.
   - **Threshold**: RSI must be < 45.0.
   - **Reasoning**: Winners showed significantly lower RSI (37.6) than losers (52.3). Restricting to < 45 eliminates "noise" entries during neutral RSI conditions.

2. **MACD Momentum (Shorts)**: [PENDING]
   - Potential engagement: Require MACD Histogram > 1.0 for Shorts.

3. **BTC Confluence**: [PENDING]
   - Potential engagement: Restrict trades if BTC 15m Trend < -0.001.

---

# Technical Analysis Update - Post RSI-Long Engagement (33-minute run)

## Observation of RSI Impact

| Metric | Side | Winning Avg | Losing Avg | Win Rate |
| :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | **32.4** | 34.1 | **33.3%** |
| **RSI** | **SELL** | **52.7** | 42.6 | **13.0%** |

### **Analysis of RSI Engagement**
- **BUYS**: Engaging `RSI < 45` improved the Buy Win Rate and tightened the entry window. Winners are now averaging an even lower RSI (32.4), suggesting further tightening to `RSI < 35` could be beneficial.
- **SELLS**: Currently unrestricted. The data shows losers are entering with a low average RSI (42.6), while winners are at **52.7**. This strongly implies that SELLS should be restricted to **RSI > 55** to avoid shorting into oversold conditions.

## BTC Confluence Evidence (Shorts)

Winning shorts in this run were perfectly correlated with positive BTC 15m and 1H momentum (+0.0007), whereas losing shorts occurred during BTC drops (-0.0024 to -0.0057). This suggests that shorting altcoins is most effective when BTC is stable or slightly rising, likely catching "laggard" drops or mean reversions.
