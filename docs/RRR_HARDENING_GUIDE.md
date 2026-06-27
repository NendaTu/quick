# RRR Hardening & Configuration Guide

This document outlines critical configuration pitfalls and the mathematical safeguards implemented to secure the 1:2 Net Risk-Reward Ratio (RRR).

## 1. The Breakeven Trap
**The Pitfall**: Setting `BREAKEVEN_ROI_THRESHOLD` equal to or near `BREAKEVEN_PROFIT_BUFFER`.
- **Effect**: As soon as the trade hits the trigger ROI, the Stop Loss is moved to a price that already includes the buffer and fees. Since the market is already at that price, the trade exits **instantly**.
- **The Loss**: While logged as a "Win," these trades net negligible profit (~0.03 USDT). A single full loss (~0.75 USDT) requires **25+ consecutive BE wins** just to stay level.
- **The Safe Setup**:
    - `BREAKEVEN_ROI_THRESHOLD = 0.20` (20% ROI)
    - `BREAKEVEN_PROFIT_BUFFER = 0.05` (5% ROI)
    - *Result*: Provides a ~0.75% price "cushion" between the trigger and the new stop.

## 2. Noise-Floor Compression
**The Pitfall**: Setting `TARGET_NET_ROE` too low (e.g., 5%) on high leverage (20x+).
- **Effect**: To maintain the 1:2 RRR, the system calculates the Stop Loss move. A 5% target move (~0.35% price) forces a Stop Loss move of **~0.15%**.
- **The Risk**: 0.15% is standard market noise on a 5-minute timeframe. The bot will be "shaken out" of every trade before it has room to trend.
- **The Safe Setup**:
    - `TARGET_NET_ROE = 0.20` (20% ROI)
    - *Result*: Forces a Stop Loss of ~0.50% - 0.60%, allowing the trade to survive minor volatility.

## 3. Limit Timeout Slippage
**The Pitfall**: Relying on `LIMIT_CHASE_TIMEOUT` without slippage enforcement.
- **Effect**: If a limit entry doesn't fill in 10s, the simulator performs a Market fill. If the price spiked during those 10s, you buy at a massive disadvantage.
- **The Risk**: Since the `stop_price` was fixed at entry, this slippage widens the distance to the stop, ballooning your realized loss beyond the risk budget.
- **The Safeguard**: The system now checks `MAX_ENTRY_SLIPPAGE` during timeout fills. If the price has run away, the entry is **cancelled**.

## 4. Bi-Directional RRR Synchronization
The system in `models.py` uses a master synchronization formula:
1. It calculates the **total cost of a stop** (Distance + Entry Fee + Exit Fee + Slippage).
2. It sets the **Take Profit** to exactly 2x that total cost.
3. **If TP is capped** (e.g. by ATR or Config), it **re-calculates the SL backwards** to ensure the 1:2 ratio is never compromised.

**Golden Rule**: The system prioritizes the 1:2 ratio over reaching a specific price target. If the market doesn't allow for a safe RRR, the trade targets will contract until it's mathematically sound or rejected.

## 5. HTF Bias Alignment
**The Pitfall**: Trading against the Higher Timeframe (4H/1D) trend.
- **Effect**: Counter-trend trades have a significantly higher failure rate as they often fight against macro momentum.
- **The Safeguard**: `RESTRICT_HTF_BIAS = True` enforces that Longs are only taken in Bullish HTF environments, and Shorts in Bearish ones.
- **Neutral Handling**: By default, a 'neutral' bias allows trades in both directions (configurable via `NEUTRAL_ALLOWS_TRADES` in `ta/patterns/trend.py`).

## 6. Multi-Stage Exit Logic (BE+TP1+TP2)
- **TP1**: Positioned at a buffered distance between the Breakeven price and the final target.
- **SL Move @ TP1**: The remaining position's Stop Loss is moved to a level halfway between the Breakeven price and the TP1 price. This locks in a net profit for the entire trade even if the second half is stopped out.
- **Reporting**: Win rate in simulation stats reflects the "Exit Success Rate." Each partial or full exit counts as a trade completion to maintain mathematical consistency in the Win/Loss ratio.
