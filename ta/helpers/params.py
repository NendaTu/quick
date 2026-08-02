"""
> ta/helpers/params.py

1. Summary: Single-concern layered parameter resolution for ta/ modules.
2. Description: Resolves a per-call tunable with precedence
   params override > config attribute (if supplied and present) > local
   hardcoded default. Shared so ta/candles/*, ta/indicators/*, and any
   other stateless ta/ module with overridable tunables use one lookup
   instead of each copy-pasting its own.
3. Context: Introduced alongside ta/helpers/overlap.py while de-duplicating
   ta/candles/engulfing.py and (pending) ta/candles/engulfing_total.py.
   First actual consumer wired up: ta/indicators/atr.py (8/1/2026), using
   the list_index path added below. Note engulfing.py itself doesn't parse
   any params today -- its pattern is purely qualitative -- so despite
   being named above, it isn't calling resolve() yet either; that's still
   pending, same as engulfing_total.py.

Audited by Claude on 8/1/2026 -- see resolution of [HELPERS-001] below.
"""

from typing import Any, Optional

_MISSING = object()


def resolve(
    params: Optional[Any],
    key: str,
    local_default: Any,
    config_attr: Optional[str] = None,
    config: Any = None,
    list_index: Optional[int] = None,
) -> Any:
    """
    Resolve a single tunable with precedence:
        params override  >  getattr(config, config_attr)  >  local_default

    [HELPERS-001 -- resolved 2026-08-01] The real caller is
    backtest.py's StrategyWrapper: params come from splitting a
    space-separated CLI-style string (parse_confluence_command's
    `bits[1:]`), so `params` is a plain list of strings at every
    confirmed call site, never a dict. The original version of this
    function only checked for dict-like `.get()` support, so it
    silently fell through to config/local_default on every real call --
    an override the person typed on the command line was accepted and
    then quietly discarded, no error. `list_index` is added to resolve
    against that confirmed shape; dict-like params (`.get()`) are still
    checked first and unchanged, so nothing that already relied on
    passing a dict here needs to change.

    Args:
        params: Per-call overrides. Checked in this order: if
            dict-like (has `.get`), looked up by `key`. Otherwise, if
            it's a list/tuple and `list_index` is given, looked up by
            position. Anything else (including a list with no
            `list_index` supplied) falls through to the tiers below --
            this function never raises on a mismatched shape, so a
            caller that forgets to pass `list_index` degrades to "no
            override found" on a hot trading-decision path rather than
            crashing it.
        key: The override key to look up when `params` is dict-like.
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
        list_index: Position to read from `params` when it's a list/tuple
            (i.e. the confirmed real shape from CLI-style callers). Pass
            None (default) if this tunable has no CLI-positional slot.

    Returns:
        The resolved value. Values from `params` (either tier) are
        returned exactly as given -- callers are responsible for casting
        (e.g. `float()`), since a list-shaped override is always a raw
        string here.
    """
    if params is not None:
        if hasattr(params, "get"):
            value = params.get(key, _MISSING)
            if value is not _MISSING:
                return value
        elif list_index is not None and isinstance(params, (list, tuple)):
            if 0 <= list_index < len(params):
                return params[list_index]

    if config_attr and config is not None and hasattr(config, config_attr):
        return getattr(config, config_attr)

    return local_default
