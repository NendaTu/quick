# Optimization Rounds Index

| Round | Date | Recommendation | Status | Outcome |
|---|---|---|---|---|
| 1 | 2026-07-13 | Integrate and activate Unified Scoring Engine as an entry filter and fix the zeroed-out metrics log bug | Kept | Successfully resolved zeroed-out metrics log bug, restored cooldowns, and fixed the real-world vs. virtual cooldown bug. |
| 2 | 2026-07-13 | Implement "Zombie Sweep" Prevention by tracking and blocking duplicate trades on previously traded sweeps | Kept | Successfully resolved the Zombie Sweep duplicate entry bug, completely eliminating rapid-fire cascading stop-outs. |
| 3 | 2026-07-13 | Adjust `ENTRY_SCORE_THRESHOLD` in `config.py` from `30.0` to `15.0` to resolve mathematical Denominator Dilution | Kept | Trade frequency recovered fully and robustly from 10 to 74 completed trades, while total loss was slashed by 64%. |
| 4 | 2026-07-13 | De-hardcode minimum stop-loss guard and link it to the central `SL_MOVE` config parameter set at `0.004` (0.4%) | Kept | Average stop-loss distance widened to 0.66%, successfully protecting positions from spread sweeps and order book noise. |
| 5 | 2026-07-13 | Optimize Scoring Engine weights to amplify MACD (2.5) and DRT (2.0) and suppress RSI (0.2) and Structure (0.5) | Kept | Successfully blocked low-confluence trades and reduced portfolio drawdowns on choppy markets. |
| 6 | 2026-07-13 | Enforce strict "Closed-Candle Execution" by passing completed closed candles (`ohlcv[:-1]`) to all strategy calculations | Kept | Drastically improved strategy win rates (killzone_sweep to 42.9%, range_sweep_ATR to 34.2%) and cut overall net loss by 34%. |
| 7 | 2026-07-13 | Refine Scoring Engine weights (Trend to 2.5, Sanity to 2.0, HTF Bias to 2.0) and increase TP1 exit ratio to 70% | Pending | |
