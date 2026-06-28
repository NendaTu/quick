# Strategy Recommendations & Updates (Run 30)

This document outlines the architectural and strategic hardening implemented for Run 30, based on the empirical analysis of Run 29.

## 1. Adaptive RSI Entry Windows
**Problem**: Baseline RSI triggers (40/60) often enter during indecisive sideways movement, leading to "noise churn."
**Solution**:
- **Baseline**: Tighten filters to `RSI < 25` (Long) and `RSI > 75` (Short).
- **Dynamic Relaxation**: Relax filters back to 40/60 **only if** the Multi-Timeframe DRT (5m/15m) shows extreme momentum (>0.60 or <0.40) in the trade direction.
- **Config**: `USE_ADAPTIVE_RSI`, `RSI_TIGHT_LONG`, `RSI_TIGHT_SHORT`.

## 2. ATR-Dynamic Target Calibration
**Problem**: Fixed percentage barriers (0.6% / 0.4%) do not account for asset-specific volatility, causing slippage on high-beta assets (AAVE, PEPE) and unreachable targets on stable ones.
**Solution**:
- **Volatility SL**: Set Stop Loss to `1.5x ATR`. This allows the trade to survive normal noise while maintaining the `RISK_PER_TRADE` capital allocation.
- **Capped TP**: Dynamically calculate TP to hit 5% Net ROE, but **cap** the price move at the 15m ATR value. This ensures the target is mathematically achievable within the current market regime.
- **Config**: `USE_ATR_SL`, `USE_ATR_CAPPED_TP`.

## 3. Breakeven Trigger (Capital Protection)
**Problem**: "Near-Wins" (trades that move +4% ROE then reverse) turn into full -20% ROE losses.
**Solution**:
- **Logic**: Once a trade reaches `+2.5% Net ROE` (defined by `BREAKEVEN_ROI_THRESHOLD`), the Stop Loss is automatically moved to the `Entry Price + small fee buffer`.
- **Config**: `USE_BREAKEVEN_TRIGGER`, `BREAKEVEN_ROI_THRESHOLD`.

## 4. DRT Velocity (Second Derivative)
**Problem**: Entering a "Discount" trade while the pulse is still accelerating against us (e.g., buying a falling knife).
**Solution**:
- **Logic**: For a Long entry, require `drt_1m > drt_5m`. This ensures the micro-trend is turning upward or accelerating even if the absolute DRT value is still in a "discount" zone (<0.5).
- **Config**: `USE_DRT_VELOCITY`.

---

**Status**: These features are togglable in `config.py` and are active for the Run 30 baseline verification.
