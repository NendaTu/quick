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
