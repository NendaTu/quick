"""
> ta/helpers/params.py

1. Summary: Single-concern layered parameter resolution for ta/ modules.
2. Description: Resolves a per-call tunable with precedence
   params override > config attribute (if supplied and present) > local
   hardcoded default. Extracted so ta/candles/* (and any other stateless
   ta/ module with overridable tunables) share one lookup instead of each
   copy-pasting its own -- and, previously, non-functional -- version.
3. Context: Introduced alongside ta/helpers/overlap.py while de-duplicating
   ta/candles/engulfing.py and (pending) ta/candles/engulfing_total.py.
"""

from typing import Any, Optional

_MISSING = object()


def resolve(
    params: Optional[Any],
    key: str,
    local_default: Any,
    config_attr: Optional[str] = None,
    config: Any = None,
) -> Any:
    """
    Resolve a single tunable with precedence:
        params[key]  >  getattr(config, config_attr)  >  local_default

    Args:
        params: Per-call overrides. Expected to be dict-like (supports
            `.get`). [HELPERS-001] ta/strategy_interface.py's own docstring
            describes `params` as "a list of command-line arguments" rather
            than a dict, and the actual current caller of
            ta/candles/*.get_signal() could not be located as of this
            writing (checked ta/features.py and strategies/base_strategy.py;
            neither calls it) -- confirmed unresolved as of 2026-07-31. If
            `params` isn't dict-like, this function does not raise; it
            falls through to the config/local_default tiers below, so a
            mismatched shape degrades to "no override found" on a hot
            trading-decision path rather than crashing it. Flagged here,
            specifically and heavily, so a later audit that identifies the
            real caller/shape can fix it in this one place.
        key: The override key to look up in `params`.
        local_default: Value used if neither params nor config supply one.
        config_attr: Name of the flat attribute to read from `config` (e.g.
            "TARGET_NET_ROE"). Pass None to skip the config tier entirely
            for tunables with no equivalent app-wide setting.
        config: The config module or ConfigContext to read from. Callers
            should pass this through explicitly rather than importing the
            bare `config` module here, so a caller running under a
            ConfigContext (see compare.py's multi-variant backtests) gets
            its *own* isolated value instead of whatever the global config
            module happens to hold at that moment. Passing None skips this
            tier -- safe, just not config-aware.

    Returns:
        The resolved value.
    """
    if params is not None and hasattr(params, "get"):
        value = params.get(key, _MISSING)
        if value is not _MISSING:
            return value

    if config_attr and config is not None and hasattr(config, config_attr):
        return getattr(config, config_attr)

    return local_default
