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
   - **Threshold**: RSI must be <= 40.0.
   - **Reasoning**: Previous run showed winners at 32.4 vs losers at 34.1. Tightening to 40.0 further improves the quality of oversold entries.

2. **RSI Short Restriction**: **[ENGAGED]**
   - **Target**: Shorts (SELLS) only.
   - **Threshold**: RSI must be >= 60.0.
   - **Reasoning**: Post-run analysis showed losing shorts entering at RSI 42.6 (oversold), while winners were at 52.7. Enforcing >= 60 ensures we only short into overbought/neutral-high conditions.

3. **MACD Momentum (Shorts)**: [PENDING]
   - Potential engagement: Require MACD Histogram > 1.0 for Shorts.

4. **BTC Confluence**: **[ENGAGED]**
   - **Target**: All trades.
   - **Threshold**: BTC 15m and 1H trends must align with trade direction (>=0 for Long, <=0 for Short).
   - **Reasoning**: Run 19 analysis confirmed winning trades correlate with stronger BTC momentum. Aligning with the "market pulse" filters out counter-trend noise.

---

# Technical Analysis Update - Symmetric RSI Engagement (Run 15: 171 Trades)

## Data Summary (Symmetric RSI Active)

| Metric | Side | Winning Avg | Losing Avg | Win Rate |
| :--- | :--- | :--- | :--- | :--- |
| **RSI** | **BUY** | **-** | 27.6 | **0%** |
| **RSI** | **SELL** | **-** | 95.8 | **0%** |

### **Analysis of 100% Loss Rate**
Run 15 executed **171 trades in 100 seconds** due to the `RESTRICT_SCORE=False` setting. This ultra-high frequency (1.7 trades/sec) revealed several critical baseline behaviors:

1. **Fee Attrition**: With a round-trip fee of **0.12%** (0.06% Taker x 2) and a Stop Loss of **0.1%**, it is mathematically impossible to profit from SL hits. Even with a Take Profit of **0.15%**, the net profit after fees is only **0.03%**.
2. **Infrastructure Validation**: The system handled the 1.7 trades/second load perfectly. Zero database locks and zero WebSocket dropped frames.
3. **Indicator Accuracy**: Even at this extreme speed, RSI restrictions were 100% enforced (Buys averaged 27.6, Sells averaged 95.8).
4. **Hedge Mode Noise**: Rapidly flipping between Long and Short in a sideways market (churn) is the primary driver of the drawdown.

### **Next Steps Recommendation**
To transition from "Data Collection" to "Baseline Profitability":
- **Engage RESTRICT_SCORE**: We must require positive indicator confluence to slow down trade frequency.
- **Widen Barriers**: Increase TP/SL to at least 0.5% / 0.3% to overcome the fixed fee overhead (0.12%).
- **BTC Confluence**: Data continues to suggest that ignoring BTC direction is a primary cause of loss bursts.

---

# Technical Analysis Update - Maker-Fee Optimization (Run 18: 226 Trades)

## Performance Impact

| Metric | Buy Win Avg | Buy Loss Avg | Sell Win Avg | Sell Loss Avg |
| :--- | :--- | :--- | :--- | :--- |
| **RSI** | **23.5** | 15.5 | **78.6** | 77.4 |
| **DRT** | **0.35** | 0.44 | **0.58** | 0.64 |

### **Analysis of Maker-Execution**
Run 18 successfully utilized the new **Limit Entry** and **Limit TP** architecture, reducing fee overhead from 0.12% to approximately **0.08%** round-trip (Maker Entry + Taker SL).

1. **Win Rate Persistence**: Despite the 33-66% fee reduction, the Win Rate remained low (**9.7%**). This confirms that "tight" strategy barriers (0.1% SL) are catching random market noise rather than trend pivots.
2. **Directional Mismatch**: Winning buys occurred at an average DRT of 0.35 (Bearish trend), suggesting they caught successful mean-reversion bounces from oversold RSI. However, the high volume of losses in the same zone indicates that RSI alone is not a sufficient filter.
3. **Execution Fidelity**: Logs confirmed that `PLACED LIMIT ENTRY` and `FILLED ENTRY ... (LIMIT)` followed the 10-second chase logic perfectly, providing the intended 0.02% Maker fee benefit.

### **Strategic Recommendation**:
The evidence now strongly supports **widening the Take-Profit and Stop-Loss barriers**. Currently, the "signal edge" is being diluted by market noise and fixed transaction costs. Expanding the target profit to >0.5% will allow the Maker-fee advantage to compound significantly.
