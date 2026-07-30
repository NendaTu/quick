# AGENTS.md — Round 3: Remediation & Modularization Directives for `quick`

## 0. Read This First — Round 3

This is the **third** round of directed audit/remediation work on this repository. Round 1
produced `AGENTS-old.md` (2026-07-27/28, static audit). Round 2 produced `AGENTS-old_2.md`
(exact date/scope unknown to this document's author — see §0.3). This round (2026-07-29) was
produced by re-reading `docs/map.json`, both prior directive files, `BASELINE.md`,
`PROGRESS.md`, `README.md`, and the live contents of ~20 source files on the `development`
branch, then cross-checking every specific claim in `AGENTS-old.md` against what the code
*currently* does. As instructed by Round 1's own Principle §1.6 and §0, **nothing below is
ground truth until you re-verify it against the code in front of you** — file contents may
have moved again since this was written. What follows is a well-evidenced set of hypotheses,
not a guarantee.

### 0.1 The headline finding — read this before doing anything else

**Essentially none of Round 1's P0/P1/P2 backlog has actually landed on `development`,
despite `PROGRESS.md` and `BASELINE.md` implying otherwise, and the repo currently contains
concrete, code-level evidence of a refactor that was started and abandoned mid-flight.**

Specifics, in order of how damning they are:

1. **`PROGRESS.md`'s own last entry says work never got past Phase 0.** It reads: *"Current
   Phase: Phase 0 (Baseline Setup) Complete. Beginning Phase 1."* dated 2026-07-28. No P0–P3
   item has ever been logged as fixed, in this file, by its own account.
2. **Direct re-reading of all 11 files Round 1 deep-audited shows every single P0, P1, and P2
   finding it documented is still present, verbatim, today.** Not "similar" — the same lines,
   the same bugs, in many cases the exact same surrounding code. Full item-by-item
   re-verification is in §3.
3. **`backtest.py` currently cannot run at all.** It contains two independent, guaranteed
   `TypeError`s (detailed in §3, P-1-1/P-1-2) that fire the instant any strategy is loaded or
   any `Engine` is constructed through it. One of the two crash sites is commented
   `# ... model explicitly injected (R0-4)` — i.e. someone was, at some point, in the middle of
   wiring Round 1's P0-2 "shared model" fix and Round 1's P0-1 "overrides into `Engine.__init__`"
   fix into `backtest.py`'s calling code, but the corresponding changes to the *definitions* in
   `main.py::load_strategy` and `engine/core.py::Engine.__init__` were never made. This is not
   speculative — it is a direct reading of both the call sites and the signatures they call.
4. **`BASELINE.md` (dated 2026-07-29 — today) contains a captured smoke-test log referencing a
   logger named `scalper.engine.loop`.** No such logger is created anywhere in
   `main.py`, `engine/core.py`, `engine/entry.py`, or `tools/logger.py::setup_logging()` — the
   only logger names actually configured are `scalper`, `scalper.engine`, `scalper.simulator`,
   `scalper.database`, `scalper.models`, `backtest`, `downloader`. Whatever produced that log
   line either ran different code than what's on `development` right now, or the artifact
   wasn't captured from a genuine run. Either way, **`BASELINE.md` cannot currently be trusted
   as an accurate regression floor** and must be regenerated from a real, freshly-executed run
   — see P3-4.
5. **A `config/` directory exists at the repo root, alongside the still-fully-flat
   `config.py` file.** `docs/map.json` doesn't list anything under it, and it wasn't reachable
   with this round's tooling, so its contents are unknown to this document — but its mere
   existence next to an unmigrated `config.py` is a strong signal that someone already started
   Round 1's P1-2 (`pydantic-settings` package split) and stopped. **Your very first action
   should be `ls`/`view`-ing `config/` to find out what's in it** before you do anything else
   with config, so you don't duplicate or fight against work that's already half-done. See P1-7.

None of this is presented to assign blame — coding-agent sessions get cut off by context
limits and timeouts all the time, and a half-finished edit committed as a checkpoint is a
completely normal thing to find. It's presented because **it changes what "Phase 0" must mean
for this round**: you cannot trust the existing baseline artifacts, you cannot assume "P0-X is
marked handled somewhere" means it's handled, and your first job is reconnaissance, not
backlog-item #1.

### 0.2 Coverage disclosure

**Deep-read and cross-referenced this round:** `docs/map.json`, `AGENTS-old.md` (full),
`BASELINE.md`, `PROGRESS.md`, `README.md`, `config.py`, `main.py`, `engine/base.py`,
`engine/core.py`, `engine/entry.py`, `strategies/base_strategy.py`,
`strategies/scalper.1.jules.py`, `ta/scoring.py`, `compare.py`, `database.py`, `models.py`,
`simulator.py`, `orderbook.py`, `bitget_client.py`, `engine/exchanges/bitget.py`,
`engine/exchanges/bingx.py` (as a placeholder-driver sample), `tools/trading_utils.py`,
`tools/logger.py`, `tools/verify_headers.py`, `backtest.py`.

**Not individually read this round** (same disclosure spirit as Round 1's §0 — reasoned about
only via `docs/map.json` filenames/docstrings, or not at all): the other 8 placeholder
exchange drivers (`bitunix`, `blofin`, `coinex`, `dydx`, `hyperliquid`, `kucoin`, `margex`,
`mexc`), `engine/simulation.py`, all of `ta/patterns/*` (15 files), all of `ta/indicators/*`
(9 files), `ta/candles/*` (3 files), `ta/levels.py`, `ta/utils.py`, `ta/features.py`,
`ta/strategy_interface.py`, `strategies/built/levelFinder.1.agt.py`, both
`killzone_sweep*.py` strategies, `range_sweep_ATR.1.mustafa.py`, the ~25 remaining
`tools/*.py` scripts (including all three `verify_pnl_calculations*.py` versions and
`test_order_pnl_reconciliation.py`, which Round 1 flagged as likely encoding real
financial-correctness assertions worth preserving — still true, still unread), the `.github/workflows/`
directory, the `.jules/docs/dev/` directory, and — critically — **the contents of the new
`config/` directory** and **`AGENTS-old_2.md`** (see §0.3). Do not assume any of this is
clean. Closing this gap is Phase 2 work (§5), same as it was in Round 1 — it's just a bigger
list now because Round 1's own gap was apparently never closed either.

### 0.3 `AGENTS-old_2.md` could not be located this round — find it first

This round's tooling could browse individual files at the repo root and fetch raw file
content by exact URL, but could not browse subdirectory trees or commit history (blocked by
GitHub's `robots.txt` for this access pattern) and could not guess at file paths that weren't
already linked from somewhere reachable. `AGENTS-old_2.md` is not at the repo root (confirmed
— it's alphabetically absent from the root file listing between `AGENTS-old.md` and
`BASELINE.md`), so it almost certainly lives under `docs/` or `.jules/docs/dev/`, both of
which were unreachable this round.

**You have full filesystem access and will find it in seconds. Read it before anything else.**
When you do:
- Reconcile its contents against this document and against actual current code the same way
  this document reconciled Round 1's — mark items it raises as confirmed-open,
  confirmed-fixed, or superseded, with evidence.
- If it contradicts a decision in §3 below (e.g. it changed one of Round 1's §8 defaults),
  its decision wins — it's the more recent record — but log the change explicitly in
  `PROGRESS.md` so the trail stays legible.
- If it describes work that *was* completed, go find that work in the actual codebase (it may
  be sitting uncommitted, on a stray branch, or partially applied — see §0.1's `config/`
  and `backtest.py` findings for what "partially applied" looks like in this repo
  specifically) and either finish integrating it or explain in `PROGRESS.md` why it was
  abandoned.

### 0.4 File lifecycle convention (carried forward from Round 1, now confirmed in practice)

This file (`AGENTS.md`) is the active operating document. When it's superseded by a future
round, it should be renamed `AGENTS-old_3.md` (following the pattern already established:
`AGENTS-old.md` → round 1, `AGENTS-old_2.md` → round 2) and a fresh `AGENTS.md` takes its
place. Keep `PROGRESS.md` as the one continuously-updated, append-only log across all rounds —
it is the only artifact whose job is to accurately answer "what has actually been done," and
per §0.1 it has not been doing that job. Fixing that is itself part of this round's mandate
(P3-4, P3-6).

---

## 1. Non-Negotiable Operating Principles

Carried forward from `AGENTS-old.md` §1 verbatim (items 1–9 below), plus two new ones (10–11)
added this round. All apply to every loop iteration, no exceptions:

1. **This code can place real orders with real money.** `MODE=live` and `MODE=demo` both
   connect to a real exchange (`engine/exchanges/bitget.py`). Every automated test, smoke run,
   or verification you perform must run with `MODE=paper` or against a stubbed/mocked exchange
   client. Never invoke `demo` or `live` mode, and never add automation that could. If a task
   genuinely requires live/demo verification, stop and ask the human.
2. **Never surface secrets.** Treat `.env` and any `BITGET_*_KEY`, `*_SECRET`, `*_PASSPHRASE`
   value as sensitive. Confirm `.env` is gitignored as an early check (re-confirm this — don't
   trust that Round 1/2's confirmation still holds).
3. **No silent behavior changes to money-moving logic.** State "before → after" explicitly in
   commit message and `PROGRESS.md` for anything touching trades taken, sizing, stop/target
   placement, or fee/PnL math.
4. **Every change is independently verifiable.** Write the test/verification script before or
   alongside the fix, not after. Reading the diff and feeling confident is not verification —
   see §0.1 for exactly what happens when that discipline slips.
5. **Small, reversible increments.** One backlog item per commit. The tree builds/imports
   cleanly at every commit — literally: `python3 -c "import main, backtest, compare"` should
   not raise, and per §2 it currently does.
6. **When intent is ambiguous, don't guess silently.** Document both readings, propose a
   default, flag it, move on.
7. **Preserve the existing decision trail.** `[TECH-001]`, `[ARCH-003]`, `[REPAIR-20260708]`,
   `[CS-004]`, `[C-004]`, `[R0-2]`, `[R0-4]`, `[BT-001]`, `[BT-002]`, `[PERF-001..004]` tags are
   all present in the current code (some are new since Round 1's list — add them to this list
   as you find more). Consolidate/index them, don't erase the history.
8. **Work on a branch**, e.g. `agent/foundation-hardening-r3`, never directly on
   `development`/`main`. No force-push, no history rewriting. **Before you start this branch,
   check whether an `agent/*`-style branch already exists with Round 1/2's abandoned work on
   it** (§0.1) — if so, that may be a better starting point than `development` HEAD.
9. **"Microservice-esque" means discipline, not deployment topology.** Single-concern modules,
   narrow explicit interfaces, dependency injection, independent testability — inside **one
   deployable process**. No network calls/queues/IPC in the hot trading-decision path. The one
   place a real process boundary may eventually make sense is a future read-only UI-facing API
   (P4-1), and that's still deferred, not part of this pass — see §11 for how this connects to
   the Tauri/IDE UI plan.
10. **A claim of completion is not completion.** Before marking any backlog item done in
    `PROGRESS.md`, actually run the thing that would fail if it weren't done, and paste real
    output (or a real test-run summary) into the log entry — not a description of what running
    it *would* show. §0.1 exists because this discipline lapsed at least once already.
11. **If you find a half-finished edit (a call site updated but not its definition, a new file
    or directory that isn't wired up, a comment referencing a fix that isn't there), your
    default is to finish it, not revert it** — unless finishing it would mean guessing at a
    design decision Principle §6 says not to guess at, in which case document the fork and
    pick the option that matches this document's stated target architecture (§4) if one
    applies. Reverting working-but-incomplete intent back to a *known-worse* state (e.g.
    restoring `engine/entry.py`'s hardcoded `"limit"` string because a config-driven version
    half-exists somewhere and is inconvenient to finish) is not an acceptable shortcut.

---

## 2. IMMEDIATE BLOCKERS — Fix These Before Reading Further Into the Backlog

These are not P0 items in the Round 1 numbering sense — they're more urgent than that,
because **nothing else in this document can be verified while they stand.** `backtest.py` is
this repo's primary correctness-testing tool (per its own README usage docs) and it currently
cannot execute a single strategy. Fix these three first, each as its own tiny, obviously-safe
commit, before you even re-run Phase 0.

### P-1-1 — `backtest.py` calls `load_strategy(..., model=...)`, but `load_strategy` has no `model` parameter

**Where:** `backtest.py::StrategyWrapper._load_strategy` (called from `parse_confluence_command`
at startup and again from both `run_backtest` and `run_backtest_portfolio` for every asset/run).

**Evidence:**
```python
# backtest.py
def _load_strategy(self, path, model=None):
    from main import load_strategy
    ...
    res = load_strategy(rel_path, simulator=self.simulator, model=model, overrides=self.overrides)
```
```python
# main.py — actual current signature
def load_strategy(strategy_path: str, simulator=None, overrides=None):
```
`load_strategy` has three parameters and no `**kwargs`. Calling it with `model=...` raises
`TypeError: load_strategy() got an unexpected keyword argument 'model'` every time. The call
sites in `run_backtest`/`run_backtest_portfolio` (`wrapper._load_strategy(wrapper.path,
model=engine.model)`, tagged `# ... model explicitly injected (R0-4)`) make the intent clear:
this is Round 1's P0-2 fix (shared `LearningModel` instance via constructor injection) started
in `backtest.py` and never finished in `main.py`.

**Fix:** Finish it, per Principle §1.11 — this is exactly the direction P0-2 already decided
on. Add `model=None` to `load_strategy`'s signature; thread it through both the recursive
directory-discovery branch and the single-file instantiation branch
(`obj(simulator=simulator, model=model, config_overrides=overrides)`); then update
`BaseStrategy.__init__`/`JBaseStrategy.__init__` to accept and store it (this also happens to
be exactly what P0-7 already needs for `simulator`, so do both parameters together); then
update `ScalperStrategy.__init__` to use the injected model when provided instead of always
constructing its own `LearningModel(simulator)`; then update `main.py`'s own call
(`load_strategy(strategy_query, simulator=engine.exchange, overrides=overrides)`) to pass
`model=engine.model` too, so the live/paper/demo path gets the same fix `backtest.py` was
reaching for. This single change closes P-1-1 and P0-2 (Round 1) together.

**Verify:** `python3 backtest.py scalper.1.jules 2026-05-01 2026-05-02 assets=BTCUSDT` runs to
completion without a traceback. Add a unit test instantiating a strategy via `load_strategy`
with an explicit `model=` and asserting `strategy.model is that_model`.

---

### P-1-2 — `backtest.py` constructs `Engine(..., config_overrides=...)`, but `Engine.__init__` has no `config_overrides` parameter

**Where:** `backtest.py::run_backtest` and `run_backtest_portfolio`.

**Evidence:**
```python
# backtest.py, both functions
from engine.core import Engine
engine = Engine(use_db=False, mode="paper", config_overrides=overrides)
```
```python
# engine/core.py — actual current signature
def __init__(self, use_db=True, mode=None, config_context=None):
```
Same failure mode as P-1-1: `TypeError: __init__() got an unexpected keyword argument
'config_overrides'`, on every backtest run. This is the calling-code half of Round 1's P0-1
fix ("thread `overrides` into `Engine.__init__` itself... so it applies them to the
`ConfigContext` object before anything downstream reads it") with the receiving-code half
never written.

**Fix:** Finish it, matching Round 1's P0-1 recommendation exactly: add `overrides: Optional[Dict]
= None` to `Engine.__init__`, and apply it to `self.config` (the `ConfigContext` instance)
immediately after constructing it, before any component that reads `self.config` is built
(exchange selection, model, router). Then fix `main.py::main()` to use this — construct
`Engine(mode=args.mode, overrides=overrides)` *after* `overrides` is parsed, instead of the
current `Engine(mode=args.mode)` followed by a separate `load_strategy(..., overrides=overrides)`
that mutates the bare `config` module. Also stop `JBaseStrategy.__init__`/`get_config()` from
touching the bare `config` module at all (per Round 1 §8's confirmed addendum to P0-1). This
closes P-1-2 and Round 1's P0-1 and P1-6 together.

**Verify:** Same backtest smoke command as P-1-1. Add the regression test Round 1's P0-1
already specified: construct an engine with an `ENTRY_SCORE_THRESHOLD` override via the same
code path `main.py` uses, feed `ScoringEngine.evaluate()` a fixture that would pass the
default threshold but fail the overridden one, assert it's rejected.

---

### P-1-3 — Live/demo limit-entry timeout handler calls `self.engine.ledger`, which doesn't exist

**Where:** `engine/exchanges/bitget.py::BitgetExchange._process_orders`.

**Evidence:**
```python
# engine/exchanges/bitget.py
if self.engine:
    pos_key = f"{o['symbol']}_{o['pos_side']}"
    self.engine.ledger.remove_pending(pos_key)
```
`Engine` (in `engine/core.py`) has no `ledger` attribute anywhere — it tracks pending entries
in a plain `self.pending_entries: Set[str]`. The correct pattern already exists two files
away, in `Simulator._process_orders` (`simulator.py`):
```python
if self.engine:
    pos_key = f"{o['symbol']}_{o['pos_side']}"
    if pos_key in self.engine.pending_entries:
        self.engine.pending_entries.remove(pos_key)
```
This means: the first time a live or demo limit entry order times out
(`LIMIT_CHASE_TIMEOUT`, default 10s), this line raises `AttributeError: 'Engine' object has
no attribute 'ledger'`. Depending on where that exception surfaces relative to any
surrounding `try/except`, this either crashes the background order-processing loop or (more
likely, given `data_feed_task`'s `except Exception` wrapper) gets swallowed and logged —
**leaving the symbol/side stuck in `pending_entries` forever**, silently blocking all future
entries on that symbol+side and permanently misreporting exposure, on a **live or demo
account with a real order that just got cancelled on the exchange side**.

**Fix:** The name `ledger` matches this document's own proposed `engine/positions.py::PositionLedger`
target module (§4) closely enough that this may be a second fragment of an abandoned P1-1
decomposition attempt, not a typo — worth a quick `git log -p` / `git blame` check on this
line before treating it as simple vandalism-by-autocomplete. Either way, the immediate,
safe fix is mechanical: match `Simulator`'s pattern —
```python
if self.engine:
    pos_key = f"{o['symbol']}_{o['pos_side']}"
    if pos_key in self.engine.pending_entries:
        self.engine.pending_entries.remove(pos_key)
```
If you do find evidence of a real, farther-along `PositionLedger` attempt elsewhere (branch,
stash, `config/`-style orphaned directory), prefer finishing that over this patch — but don't
let this specific bug sit unpatched while you look; it's a live-money crash-and-leak bug.

**Verify:** Unit test (mocked exchange) that creates a `BitgetExchange` with a fake `engine`
exposing `pending_entries`, adds a pending `entry_limit` order older than
`config.LIMIT_CHASE_TIMEOUT`, calls `_process_orders()`, and asserts no exception and that the
`pos_key` was removed from `pending_entries`.

---

Also as part of this immediate-blockers pass: run `view config/` (or `ls -la config/`) and
paste what you find into `PROGRESS.md` before proceeding to §3. You don't have to act on it
yet — P1-7 covers that — but every subsequent decision about `config.py` should be made with
full knowledge of what's already sitting next to it.

---

## 3. Priority Backlog

Same tier discipline as Round 1: work top-to-bottom, finish a tier before starting the next,
unless a lower-tier item is trivially bundled with a higher-tier item you're already touching
in the same file. IDs continue Round 1's numbering — nothing is renumbered, per the
"living, append-only" instruction in `AGENTS-old.md` §0. Every item below marked **RE-CONFIRMED
OPEN** was checked against the actual current file content this round, with a short excerpt of
what's still there; items marked **NEW** were not in Round 1's document at all.

### P0 — Correctness & Risk

| ID | Title | Round 3 Status |
|----|-------|-----------------|
| P0-1 | Config overrides don't reach trading-decision components | **RE-CONFIRMED OPEN.** `main.py::main()` still does `engine = Engine(mode=args.mode)` before `load_strategy(..., overrides=overrides)`. Folded into P-1-2's fix above — do both together. |
| P0-2 | Online-learning split-brain (train ≠ decide) | **RE-CONFIRMED OPEN.** `Engine.__init__` still builds its own `LearningModel(self.exchange)`; `ScalperStrategy.__init__` still independently builds `self.model = LearningModel(simulator)`. Folded into P-1-1's fix above — do both together. |
| P0-3 | Duplicate-entry exposure race across strategies | **RE-CONFIRMED OPEN, and now more exercisable.** `Engine._asset_is_tradable`'s guard is still `if pos_key in self.open_positions or (pos_key in self.pending_entries and signal is None): return False` — since the live call sites always pass a real `signal`, the `pending_entries` half of this check is permanently dead. The double-call of `_asset_is_tradable` (once before entry math, once right after `pending_entries.add(pos_key)`) is still there too, and for the same reason still doesn't catch a same-tick collision. **New in Round 3:** `Engine` now has first-class multi-strategy support (`self.strategies: List[any]`, `main.py::load_strategy`'s new recursive "Family" discovery, `engine.strategies = strategies` for a whole directory), and `_asset_is_tradable` has a *new* conditional — `if len(self.strategies) <= 1:` — that **skips the opposite-side collision check entirely whenever 2+ strategies are active**, meaning two strategies can now legitimately open a long and a short on the same symbol simultaneously with zero warning. Since multiple strategies signaling the same symbol at once is no longer a hypothetical, implement Round 1's decided fix (atomic first-accepted-wins reservation, with skip logging) now, not later. |
| P0-4 | No aggregate exposure cap | **RE-CONFIRMED OPEN.** `config.py` still has `MAX_CONCURRENT_POSITIONS = 1000` (not the decided default of 15), and no aggregate-margin-based cap exists anywhere — `Engine._trading_loop`'s only gate is still the raw position count against `MAX_CONCURRENT_POSITIONS`. Implement Round 1's decided default (10% of equity aggregate cap, `MAX_CONCURRENT_POSITIONS` → 15) as a first-class, config-driven check. |
| P0-5 | Live/demo hardcodes `"limit"` order type | **RE-CONFIRMED OPEN.** `engine/entry.py::SignalRouter.route_signal`'s live/demo branch is still `return await self.exchange.place_order(symbol, side, "limit", qty, price, **kwargs)`. Read from `self.config.ENTRY_ORDER_TYPE` (and confirm `TP_ORDER_TYPE`/`SL_ORDER_TYPE` wiring at the exit-order call sites, per Round 1 §8's confirmed extension). |
| P0-6 | Strategy state type changes silently (DB vs. in-memory) | **RE-CONFIRMED OPEN.** `JBaseStrategy.save_state` still does `self._mem_state[key] = str(value)` unconditionally; `get_state`'s in-memory branch still does a bare `return self._mem_state.get(key)` with no deserialization — only the DB-backed branch attempts `ast.literal_eval` (and only when the string starts with `{`/`[`). Store real objects in `_mem_state`, not stringified ones, per Round 1's confirmed decision. |
| P0-7 | Strategy↔simulator wiring is unenforced | **RE-CONFIRMED OPEN.** `BaseStrategy.__init__` (engine/base.py) still only does `self.config_overrides = config_overrides or {}` — no `simulator` parameter. `ScalperStrategy.__init__` still accepts `simulator` but never does `self.simulator = simulator`. `_get_ohlcv` still silently returns `[]`, `is_ready()` still silently returns `True`, when `simulator`/`required_history` are absent. Fold this fix into P-1-1's work above (same constructor you're already touching for `model`). |
| **P0-8** | **NEW — `backtest.py` cannot run (two `TypeError`s)** | See P-1-1 and P-1-2 above. Listed here too so it stays in the numbered backlog for `PROGRESS.md` bookkeeping purposes; the actual fix work is in §2. |
| **P0-9** | **NEW — Live/demo limit-timeout handler references non-existent `self.engine.ledger`** | See P-1-3 above. Same bookkeeping note. |
| **P0-10** | **NEW — Position sizing silently ignores config-context overrides** | **Where:** `models.py::LearningModel.predict()` → `tools/trading_utils.py::calculate_position_size()`. **Evidence:** `predict()` builds `cfg = self.simulator.config` and uses it for essentially every other parameter in the function (`getattr(cfg, 'MAKER_FEE', ...)`, `getattr(cfg, 'RISK_PER_TRADE', ...)`, etc.), but its call to `calculate_position_size(riskable_equity, risk_fraction, entry, stop_price, entry_maker=..., exit_maker=..., fee_aware=...)` passes **no `config=` argument**. `calculate_position_size` (and its sibling fee/PnL helpers in `tools/trading_utils.py`) fall back to `import config as default_config` — the bare module — whenever `config` isn't explicitly passed. So the single most safety-critical number in the whole system (how large a position to actually open) is computed against whatever the raw `config` module currently holds, not against the `ConfigContext`/overrides that everything else in the same function correctly respects. This is a fresh, concrete instance of the exact P0-1/P1-6 pattern, in the highest-stakes possible location. **Fix:** pass `config=cfg` explicitly at this call site (and audit every other `tools/trading_utils.py` call site the same way — `calculate_fees` is also called without `config=` from `simulator.py::_execute_entry_direct`/`_execute_exit`). **Verify:** construct a `ConfigContext` with an overridden `MAKER_FEE`, call `predict()` through it, assert the computed `qty` reflects the override, not the module default. |
| **P0-11** | **NEW — Paper-mode fee assumption diverges from live/demo's documented one for TP/SL exits** | **Where:** `simulator.py::Simulator.place_trade_oco`'s "narrow fee trap" filter vs. `engine/exchanges/bitget.py::BitgetExchange.place_order`'s equivalent filter. **Evidence:** the live/demo version has an explicit comment: *"R0-2: On live/demo Bitget exchanges, take-profits and stop-losses always execute at market (taker)... we always assume taker fees for the exit leg."* and hardcodes `exit_fee_rate = self.config.TAKER_FEE`. The paper-mode version instead does `exit_fee_rate = self.config.MAKER_FEE if self.config.TP_ORDER_TYPE == "limit" else self.config.TAKER_FEE` — i.e. it assumes maker fees whenever `TP_ORDER_TYPE == "limit"` (the default). If the R0-2 comment is correct about real Bitget TP/SL mechanics, paper-mode backtests and paper trading are systematically understating real trading costs on every exit, which means paper results **overstate** how a strategy will actually perform live. **Fix:** this is a judgment call under Principle §6 (is R0-2's assumption actually correct for how this bot posts TP/SL — plan vs. limit orders — and if so, should paper mode mirror it exactly, or is there a legitimate reason a plan-triggered TP/SL might still get maker treatment here?) — don't silently pick one. Document both readings, propose mirroring R0-2's assumption in `simulator.py` as the default (parity with live matters more here than either being "more optimistic"), and flag it in `PROGRESS.md` for a human sanity-check given it changes projected profitability, per Principle §3. |

### P1 — Architecture & Single-Concern Modularity

| ID | Title | Round 3 Status |
|----|-------|-----------------|
| P1-1 | `engine/core.py::Engine` is a god object | **RE-CONFIRMED OPEN.** The file is, if anything, larger than Round 1 described — it now also owns multi-strategy heartbeat/warmup bookkeeping (`_warmup_logged`, `_ready_logged`) on top of everything Round 1 listed. None of the proposed `loop.py`/`positions.py`/`risk.py`/`reporting.py`/`regimes.py`/`reconciliation.py`/`factory.py`/`signal.py` split exists — it's still one ~500-line class doing config bootstrap through exchange-state reconciliation. See P1-7 and P-1-3 for two concrete fragments (`config/` dir, `self.engine.ledger`) that suggest someone already started reaching for this exact decomposition — use them as a starting point/precedent, not just a warning. |
| P1-2 | `config.py` is one flat, ungoverned namespace | **RE-CONFIRMED OPEN, but see P1-7 below — do not start this from scratch.** `ConfigContext.__init__` is byte-for-byte the same reflection hack, same manual exclusion list (`os`, `datetime`, `pytz`, `load_dotenv`, `get_env_stripped`). No `pydantic-settings` import anywhere in `config.py`. |
| P1-3 | `hasattr`/`getattr` duck-typing everywhere | **RE-CONFIRMED OPEN.** Still rampant in `engine/core.py` (`asset_correlations`, `recalculate_correlations`, `ready_assets`, `books`, `is_ready`, `params`, `db`, `symbol_map`/`rev_symbol_map`) and now also visibly present in `simulator.py` and `engine/exchanges/bitget.py` (`hasattr(self, 'positions')`, `hasattr(self.books[sym], "_regenerate")`, etc. — this wasn't individually catalogued by Round 1 since those files weren't deep-read then). |
| P1-4 | `Signal` is an untyped dict | **RE-CONFIRMED OPEN.** Still built/mutated as a raw dict across `engine/core.py`, `models.py`, `engine/entry.py`, `simulator.py`, `backtest.py`. |
| P1-5 | `SignalRouter._init_exchange()` is dead/duplicate | **RE-CONFIRMED OPEN.** Unchanged — still doesn't pass `config_context`, still doesn't set `.engine`, still unreachable in the current call graph since `Engine` always passes its own `exchange`. |
| P1-6 | Two override mechanisms, incompatible ordering | **RE-CONFIRMED OPEN**, and now there are **three**: `main.py` (broken ordering), `compare.py::variant_runner` (correct — applies to the bare module before `import engine`), and `backtest.py::run_backtest[_portfolio]` (a fourth variant: `importlib.reload(config)` then `setattr` on the module, then attempts to pass `config_overrides=` into `Engine.__init__`, which per P-1-2 doesn't even accept that parameter today). Resolve as one mechanism, used identically by all three entry points, per P0-1/P-1-2's fix. |
| **P1-7** | **NEW — A `config/` directory already exists at the repo root, next to the still-flat `config.py`** | The repository root listing shows a `config` **directory** alongside `config.py`, `database.py`, etc. — this was not reachable with this round's tooling (no directory listing access), and it is **not** referenced anywhere in `docs/map.json`, so its contents and purpose are unknown to this document. Given P1-2's target layout (§4) is literally a `config/` package with `settings.py`/`risk.py`/`execution.py`/`scoring.py`/`logging.py`/`simulator.py` submodules, this is almost certainly either (a) a start on exactly that migration that stalled, (b) an empty/scaffold directory, or (c) something unrelated (e.g. deployment config, unrelated to `config.py` at all). **First action, before touching `config.py` at all: read what's actually in there** (`view config/`), and act accordingly — finish it if it's (a) and salvageable, ignore/repurpose if it's (c), and either way document what you found in `PROGRESS.md` so this stops being a mystery for whoever reads this next. |

### P2 — Consistency, Duplication & Hygiene

Round 1's original 15-item table (P2-1 through P2-15) — **every single row re-confirmed open**
this round via direct inspection, no exceptions, **except P2-15's header-marking half, which
appears to have actually landed** (see below). Rather than reproduce the full original table
verbatim, here is the re-verification status plus what's new. Full original text/evidence for
P2-1–P2-15 is in `AGENTS-old.md` §2 — treat it as still accurate.

- **P2-1 (TF_SECONDS duplicated):** **RE-CONFIRMED OPEN, and worse than documented.** Round 1
  found it duplicated in ~4 places. This round found it (or a near-copy) in at least
  **six**: `config.py` (canonical), `database.py` (twice — `has_data_gaps` and
  `get_data_gaps`), `strategies/base_strategy.py::get_readiness_eta`,
  `compare.py::DataCoordinator.warm_up`, `simulator.py::fetch_symbol_data`, plus a distinct
  partial copy (`_update_candles`, see P2-16 below, which is the dangerous one — it's not just
  duplicated, it's duplicated *wrong*).
- **P2-2 (asset-discovery duplicated):** **RE-CONFIRMED OPEN, and now triplicated, not
  duplicated.** The identical sort/filter/stablecoin-exclusion block (down to the literal
  `["USDC", "DAI", "BUSD", "EUR", "GBP"]` list) now exists in `Engine.start()`,
  `compare.py::DataCoordinator.warm_up()`, **and** `simulator.py::DataAcquisitionManager.initialize_metadata()`,
  **and** `backtest.py::discover_assets()` — four copies. Extract the single
  `discover_assets(tickers, omitted, count)` function Round 1 already specified and use it
  everywhere.
- **P2-3 (`asset_conf` dead dimension):** **RE-CONFIRMED OPEN.** `ta/scoring.py` still computes
  `raw_scores["asset_conf"] = raw_scores["trend_15m"]` and still iterates it in
  `directional_keys`; `config.py` still carries `WEIGHT_ASSET_CONF = 0.0`. Round 1's decided
  default (remove it) was never applied.
- **P2-4 (tunables hidden as magic defaults, absent from `config.py`):** **RE-CONFIRMED OPEN.**
  `MIN_VOLATILITY` and `VOL_PCT_MIN` are still referenced via `getattr(config_context, KEY,
  default)` in `ta/scoring.py` and are still absent from `config.py` entirely.
- **P2-5 (stale `getattr` fallback literals don't match configured values):** **RE-CONFIRMED
  OPEN.** `ta/scoring.py` still has `entry_threshold = getattr(config_context,
  'ENTRY_SCORE_THRESHOLD', 30.0)` (configured value is 15.0) and `report_only =
  getattr(config_context, 'BY_DEFAULT_REPORT_ONLY', True)` (configured value is `False`).
- **P2-6 (bare/broad `except:`):** Not independently re-audited this round beyond what was
  visible in files already read (several are visible, e.g. `main.py`'s strategy-override
  parsing `try/except: overrides[k] = v`, `compare.py`'s several bare `except:` around queue
  operations). Treat as still open; do the full sweep Round 1 specified.
- **P2-7 (`RISK_PER_TRADE` mislabeled as "Target net profit per trade"):** **RE-CONFIRMED
  OPEN**, unchanged line in `main.py`: `log.info(f"Target net profit per trade:
  {RISK_PER_TRADE*100}% of equity")`.
- **P2-8 (hardcoded `"scalper"` logger name):** **RE-CONFIRMED OPEN.** `main.py` still has
  `log = logging.getLogger("scalper")` as a bare literal. Note for whoever verifies this next:
  don't be fooled by `BASELINE.md`'s captured output showing `scalper.*`-prefixed log lines —
  that's exactly what this hardcoded value produces when the strategy being run *happens* to
  be named `scalper`; it proves nothing about whether the name is actually derived from the
  loaded strategy. It isn't.
- **P2-9 (fuzzy-match fallback non-recursive):** **RE-CONFIRMED OPEN.** `main.py::load_strategy`'s
  fuzzy-match branch still does a plain `for f in os.listdir("strategies"):` — non-recursive —
  even though a *different*, newer branch of the same function
  (`# 1. Directory-based Discovery (Recursive Families)`) now does proper `os.walk`-based
  recursion for a different case. The two code paths have drifted; the specific fallback P2-9
  named is still exactly as broken as documented.
- **P2-10 (stale scaffolding comment):** **RE-CONFIRMED OPEN.** `engine/entry.py` still has
  `# In a real implementation, this would call self.exchange.place_order` directly above code
  that already does call `self.exchange.place_order`.
- **P2-11 (DB path not mode-aware):** **RE-CONFIRMED OPEN.** `Database.__init__` still resolves
  to a single hardcoded `market_data.db` regardless of mode; no `config.DB_PATH` exists.
- **P2-12 (mixed sync/queued DB write paths, no documented threading contract):**
  **RE-CONFIRMED OPEN.** Same split as documented: `save_tick`/`save_candle`/`save_log`/`save_signal`/`save_trade`
  go through the queue; `save_weight`/`save_strategy_state`/`save_discovered_assets` and all
  `get_*` reads hit `.connection` directly, synchronously, with no `check_same_thread=False`
  and no documentation of the assumption.
- **P2-13 (`compare.py` scans full `sys.argv` instead of argparse's `remaining`):**
  **RE-CONFIRMED OPEN.** Both override-parsing loops in `compare.py::parse_args` still iterate
  `sys.argv[1:]` directly rather than the `remaining` list `parse_known_args()` already hands
  back.
- **P2-14 (`LearningModel.predict` calls `ScoringEngine.evaluate` twice per prediction):**
  **RE-CONFIRMED OPEN.** `models.py::predict()` still computes `buy_res` and `sell_res` via two
  full, independent calls, fully recomputing every side-independent raw score both times.
- **P2-15 (placeholder exchange drivers unmarked):** **PARTIALLY DONE — genuine progress
  found.** `engine/exchanges/bingx.py` (checked as a sample) now carries `STATUS: placeholder,
  not implemented` directly in its 3-part header's Context field, and `tools/verify_headers.py`
  does validate that all three header fields are present. **Gap:** `verify_headers.py` only
  checks that the labeled sections exist, not their *content* — it would still report success
  even if someone silently deleted the `STATUS: placeholder` text from within Context, or if a
  driver were half-implemented but left the marker in place by mistake. Tighten
  `verify_headers.py` to specifically assert `STATUS: placeholder, not implemented` (or a
  real-status equivalent) is present for every file under `engine/exchanges/` that isn't
  `bitget.py`, and confirm the other 8 placeholders (`bitunix`, `blofin`, `coinex`, `dydx`,
  `hyperliquid`, `kucoin`, `margex`, `mexc`) actually carry the same marker — only one of nine
  was sampled this round.

**New P2 items found this round:**

- **P2-16 — NEW, and the most concrete correctness bug in this list:** `simulator.py::DataAcquisitionManager._update_candles`
  has its own local timeframe-seconds map:
  ```python
  tf_map = {
      "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
      "1H": 3600, "4H": 14400, "1D": 86400
  }
  ```
  This is missing **`"3m"`**, which is present in the canonical `config.TF_SECONDS` and in
  `config.AVAILABLE_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1H", "4H", "1D"]`.
  `_update_candles` is what appends new candles as live trade ticks stream in (called from
  `_ws_callback`'s `trade` handler). Since `"3m"` isn't in *this* dict, the 3m timeframe never
  gets a new candle appended after the initial historical warm-up — it goes stale and stays
  stale for the rest of the session, silently, in both paper mode and (since
  `engine/exchanges/bitget.py` also calls `self._update_candles(...)` from its own `_ws_callback`)
  **live/demo mode too**. Anything reading 3m data (confluence checks, any strategy with
  `required_history` including `"3m"`) is working off frozen data mid-session without any
  error or warning. **Fix:** delete this local dict and import `config.TF_SECONDS`, closing
  this specific instance of P2-1 and the correctness bug at the same time. **Verify:** a test
  that feeds two ticks a few seconds apart through `_update_candles` for a symbol with `"3m"`
  in `AVAILABLE_TIMEFRAMES`, and asserts a 3m candle actually gets created/updated.
- **P2-17:** See P0-11 above (paper/live fee-model divergence) — filed as P0 given its
  profitability-projection impact, cross-referenced here since it's also a hygiene/consistency
  issue between two near-duplicate filter implementations.
- **P2-18:** `compare.py::download_asset_tf_gap` (inside `DataCoordinator.warm_up`) does
  `from tools.downloader import RateLimiter`, a local import that shadows the module-level
  `from bitget_client import BitGetClient, BitGetWSClient, RateLimiter` already imported at
  the top of the same file. Confirm whether `tools/downloader.py`'s `RateLimiter` is the same
  implementation as `bitget_client.py`'s (re-exported) or a genuinely separate one — if
  separate, that's a second P2-1-style duplicated-concept problem (two rate limiters that can
  silently drift apart); consolidate to one either way.
- **P2-19:** `bitget_client.py` imports `BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE`
  from `config` at module level but never references them anywhere in the file body (all real
  usage goes through constructor-injected `self.api_key`/etc.). Dead import; remove, and while
  auditing, check whether this was meant to be a fallback-default mechanism that never got
  wired up (Principle §6 — don't just delete without a quick look at whether it was headed
  somewhere).
- **P2-20:** `SimulatedOrderBook._regenerate()` (`orderbook.py`) fabricates bid/ask depth via
  `random.uniform(500, 2000)` at both levels of the book. This is fine as a bootstrap-only
  placeholder before real data arrives (that's its documented purpose), but confirm nothing
  (e.g. `RESTRICT_LIQUIDITY`'s `top_bid_ask_qty()` check) can act on this randomized
  placeholder data before real book data has actually populated it — if it can, that's a gate
  evaluating against noise, not depth, for a real (if brief) window every session.

### P3 — Testing & Verification Infrastructure

Round 1's P3-1 (no real `tests/`/`pytest` suite), P3-2 (no CI), P3-3 (standing paper-mode
smoke test) are **status unclear this round** — `BASELINE.md` claims `pytest` is now set up
and 39 tests pass, including a new `tools/test_remediation.py` not present in Round 1's
`docs/map.json`. Given §0.1's finding that `BASELINE.md`'s own captured output doesn't match
current code, **do not take this claim at face value either** — confirm `tests/` (or
wherever `test_remediation.py` actually lives) exists and genuinely passes against current
`development` HEAD, post-§2 fixes, before crediting P3-1 as done.

- **P3-4 — NEW:** `BASELINE.md` and `PROGRESS.md` do not currently reflect the real, runnable
  state of `development` (§0.1). Once §2's three blockers are fixed, regenerate both from
  scratch: real `pytest` run output, a real bounded paper-mode smoke run
  (`python3 main.py --strategy scalper.1.jules --mode paper`, capture and let it run long
  enough to pass through asset warm-up), and a real `python3 backtest.py scalper.1.jules
  <date> <date> assets=BTCUSDT` run — paste actual captured output, not a paraphrase.
- **P3-5 — NEW:** Locate and read `AGENTS-old_2.md` (§0.3) — folded in here as a formal
  backlog item so it isn't lost, even though the actual action is "go read a file you have
  access to and I don't."
- **P3-6 — NEW:** Whatever caused `PROGRESS.md` to stall at "Phase 0 complete, beginning Phase
  1" without a single subsequent entry — across what appears to be at least one full
  additional round of work (Round 2) — is worth a moment of explicit reflection before you
  start Round 3's own loop. If it was a context/session limit, structure your own work into
  more, smaller, independently-committed chunks so a cutoff mid-session still leaves
  `PROGRESS.md` accurate up to the last completed item, rather than accurate only up to the
  last item you *intended* to also write up.

### P4 — Forward-Looking (deferred — do not let this block P-1/P0–P3)

Round 1's P4-1 (stable read/event facade for a future UI), P4-2 (thin entry-point adapters),
P4-3 (placeholder exchange roadmap-vs-prune) all still apply unchanged and are still
correctly deferred. See §11 for how P4-1 specifically connects to the Tauri/IDE UI plan
mentioned in this round's request — worth a read now even though the work itself stays
deferred, since it may subtly influence which interface shapes you pick during the P1
decomposition (e.g. favoring a facade-friendly `reporting.py`/`reconciliation.py` interface
now costs little and saves a rework later).

---

## 4. Proposed Target Module Layout

Unchanged from Round 1 (`AGENTS-old.md` §3) — still a starting proposal, not a rigid mandate,
and still fully unimplemented, so there's nothing to reconcile against divergent reality yet.
One amendment based on this round's findings:

```
engine/
  loop.py            TradingLoop: pure iteration + signal-generation orchestration.
  positions.py        PositionLedger: open_positions / pending_entries bookkeeping only.
                      NOTE: engine/exchanges/bitget.py already references
                      `self.engine.ledger.remove_pending(...)` (P-1-3) — a dangling call to
                      exactly this abstraction under exactly this kind of name. Treat that as
                      a found sketch of the intended interface, not just a bug: when you build
                      this module for real, check whether `remove_pending(pos_key)` (and
                      whatever its sibling methods would need to be) is in fact the natural
                      shape, and wire the bitget.py call site to the real thing instead of the
                      minimal patch suggested in P-1-3.
  risk.py              RiskGate: drawdown/ROI/trade-count/duration limits, aggregate
                      exposure cap (P0-4), tradability gate (correlation/liquidity/cooldown),
                      and — new since Round 1 — cross-strategy same-tick collision arbitration
                      (P0-3), since multi-strategy execution is now a first-class feature, not
                      a hypothetical.
  reporting.py         TradeReporter / StatsAggregator: unchanged from Round 1.
  regimes.py           RegimeClassifier: unchanged from Round 1.
  reconciliation.py    Everything currently in _sync_exchange_state: unchanged from Round 1 —
                      still the highest financial-correctness stakes in the file, still gets
                      its own dedicated test file before anything else in this list.
  factory.py           build_engine(mode, overrides, model=None, ...): the one place mode ->
                      exchange/model selection happens. This is also where P-1-1/P-1-2's
                      `overrides`/`model` constructor parameters should ultimately live once
                      Engine itself is thin — build it with that in mind from the start rather
                      than bolting overrides onto today's fat `Engine.__init__` and then
                      re-extracting them later.
  signal.py            The typed Signal/OrderRequest dataclass from P1-4.

config/
  (contents unknown — see P1-7. Read what's there before building this fresh. If it's empty
  or unrelated, the layout below still stands as the target:)
  settings.py          Typed, validated top-level Settings object (P1-2), pydantic-settings.
  risk.py               RISK_PER_TRADE, MAX_CONCURRENT_POSITIONS, DRAWDOWN_LIMIT, the new
                      aggregate-exposure cap (P0-4).
  execution.py           Order types, fee/slippage assumptions (including reconciling P0-11's
                      paper/live fee-model divergence explicitly here), exit strategy toggles.
  scoring.py             WEIGHT_* constants, thresholds.
  logging.py             Log toggles, summary/heartbeat intervals.
  simulator.py           Simulator-internal tunables.
```

`Engine` itself, post-refactor, should be a thin composition object: construct the pieces
above via `factory.py::build_engine`, wire them together via constructor injection, expose
`start()`/`stop()`. If `Engine` still has business logic of its own after this split, that
logic hasn't found its module yet.

---

## 5. The Looping Development Process

### Phase −1 — Unblock (run once, before Phase 0, new this round)

1. Fix P-1-1, P-1-2, P-1-3 (§2) — each its own commit, each independently verified per its
   own Verify step.
2. `view config/` and record its contents in `PROGRESS.md` (P1-7).
3. Locate and read `AGENTS-old_2.md`; reconcile per §0.3 (P3-5).
4. Confirm `python3 -c "import main, backtest, compare"` succeeds with no exceptions.

### Phase 0 — Baseline (run once, after Phase −1, before any further code changes)

Same six steps as Round 1's `AGENTS-old.md` §4, with two amendments:

1. Confirm `.env` is gitignored; scan history for committed secrets.
2. Regenerate `docs/map.json` via `tools/generate_map.py`; diff against the current one —
   given this round found map.json's *file list* still accurate wherever checked, this may be
   a clean diff, but confirm rather than assume, and specifically confirm it now also reflects
   whatever's inside `config/`.
3. Run every existing `tools/test_*.py` and `tools/verify_*.py` script as-is (**for real, this
   time** — see Principle §10) and capture verbatim pass/fail output into a **freshly
   regenerated** `BASELINE.md`. Do not carry forward any existing `BASELINE.md` content you
   haven't personally reproduced this session — per §0.1, the existing one doesn't match
   current code.
4. Attempt a bounded paper-mode smoke run (P3-3/P3-4) and capture the **real** final stats
   block.
5. Confirm `pytest`/`tests/` setup — if `tools/test_remediation.py` genuinely exists and
   passes, keep it; if it doesn't exist or doesn't pass, that's itself evidence for
   `PROGRESS.md` about what actually happened between rounds.
6. Reset `PROGRESS.md`'s "Summary & Current Status" block at the top to reflect Phase −1 and
   the fresh Phase 0 results, keeping all prior entries below it intact (append-only).

### Phase 1 — The Work Loop (repeat until §3's backlog is empty or explicitly deferred)

Identical process to `AGENTS-old.md` §4 Phase 1 (steps a–j) — re-verify against current code
first (line numbers have moved at least twice now), write the test first, smallest change,
run new+existing+smoke tests, self-review against §1, log to `PROGRESS.md` **with real
output pasted in**, commit referencing the item ID, re-scan for newly-revealed issues, repeat.

### Phase 2 — Consolidation Pass (after P-1/P0–P3 in §3 are clear)

Same as Round 1's Phase 2: close the coverage gap disclosed in §0.2 (this round's list is
longer than Round 1's was — start with the money-math files Round 1 already flagged as likely
containing real assertions worth preserving: `tools/verify_pnl_calculations*.py`,
`tools/test_order_pnl_reconciliation.py`, `tools/verify_rrr.py`), re-run header/map
consistency checks, produce a human-facing summary organized by tier, and a fresh prioritized
backlog for Round 4.

---

## 6. Verification & Testing Standards

Unchanged from `AGENTS-old.md` §5, plus:

- **A test or verification run that isn't reproduced this session doesn't count.** This is
  Principle §10 restated as a testing standard specifically because §0.1 shows what happens
  otherwise.
- The paper-mode smoke test and a real `backtest.py` run are now **both** required after any
  change touching the trading/scoring/risk path (not smoke-test alone) — `backtest.py` is
  cheap to run for a short date range and exercises a materially different code path
  (`Engine(mode="paper", ...)` constructed fresh per asset, full historical replay) than the
  live-feed paper smoke test does.

---

## 7. Definition of Done (per pass)

Unchanged from `AGENTS-old.md` §6, plus:

- Every item in §2 (Immediate Blockers) is fixed and independently re-run-verified, not just
  marked fixed.
- `config/`'s contents and purpose are documented in `PROGRESS.md`, whether or not they were
  acted on this pass.
- `AGENTS-old_2.md` has been read and reconciled (§0.3/P3-5) — its status noted explicitly.
- `BASELINE.md` reflects an actually-reproduced run from this session, dated accordingly.

---

## 8. Progress Tracking & Handback Format

Same format as `AGENTS-old.md` §7:

```
## [item ID] short title
Date:
Files touched:
What changed:
Why:
Behavior change? (explicit yes/no + description if yes, per Principle 1.3)
How verified:
Follow-ups spawned:
```

**One addition:** "How verified" must include either pasted real command output or a specific
file/line reference to where that output now lives (e.g. "see `BASELINE.md`, regenerated this
session, section X") — a sentence describing what verification *would* show is not sufficient,
per Principle §10.

Close every session, regardless of stopping reason, with an updated "Summary & Current
Status" block at the top of `PROGRESS.md`: current tier, what's left, and any item that turned
out to need a human decision. Given this round's core finding is that this exact step
appears to have been skipped for at least one full round already, treat writing this closing
summary as the very last thing you do before your context runs out — not something to get to
"if there's time."

---

## 9. Open Questions for the Human (Repo Owner)

Genuinely open items — proceed on the stated defaults below without blocking the loop on
them, but don't treat the defaults as final:

1. **Is there an existing branch or PR with Round 1/2's partial work** (the `model=`/
   `config_overrides=` edits in `backtest.py`, whatever's in `config/`, whatever produced
   `BASELINE.md`'s "39 passed" / `test_remediation.py` claim)? If one exists, Round 3 should
   almost certainly start from it rather than from `development` HEAD plus this document's
   patches — please point the coding agent at it directly if it exists somewhere this
   environment's tooling can't discover on its own (this round's tooling could not browse
   branches or PR history).
2. **P0-11's paper/live fee-model divergence** — is the live/demo `R0-2` comment's premise
   (Bitget TP/SL always execute at taker) actually correct for how this bot posts them? If so,
   confirm mirroring it into paper mode is the right call even though it will make paper
   backtests look somewhat less profitable than they currently do.
3. Round 1's Round-1-§8 defaults (10% aggregate exposure cap, `MAX_CONCURRENT_POSITIONS` → 15,
   `pydantic-settings` for P1-2, remove `asset_conf`, mode-aware DB path, mark-not-relocate for
   placeholder exchanges) — all still un-implemented, all still stand as the default absent
   further input, per Round 1's own framing. Re-confirming here rather than re-asking.
4. **Given `config/` already exists** — was a settings-package migration already
   commissioned/attempted deliberately (worth finishing exactly as started), or is it
   incidental/unrelated to this effort? This materially changes how Round 3 should approach
   P1-2/P1-7.

---

## 10. Round 3 Findings — Consolidated Evidence Appendix

This section exists so a future round (or a human skimming just this appendix) doesn't have
to re-derive the reasoning behind §0.1's headline claim. All four numbered points there are
independently reproducible by reading, in this order: `PROGRESS.md` (stalls at Phase 0),
`main.py::load_strategy`'s signature vs. `backtest.py::StrategyWrapper._load_strategy`'s call
of it (P-1-1), `engine/core.py::Engine.__init__`'s signature vs. `backtest.py::run_backtest`'s
call of it (P-1-2), `engine/core.py`/`main.py`/`engine/entry.py`/`tools/logger.py` for the
absence of any `scalper.engine.loop` logger vs. `BASELINE.md`'s captured line referencing
exactly that name. Nothing in this appendix requires trusting this document — every claim
names the exact file and, in most cases, the exact code fragment needed to check it yourself
in under a minute.

---

## 11. Forward Note — Tauri/IDE UI Porting Readiness

Out of scope for active work this round (per P4's deferral), but worth keeping in view while
you do the P1 decomposition, since the stated end goal is porting this into a heavily
customized open-source terminal/IDE Tauri app for a proper UI while keeping codebase/terminal
access:

- **P4-1's "stable read/event facade"** is the single highest-leverage piece of prep you can
  do now without violating the deferral: as `reporting.py`/`reconciliation.py`/`positions.py`
  take shape in the P1 split, give them clean, dependency-injected, **synchronous,
  serializable-state-returning** interfaces (e.g. a `PositionLedger.snapshot() -> dict`
  method) even though nothing consumes them as an API yet. That's a free option on the future
  UI work and costs nothing extra today if you're building these modules with narrow
  interfaces anyway, per the core mandate.
- **Keep `main.py`/`backtest.py`/`compare.py` genuinely thin (P4-2)** — a Tauri app driving
  this via its embedded terminal will be shelling out to these same entry points (or a future
  thin read-only API per P4-1); every bit of business logic that leaks into entry-point
  argument-parsing code today is logic that has to be duplicated or awkwardly reached into
  later.
- Do not start building the actual facade/API surface, and do not let this section pull any
  P1 module design toward speculative "future UI" requirements at the expense of getting the
  core trading-decision path correct and modular first — that's still the explicit, stated
  priority, and P4 remains deferred until P-1 through P3 are clear.
