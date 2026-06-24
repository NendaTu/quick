# Trading Configuration Legend (Baseline Relaxation)

This document journals the variables that have been relaxed to establish a maximum activity baseline for the trading simulation.

## Global Configuration (`config.py`)

| Variable | Description | Action Taken | Expected Outcome |
| :--- | :--- | :--- | :--- |
| `MIN_IMBALANCE` | The minimum required percentage difference between bid and ask volume at the top of the book. | Lowered from **0.05** to **0.01**. | Significantly increases the number of symbols passing the initial filter, as small imbalances are very common. |
| `MIN_CONFIDENCE` | A threshold for the signal's confidence score (purely for filtering in some logic). | Lowered from **0.66** to **0.1**. | Allows virtually any signal with a positive confidence to pass through. |
| `TREND_STRENGTH_MIN` | Minimum Directional Trend (DRT) required to consider a move strong enough. | Lowered from **0.3** to **0.1**. | Accepts even very weak or flat trends as tradable. |

## Model Scoring (`models.py`)

| Logic Component | Description | Action Taken | Expected Outcome |
| :--- | :--- | :--- | :--- |
| **Required Score** | The cumulative score from indicators required to trigger a signal. | Lowered from **2** to **1**. | A single positive indicator (e.g., RSI < 45) is now enough to trigger a trade, regardless of other metrics. |
| **Imbalance Scoring** | Points awarded based on order book imbalance levels. | Thresholds lowered to **0.01** (1 pt) and **0.10** (2 pts). | Makes the bot much more sensitive to even minor order book pressure. |
| **RSI Scoring** | Points awarded based on Relative Strength Index. | Thresholds loosened to **< 45** (Long) and **> 55** (Short). | Increases the frequency of RSI-based triggers by accepting less extreme overbought/oversold conditions. |
| **Asset 15m Trend** | Points awarded based on the price change over the last 15 minutes. | Threshold lowered from **0.001** (0.1%) to **0.0001** (0.01%). | Nearly any detectable movement on the 15m timeframe now contributes to the trade score. |
| **Safety Alignment** | A check that prevents buying if imbalance is negative (and vice versa). | **Removed**. | Allows the bot to trade on indicator strength even if the order book is momentarily showing counter-pressure. |

## Engine Constraints (`engine.py`)

| Variable | Description | Action Taken | Expected Outcome |
| :--- | :--- | :--- | :--- |
| **Tradability Volume** | Minimum volume required at the best bid/ask to consider an asset liquid enough. | Lowered from **10** to **1**. | Ensures that even during low-liquidity moments or for smaller assets, the bot will still attempt to place trades. |

## Miscellaneous

| Variable | Description |
| :--- | :--- |
| `LOG_REJECTIONS` | Boolean to enable/disable rejection notices (like High Slippage) in the console output. |

---

*Note: These settings are intended for establishing a baseline and will result in high-frequency trading with potentially higher slippage and lower win rates. Use for data collection and initial simulation only.*
