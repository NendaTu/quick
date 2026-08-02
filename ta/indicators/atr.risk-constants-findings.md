# atr.py risk constants — audit findings

Four constants were removed from `ta/indicators/atr.py` on 8/1/2026 as part of enforcing
its single concern (measuring ATR, not deciding risk policy from it). This document
records what each one was for and what was found when tracing where they connect
elsewhere in the codebase, for reference before they're acted on further.

## SL_MULT = 1.5

**Stated purpose:** "Standard multiplier for ATR-based stop losses. Distance = ATR * SL_MULT."

**Checked:** `config.py`, `tools/trading_utils.py` (`calculate_position_size`), `ta/scoring.py`,
and `strategies/sweeps/range/range_sweep_ATR.1.mustafa.py` (the one real strategy that
consumes this file for ATR-related logic).

**Finding:** No reference anywhere. `range_sweep_ATR` computes its own stop from FVG
extremes plus `config.SL_MOVE` — not an ATR multiple. Unlike the three constants below,
there's no matching toggle or analog anywhere else in the codebase.

**Recommendation:** No clear centralized home found. If a strategy wants an ATR-based
stop, this looks like it should be that strategy's own tunable — the same way
`is_expansion_candle`'s `multiplier` is already owned by the calling strategy — rather
than a shared constant in either `atr.py` or `config.py`.

## MIN_VOLATILITY = 0.0001

**Stated purpose:** "Minimum absolute ATR value required to trade. Prevents the bot
from entering 'zombie' assets with zero volatility."

**Checked:** `ta/scoring.py`.

**Finding:** `ScoringEngine.evaluate()` does `getattr(config_context, 'MIN_VOLATILITY', 0.0)
or 0.0001` for its "ATR Volatility Floor" check. `config_context` is `config.py` (via
`ConfigContext`'s auto-inheritance of its module-level constants) — exactly where this
was expected to live. It isn't defined there, so scoring.py silently falls back to its
own hardcoded `0.0001` — which happens to be the exact value atr.py's copy held. That's
almost certainly not a coincidence: this constant was very likely meant for `config.py`
and ended up in the wrong file instead. As shipped, editing atr.py's copy had zero
effect on the running system.

**Recommendation:** Define `MIN_VOLATILITY = 0.0001` directly in `config.py`, so
`ScoringEngine` reads the real thing instead of quietly relying on its own fallback.

## VOL_ADJUST_THRESHOLD = 0.002 and REDUCED_RISK_FRACTION = 0.5

**Stated purpose:** "ATR % level above which we consider the market 'Too Volatile' and
reduce risk" / "The fraction of RISK_PER_TRADE used when volatility exceeds
VOL_ADJUST_THRESHOLD."

**Checked:** `config.py`, `tools/trading_utils.py` (`calculate_position_size`).

**Finding:** `config.py` already defines `USE_VOL_ADJUSTED_RISK = False`, described as:
"Toggles reducing your trade risk fraction during high volatility regimes... expect
position sizing models to automatically half your risk when ATR exceeds thresholds."
That "half" is exactly `REDUCED_RISK_FRACTION`'s value. But `calculate_position_size()`
— the one shared sizing function strategies call — never references
`USE_VOL_ADJUSTED_RISK`, `VOL_ADJUST_THRESHOLD`, or `REDUCED_RISK_FRACTION` anywhere.
This is a real, named, toggleable feature whose switch lives in `config.py` and whose
two supporting numbers were stranded in this unrelated indicator file — currently a
no-op even with the toggle flipped on.

**Recommendation:** Move both constants into `config.py` alongside
`USE_VOL_ADJUSTED_RISK`, and add the actual check into `calculate_position_size()` (or
wherever each strategy sizes its position) so the toggle does something.

## Summary table

| Constant | Belongs in `atr.py`? | Where it belongs instead | Confidence |
|---|---|---|---|
| `SL_MULT` | No | Unclear — likely a per-strategy param, not centralized | Low evidence either way |
| `MIN_VOLATILITY` | No | `config.py` — confirmed via `ta/scoring.py`'s direct `getattr` reference | High |
| `VOL_ADJUST_THRESHOLD` | No | `config.py`, alongside `USE_VOL_ADJUSTED_RISK` | High |
| `REDUCED_RISK_FRACTION` | No | `config.py`, wired into `calculate_position_size()` | High |
