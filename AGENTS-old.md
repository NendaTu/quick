# AGENTS.md — Remediation & Modularization Directives for `quick`

## 0. Read This First

This file is the operating manual and prioritized backlog for coding-agent work on this
repository. It was produced by a human-directed static audit of the `development` branch
(repo map: `docs/map.json`) on 2026-07-27. Treat every finding below as a **well-evidenced
hypothesis to re-verify against current code**, not as ground truth to apply blindly — file
contents may have moved since this was written, and you have something the audit didn't:
full read/write/execute access to the live repo, a shell, and the ability to actually run
the code.

**Coverage disclosure — read before trusting silence on any file.** The audit deep-read and
cross-referenced 11 files end-to-end: `config.py`, `main.py`, `engine/base.py`,
`engine/core.py`, `engine/entry.py`, `strategies/base_strategy.py`,
`strategies/scalper.1.jules.py`, `ta/scoring.py`, `compare.py`, `database.py`, `models.py`.
Everything else — all 15 `ta/patterns/*.py` files, all 9 `ta/indicators/*.py` files, the 3
`ta/candles/*.py` files, `orderbook.py`, `simulator.py`, `engine/simulation.py`,
`bitget_client.py`, `engine/exchanges/bitget.py`, the 9 placeholder exchange drivers,
`backtest.py`, and ~20 files under `tools/` — was **not** individually line-read. It was
reasoned about only via filenames/docstrings in `docs/map.json` and incidental references
from the files that were read. Do not assume it's clean; assume it hasn't been checked yet,
and apply the same rigor there that produced the findings below. Part of Phase 2 (§4) is
explicitly closing this gap.

This document has two jobs:
1. A **priority backlog** (§2) of specific, evidence-backed issues, plus the architecture
   direction the user has mandated.
2. A **process** (§4) for working through that backlog — and everything you find beyond
   it — safely, verifiably, and in a loop, without a human re-prompting at every step.

This is expected to be the first of several rounds. Treat this backlog as living and
append-only across rounds: mark items done, don't delete them, and add newly-discovered
items with the same ID scheme (see §2 numbering) so a future audit round can pick up the
thread.

> **Round 1 update (2026-07-28):** initial clarifying questions on several P0–P2 items
> have been answered in §8, and the specific bullets below have been updated in place to
> reflect those decisions. Where §8 and an earlier section could be read as disagreeing,
> §8 is authoritative — it's this document's latest revision, not a separate opinion.

---

## 1. Non-Negotiable Operating Principles

These apply to every loop iteration, no exceptions:

1. **This code can place real orders with real money.** `MODE=live` and `MODE=demo` both
   connect to a real exchange (`engine/exchanges/bitget.py`). Every automated test, smoke
   run, or verification you perform must run with `MODE=paper` or against a
   stubbed/mocked exchange client. Never invoke `demo` or `live` mode, and never add
   automation that could. If a task genuinely requires live/demo verification, stop and
   ask the human — do not proceed on your own judgment.
2. **Never surface secrets.** Treat `.env` and any `BITGET_*_KEY`, `*_SECRET`,
   `*_PASSPHRASE` value as sensitive — never log, print, commit, or paste them, including
   in commit messages, test fixtures, or progress reports. Confirm `.env` is gitignored as
   an early Phase 0 check.
3. **No silent behavior changes to money-moving logic.** If a change alters what trades
   get taken, position sizing, stop/target placement, or fee/PnL math, call it out
   explicitly — in the commit message and in the progress log (§6) — with a one-line
   "before → after" behavior statement. Never bundle a behavior change inside a commit
   labeled as a pure refactor.
4. **Every change is independently verifiable.** If nothing in the repo can currently
   prove a change is correct, write that proof (a test, a verification script, a
   smoke-run assertion) before or alongside the change. Reading the diff and feeling
   confident is not verification.
5. **Small, reversible increments.** One backlog item (or one clearly-scoped sub-item)
   per commit. The tree should build/import cleanly at every commit.
6. **When intent is ambiguous, don't guess silently.** Some things in this codebase are
   deliberate judgment calls, not bugs — e.g. `database.py`'s own inline comment on the
   `has_data_gaps` tolerance window says as much explicitly. When you can't tell which one
   you're looking at, document both readings, propose a default, flag it in §6, and move
   on rather than silently picking one and hoping it was right.
7. **Preserve the existing decision trail.** You'll see inline tags like `[TECH-001]`,
   `[ARCH-003]`, `[REPAIR-20260708]`, `[CS-004]`, `[C-004]` scattered through the code — a
   lightweight, ad hoc decision log that predates this document. Consolidate and index
   them (P2 area) but don't delete the history they represent.
8. **Work on a branch**, e.g. `agent/foundation-hardening`, never directly on
   `development`/`main`. No force-push, no history rewriting.
9. **"Microservice-esque" means discipline, not deployment topology.** The mandate is
   single-concern modules with narrow, explicit interfaces, dependency injection, and
   independent testability — all still inside **one deployable process**. Do not introduce
   network calls, message queues, or IPC into the hot trading-decision path to satisfy
   this. The one place a real process boundary may eventually make sense is a future
   read-only UI-facing API (P4-1) — and that is explicitly deferred, not part of this pass.
   If you find yourself drawing a line between two modules that would require a network
   hop in the trading loop, that's a sign to redraw the line, not to add the hop.

---

## 2. Priority Backlog

Work top-to-bottom within each tier; tiers are strict (finish all of P0 before starting
P1, etc.) unless a P1+ item is trivially bundled with the P0 item you're already touching
in the same file. Each item has an ID (`Txx-n`) — reference it in commits and in the
progress log.

### P0 — Correctness & Risk

Fix or conclusively resolve these first. Wrong behavior here loses money or corrupts
state, silently.

#### P0-1 — Config overrides don't reach the components that gate trading decisions
**Where:** `main.py::main()`, `engine/core.py::Engine.__init__`,
`strategies/base_strategy.py::JBaseStrategy.__init__`, `ta/scoring.py::ScoringEngine.evaluate`

**Evidence:** `main.py` constructs `Engine(mode=args.mode)` — which snapshots the live
`config` module into an immutable `ConfigContext` instance (`self.config`) — *before* it
calls `load_strategy(..., overrides=overrides)`. Strategy construction
(`JBaseStrategy.__init__`) applies CLI-supplied `KEY=VALUE` overrides via
`setattr(config, key, value)` directly on the `config` **module**, not on `self.config`.
Since the `ConfigContext` snapshot already happened, the override can never reach it.
`ScoringEngine.evaluate()` — the entry-scoring gate — is always called with
`config_context=self.config` (the stale snapshot), so weight/threshold overrides passed on
the command line have zero effect on actual trade-entry decisions, even though
`JBaseStrategy.get_config()` (which reads the bare module) *does* see them — so a strategy
checking its own override via `get_config()` will believe the override took effect system-wide.
Contrast with `compare.py::variant_runner`, which applies overrides to the module *before*
constructing `Engine` — same underlying mechanism, correct ordering, working as intended.
Two independent override pathways exist with different, undocumented ordering
requirements, and only one of them is reliable.

**Fix:** Pick one mechanism. Recommended: overrides should be applied to a config object
*before* any component that reads config is constructed, full stop — thread `overrides`
into `Engine.__init__` itself (or a factory function `build_engine(mode, overrides)`) so it
applies them to the `ConfigContext` object before anything downstream reads it, and stop
having `JBaseStrategy` mutate the shared module at all (mutating shared global state from
inside a strategy constructor is itself an architecture smell — see P1-2/P1-6).

**Verify:** New test — construct an engine with an `ENTRY_SCORE_THRESHOLD` override via the
same code path `main.py` uses, feed `ScoringEngine.evaluate()` a fixture that would pass
the default threshold but fail the overridden one, assert it's rejected.

---

#### P0-2 — Online-learning split-brain: the model that trains isn't the model that decides
**Where:** `engine/core.py` (trading loop's `train_on_tick` call and `_report_exit`'s
`train_on_trade` call — both operate on `self.model`), `strategies/scalper.1.jules.py::
ScalperStrategy.__init__` (`self.model = LearningModel(simulator)`), `models.py::LearningModel`

**Evidence:** `Engine.__init__` creates its own `LearningModel` (paper mode) as
`self.model`, and it's the *only* object that ever receives `train_on_tick`/`train_on_trade`
calls. But whenever any strategy is loaded (the normal path — `main.py` defaults to
`scalper.1.jules`), `Engine._trading_loop` gets entry signals via
`strat.get_entry_signal(...)`, not `self.model.predict(...)` — so `Engine.model.predict()`
is dead code in the default configuration. `ScalperStrategy` constructs its *own*, separate
`LearningModel(simulator)` instance, and that's the one whose `.predict()` actually
produces trade signals. Both instances load starting weights from the same DB table
(`model_weights`) at construction time via `_load_shared_weights()`, but only
`train_on_trade` calls `_save_shared_weights()` — `train_on_tick` updates stay in-memory
only. So within a single session: tick-level learning on `Engine.model` never reaches the
strategy's decision-making model at all, and trade-close learning only reaches it via a DB
round-trip that the already-running strategy instance never re-reads.

**Fix — decided (Round 1):** Exactly one `LearningModel` instance per running session,
created by `Engine` and passed into strategy construction via explicit constructor
injection (`obj(simulator=simulator, model=engine.model, config_overrides=overrides)`),
mirroring how P0-7 has the base class own `self.simulator`. Rejected: routing through
`self.simulator.engine.model` — that requires the exchange/simulator layer to hold a
back-reference to the `Engine` that owns it, a layering inversion that creates a circular
object graph (`Engine → exchange`, `exchange → Engine`) and works against every other P1
goal. Don't build support for a strategy-private, unshared model speculatively — there's no
concrete use case for it in this codebase today; add it later as an explicit, clearly-named
opt-in only if a genuine multi-model research scenario shows up.

**Verify:** Unit test that calls `train_on_trade` with a strongly-signed synthetic result on
the model instance a strategy actually uses for `predict()`, then confirms the next
`predict()` call reflects the updated weight.

---

#### P0-3 — Possible duplicate-entry exposure when multiple strategies signal the same symbol/side in one tick
**Where:** `engine/core.py::Engine._asset_is_tradable`, `Engine._trading_loop`

**Evidence:** `_asset_is_tradable`'s pending-entry guard
(`pos_key in self.pending_entries`) is explicitly bypassed whenever a `signal` object is
passed (`and signal is None`) — which it always is, from the trading loop. `pos_key` gets
added to `pending_entries` partway through signal processing, but two different strategies
producing a same-symbol/same-side signal inside the same iteration of the strategy loop
don't appear to be deduplicated against each other before both could reach
`self.router.route_signal(...)`. Also note `_asset_is_tradable` is called **twice** with
identical arguments for the same signal (once before the entry math, once again right
after) — investigate whether that second call was meant to catch exactly this race and
simply doesn't, given the `signal is None` bypass.

**Status:** This needs a concrete trace/repro, not just static reading, before you know
whether it's live. Treat it as P0 until disproven, given the financial stakes.

**Fix — decided (Round 1):** Reserve `pos_key` atomically the moment the *first* signal for
it is accepted in a given loop pass; skip any subsequent signal for the same `pos_key` in
the same pass (first-accepted-wins). Treat this as a simple, deterministic starting policy,
not a final one — log every skip (symbol, both competing strategy IDs, timestamp) so
there's real data on how often collisions actually happen. If they turn out to be common,
that data justifies upgrading to score-based arbitration (compare `ScoringEngine` composite
scores instead of relying on list order) as a well-motivated follow-up rather than
speculative complexity now. Before deleting the second, redundant `_asset_is_tradable` call:
check `git blame` for why it was added — if no distinct purpose surfaces in history, remove
it once the atomic reservation sits immediately after the first check, since that
reservation is what the second call appears to have been informally (and unsuccessfully)
trying to approximate.

**Verify:** Regression test simulating two concurrent strategies both emitting a signal for
the same symbol+side within one `_trading_loop` iteration; assert exactly one order is
routed and one skip is logged. Also add a test asserting the double `_asset_is_tradable`
call is either removed as redundant or given a documented, distinct purpose.

---

#### P0-4 — No aggregate exposure cap; `MAX_CONCURRENT_POSITIONS` defaults to a number that isn't really a cap
**Where:** `config.py` (`MAX_CONCURRENT_POSITIONS = 1000`, `RISK_PER_TRADE = 0.01`),
`engine/core.py::Engine._trading_loop` / `_asset_is_tradable`

**Evidence:** The only structural brake on simultaneous exposure is a raw *position count*
(default 1000) and pairwise correlation blocking (only for symbol pairs with a recorded
correlation above 0.9, and only when that data is populated — confirm it's populated in
every mode, including paper/backtest). There is no cap expressed in terms of aggregate
risk-at-once (e.g. sum of `qty * entry / leverage` across open positions, or sum of
per-trade risk fractions).

**Fix — decided (Round 1):** Add an explicit aggregate-exposure gate (total open margin as
a fraction of equity) as a first-class, config-driven check in the tradability gate,
independent of the raw position-count cap. **Default the cap to 10% of equity** —
systematic strategies commonly run aggregate risk-at-once somewhere in the 5–20% range,
tightening toward the low end when positions are likely correlated, which a 250-asset
crypto universe often is during broad moves regardless of what a lagged pairwise
correlation table says. **Default `MAX_CONCURRENT_POSITIONS` to 15** — comfortably above the
~10 full-risk positions the 10%/1%-per-trade math implies, leaving room for
smaller-than-standard entries, and nowhere near the effectively-unlimited 1000 it is today.
Both are starting engineering defaults, not fixed judgments — they're config values the
human should retune once real paper-trading data shows how often the aggregate cap binds.
Flag this change explicitly per Principle §1.3, since it changes trading behavior.

**Verify:** Test that constructs enough uncorrelated synthetic signals to exceed a
configured aggregate-risk limit and asserts later ones are rejected once the limit is hit,
independent of position count.

---

#### P0-5 — Live/demo execution hardcodes "limit" orders regardless of `ENTRY_ORDER_TYPE`
**Where:** `engine/entry.py::SignalRouter.route_signal`

**Evidence:** The live/demo branch calls
`self.exchange.place_order(symbol, side, "limit", qty, price, **kwargs)` — the order-type
string is hardcoded, not read from `config.ENTRY_ORDER_TYPE` (documented in `config.py` as
togglable between `"limit"` and `"market"`). Changing that setting has no effect on
live/demo execution. Confirm whether `TP_ORDER_TYPE`/`SL_ORDER_TYPE` are correctly wired
wherever exits are placed — this file only shows the entry path.

**Fix:** Read the configured order type from `self.config` (or whatever config object this
class ends up depending on post-P1-6) instead of hardcoding it.

**Verify:** Test that sets `ENTRY_ORDER_TYPE="market"`, calls `route_signal` against a mock
exchange in live/demo mode, and asserts `place_order` was called with `"market"`.

---

#### P0-6 — Strategy state can silently change type between DB-backed and in-memory runs
**Where:** `strategies/base_strategy.py::JBaseStrategy.save_state` / `get_state`

**Evidence:** `save_state` always stores `str(value)` in the in-memory fallback dict.
`get_state`'s `ast.literal_eval` deserialization is only applied on the DB-backed branch;
the in-memory-fallback branch returns the raw string as-is. A strategy that `save_state`s a
dict/list and later `get_state`s it back gets a real object when a DB is attached, and a
string repr of that object when it isn't — a silent type change depending on which mode the
bot happens to be running in.

**Fix:** Apply the same deserialization attempt on both paths, or simpler: store real
objects (not stringified ones) in the in-memory dict, since there's no serialization need
for an in-process fallback.

**Verify:** Unit test: `save_state("k", {"a": 1})` then `get_state("k")` with no
simulator/db attached; assert it returns the dict, not the string `"{'a': 1}"`.

---

#### P0-7 — Strategy↔simulator wiring is an unenforced, silently-failing contract
**Where:** `engine/base.py::BaseStrategy.__init__`, `strategies/base_strategy.py::
JBaseStrategy.__init__`, `strategies/scalper.1.jules.py::ScalperStrategy.__init__`,
`main.py::load_strategy`

**Evidence:** `main.py` instantiates every discovered strategy class as
`obj(simulator=simulator, config_overrides=overrides)`, but neither `BaseStrategy` nor
`JBaseStrategy` declares or stores a `simulator` parameter — each concrete strategy is
implicitly responsible for accepting it and setting `self.simulator` itself. Confirmed:
`ScalperStrategy.__init__` accepts `simulator` but never stores it. `JBaseStrategy._get_ohlcv`
silently returns `[]` when `self.simulator` isn't set, and `is_ready()` silently returns
`True` when a strategy has no `required_history` attribute — so a strategy that *does*
define `required_history` but forgets to store `self.simulator` would sit in "warming up"
forever with no error raised anywhere. `ScalperStrategy` happens not to trigger this today
only because it doesn't set `required_history`.

**Fix:** Move `simulator` into the shared base-class constructor contract so every strategy
gets it for free and can't forget it. Make the "no simulator + history required" case raise
loudly instead of degrading to an empty list.

**Verify:** Test instantiating a minimal strategy subclass with a `required_history`
requirement and no simulator wired; assert a clear, immediate error rather than a silent,
permanent "not ready."

---

### P1 — Architecture & Single-Concern Modularity

These are the structural items behind the "single-concern, microservice-esque" mandate.
See §3 for the proposed target layout these feed into.

#### P1-1 — `engine/core.py::Engine` is a god object
One class currently owns: config bootstrap, exchange selection, position bookkeeping,
equity/risk limit monitoring, asset regime classification, the tradability gate, trade
stats/reporting, the trading loop itself, TTL exit management, heartbeat/summary logging,
and exchange-state reconciliation (`_sync_exchange_state`, a long, deeply-nested method
that reconciles live exchange state against internal bookkeeping and deserves particular
care — get this one under test before refactoring it, given how much financial correctness
rides on it). See §3 for the proposed split.

#### P1-2 — `config.py` is one flat, ungoverned global namespace spanning 8+ concerns
Environment/credentials, account risk limits, asset universe, timeframes, execution/order
types, strategy toggles, scoring weights, logging, and simulator internals are all
module-level constants in one file. `ConfigContext.__init__` copies `globals()` into
instance attributes, manually excluding known non-config names (`os`, `datetime`, `pytz`,
`load_dotenv`, `get_env_stripped`) — any future import or helper function added to
`config.py` that isn't itself a `type` will silently leak into every `ConfigContext`
instance as a spurious attribute unless someone remembers to extend that exclusion list.
Replace both the flat namespace and the reflection-based `ConfigContext` with a typed,
validated settings model. **Decided (Round 1): `pydantic-settings`, not plain
dataclasses** — the diagnosed problems (P2-4/P2-5: keys silently missing or drifted, no
validation, hand-rolled env-loading via `get_env_stripped`) are validation and env-loading
problems specifically, and dataclasses alone would just rebuild the same manual plumbing
under a different name. Pydantic-settings gets typed env-loading, constraint validation
(e.g. weights bounded to `[0, 1]`), and fail-fast startup errors for free. Structure it as
nested settings groups matching the risk/execution/scoring/logging/simulator split above,
composed under one top-level `Settings` object. Check `requirements.txt` for whether
pydantic is already a dependency before treating this as fully settled. See §3.

#### P1-3 — Implicit `hasattr`/`getattr` duck-typing substitutes for real interfaces
`Engine` alone defensively probes for `asset_correlations`, `recalculate_correlations`,
`ready_assets`, `books`, `is_ready`, `params`, `db`, `symbol_map`/`rev_symbol_map`, and more
— none of which are part of the `BaseExchange`/`BaseStrategy` ABC contracts in
`engine/base.py`, yet calling code depends on them everywhere via defensive checks. Audit
every `hasattr`/hardcoded-default `getattr` call site against `Engine`, `SignalRouter`, and
the strategy base classes, and formalize the real ones into the ABCs — or, where a
capability is genuinely optional (not every exchange needs `recalculate_correlations`,
say), model it as an explicit `typing.Protocol` capability check instead of an inline
`hasattr`.

#### P1-4 — `Signal` is a loosely-typed dict threaded through four layers with manual key-popping
`Engine` builds it, `ScoringEngine` reads from it, `Strategy` returns/enriches it,
`SignalRouter` strips specific keys by name (`kwargs.pop(key, None)` loops in
`engine/entry.py`) before forwarding the rest positionally into exchange methods. Any new
field added anywhere in this chain risks silently colliding with a downstream method's
parameter name. Replace with a typed `Signal`/`OrderRequest` dataclass with an explicit,
named mapping to each exchange method's parameters — a collision becomes a type error
instead of a runtime surprise.

#### P1-5 — `SignalRouter._init_exchange()` is a dead, duplicate exchange-selection path
`Engine` always passes its own already-constructed `exchange` into `SignalRouter(...)`, so
`_init_exchange()`'s independent mode→exchange selection logic never runs in the current
call graph — and it's already drifted from `Engine.__init__`'s version (it doesn't pass
`config_context`, doesn't set an `.engine` back-reference). Either delete it, or make
`SignalRouter` genuinely usable standalone and single-source the wiring logic so the two
can't drift further.

#### P1-6 — Two independent config-override mechanisms coexist with incompatible ordering requirements
This is P0-1's root cause, listed again here because the fix is fundamentally an ownership
decision (one component applies overrides, used identically by every entry point —
`main.py`, `compare.py`, any future entry point), not a local patch. Resolve P0-1 and P1-2
together.

---

### P2 — Consistency, Duplication & Hygiene

| ID | Where | Issue | Action |
|----|-------|-------|--------|
| P2-1 | `config.py` (`TF_SECONDS`), `strategies/base_strategy.py::get_readiness_eta`, `compare.py::DataCoordinator.warm_up`, `engine/core.py`'s TTL parsing | The timeframe→seconds mapping is hand-duplicated in at least four places with three different literal spellings of the same dict. | Consolidate to one import of `config.TF_SECONDS` everywhere; delete the local copies. |
| P2-2 | `engine/core.py::Engine.start()` vs `compare.py::DataCoordinator.warm_up()` | Near-identical asset-discovery/filtering logic (sort by volume, filter stablecoins, filter `ASSET_OMITTED`, take top N) is duplicated between the two files. | Extract a single `discover_assets(tickers, omitted, count)` function both call. |
| P2-3 | `ta/scoring.py::ScoringEngine.evaluate` | `raw_scores["asset_conf"]` is a direct copy of `raw_scores["trend_15m"]`; `WEIGHT_ASSET_CONF` is permanently `0.0` specifically to avoid double-counting. The dimension is dead but still allocated, computed, and iterated every evaluation. | **Decided (Round 1), default absent further human input: remove it now.** Original intent is genuinely the human's call and isn't recoverable from the code alone; a dead, zero-weighted, exact-duplicate dimension costs real cycles every evaluation for no effect, and a distinct calculation is cheap to reintroduce later if intent surfaces. Document the removal clearly in `PROGRESS.md` so it's easy to revisit. |
| P2-4 | `ta/scoring.py` (`MIN_VOLATILITY`, `VOL_PCT_MIN`), `database.py` (tick/candle retention periods) | Config keys are referenced via `getattr(..., default)` in code but are absent from `config.py` entirely — real tunables hidden as magic defaults in unrelated files instead of being centralized where `config.py`'s own docstring says they should live. | Audit every `getattr(config_context, KEY, default)` / hardcoded-default call across the repo; promote genuinely-tunable ones into `config.py` (or its P1-2 successor). |
| P2-5 | `ta/scoring.py`'s `getattr(..., fallback)` calls | Several fallback defaults don't match `config.py`'s actual configured values (e.g. `ENTRY_SCORE_THRESHOLD` fallback `30.0` vs. configured `15.0`; `BY_DEFAULT_REPORT_ONLY` fallback `True` vs. configured `False`). Currently harmless only because `ConfigContext` always carries the real value — but misleading, and a landmine if that assumption ever changes. | Remove the stale fallback literals or make them match; add a test asserting no drift. |
| P2-6 | `main.py`, `strategies/base_strategy.py`, `compare.py` (multiple sites) | Systemic bare/broad `except:` clauses swallow everything, including `KeyboardInterrupt`/`SystemExit`. | Narrow to specific exception types; at minimum `except Exception:` with logging. |
| P2-7 | `main.py` startup log | `RISK_PER_TRADE` (a loss-risk sizing parameter) is logged as "Target net profit per trade" — conflates two different concepts in the one place a human actually reads at startup. | Fix the label. |
| P2-8 | `main.py` | `log = logging.getLogger("scalper")` is hardcoded regardless of which strategy or mode is actually running. | Derive the logger name from the loaded strategy/mode. |
| P2-9 | `main.py::load_strategy` fuzzy-match fallback | Only scans the top level of `strategies/` via `os.listdir` (non-recursive), so partial-name resolution silently can't find strategies under `strategies/built/`, `strategies/sweeps/killzone/`, or `strategies/sweeps/range/`. | Make the fuzzy-match fallback recursive (`os.walk`), matching the directory-based loader's existing behavior. |
| P2-10 | `engine/entry.py::SignalRouter.route_signal` | Stale scaffolding comment ("In a real implementation, this would call...") sits above code that *is* the real implementation. | Delete/update the comment; audit for similar leftover scaffolding language elsewhere. |
| P2-11 | `database.py::Database.__init__` | `market_data.db` path is hardcoded relative to `database.py`'s own file location and identical across every mode and script — `main.py` (paper/demo/live), `backtest.py`, and `compare.py`'s `DataCoordinator` all share one physical file, differentiated only by `session_id`/`strategy_id` foreign keys. | **Decided (Round 1):** yes, mode-aware — `config.DB_PATH` defaulting to `data/market_data_{mode}.db`, so live history can't accidentally commingle with backtest/paper experimentation. For `compare.py::DataCoordinator`'s warm-up cache specifically, which is already transient by design (created and torn down within one method call), consider an in-memory SQLite connection instead of a file at all — that sidesteps multi-process file-lock contention for that path entirely rather than just relocating it. |
| P2-12 | `database.py` | Mixed write paths: `save_tick`/`save_candle`/`save_log`/`save_signal`/`save_trade`/`mark_exhausted` go through the queued, batched writer thread; `save_weight`/`save_strategy_state`/`save_discovered_assets` write directly and synchronously via the lazily-created `connection` property. No `check_same_thread=False` anywhere, so there's an implicit, unenforced "only touch `.connection` from one thread" assumption. | Document the threading contract explicitly, or unify all writes through the queue/worker pattern already used for the high-volume ones (it's well-built — see the note under P3). |
| P2-13 | `compare.py::parse_args` | Mixes `argparse.parse_known_args()` with a separate raw `sys.argv` scan for `"=" in arg` that doesn't exclude args argparse already claimed — an equals-style flag like `--strategy-a=foo` could be double-counted as a config override with key `"--strategy-a"`. | Scan only `remaining` (argparse's leftover args), not the full `sys.argv`. |
| P2-14 | `models.py::LearningModel.predict` | Calls `ScoringEngine.evaluate()` twice per prediction (once `side="buy"`, once `side="sell"`), fully recomputing every side-independent raw score both times. | Compute side-independent scores once, apply the sign/`filter_multiplier` flip for each side afterward. Minor cost today; scales with asset count and tick rate. |
| P2-15 | `engine/exchanges/` | 9 of 10 exchange drivers (bingx, bitunix, blofin, coinex, dydx, hyperliquid, kucoin, margex, mexc) are placeholders against one production driver (bitget). | Roadmap-vs-prune is genuinely the human's product call, not the agent's — confirm before acting unilaterally. **Default (Round 1) absent further input:** don't physically relocate the files — that risks breaking anything that discovers exchange drivers by directory listing, the same way `main.py` discovers strategies. Instead mark stub status unambiguously using tooling this repo already has for exactly this (`tools/add_headers_auto.py` / `tools/verify_headers.py`) with a `STATUS: placeholder, not implemented` header, so it's machine-checkable rather than something a future reader has to infer from an empty method body. |

---

### P3 — Testing & Verification Infrastructure

#### P3-1 — No conventional automated test suite
No `tests/` directory or pytest/CI config was found among the mapped files. Instead there
are ad hoc `tools/verify_*.py` and `tools/test_*.py` scripts, including superseded-but-still-
present versions: `verify_pnl_calculations.py` → `verify_pnl_calculations_v2.py` →
`verify_pnl_calculations_v3.py`, and `analyze_data.py` → `analyze_data_v2.py`. Establish a
real `tests/` tree with `pytest`; migrate each verify_/test_ script's actual checks into
proper test functions without losing coverage (read them first — some, like
`test_order_pnl_reconciliation.py` and `verify_rrr.py`, sound like they already encode real
financial-correctness assertions worth preserving exactly, not just porting loosely).
Decide the fate of superseded v1/v2 versions (archive or delete) only once their coverage
is confirmed preserved in the new suite.

#### P3-2 — No CI workflow found
Add one (lint + test on push/PR) once Phase 0 baseline work makes the test suite meaningful.
Every CI test step must run in `MODE=paper` or with a mocked exchange — see Principle §1.1.

#### P3-3 — Establish a standing paper-mode smoke test
A bounded-duration or bounded-trade-count run of `Engine` in paper mode against
fixture/backtest data, asserting the process starts, runs, and produces a sane final stats
block without exceptions. This is the fast end-to-end sanity check the loop in §4 runs
after any change touching the trading/scoring/risk path.

---

### P4 — Forward-Looking (explicitly deferred — do not let this block P0–P3)

#### P4-1 — Stable read/event facade for a future custom UI
Once the core is modularized, expose one read-oriented facade — state snapshots plus the
structured events already half-present in `database.py`'s `signals`/`trades` tables and the
logger — so a future terminal/IDE-based UI can observe the system without reaching into
`Engine` internals. This is naturally where a real process boundary (a small local
read-only API) could eventually make sense, per Principle §1.9 — but only after the core
itself is trustworthy.

#### P4-2 — Keep entry points as thin adapters over a reusable core
`main.py`, `backtest.py`, and `compare.py` should become thin CLI adapters over the
modularized core (§3), not each reimplementing their own slice of wiring logic (see P1-5,
P2-2 for two concrete examples of exactly this happening today). Do this as a natural
side effect of the P1 decomposition, not as separate work.

#### P4-3 — Placeholder exchange drivers
See P2-15. Listed again here because the actual decision (prune vs. roadmap) is a product
call for the human, not something to resolve unilaterally mid-refactor.

---

## 3. Proposed Target Module Layout

This is a starting proposal, not a rigid mandate — validate against actual coupling and
import cycles as you go, and adjust boundaries where the real dependency graph disagrees
with this sketch. The goal is single responsibility per module and dependency injection
over global state, not a specific file count.

```
engine/
  loop.py            TradingLoop: pure iteration + signal-generation orchestration.
                      Depends on the below via constructor injection; contains no
                      risk/reporting/reconciliation logic itself.
  positions.py        PositionLedger: open_positions / pending_entries bookkeeping only.
  risk.py              RiskGate: drawdown/ROI/trade-count/duration limits, aggregate
                      exposure cap (P0-4), tradability gate (correlation/liquidity/cooldown).
  reporting.py         TradeReporter / StatsAggregator: asset_stats, strategy_stats,
                      equity_history, entry/exit reporting, final-stats printing.
  regimes.py           RegimeClassifier: asset regime classification, isolated from the
                      tradability gate it currently lives beside in Engine.
  reconciliation.py    Everything currently in _sync_exchange_state. High financial-
                      correctness stakes — this module gets its own dedicated test file
                      before anything else in this list.
  factory.py           build_engine(mode, overrides, ...): the one place mode -> exchange
                      /model selection happens, replacing the duplicated logic currently
                      split between Engine.__init__ and SignalRouter._init_exchange (P1-5).
  signal.py            The typed Signal/OrderRequest dataclass from P1-4.

config/
  settings.py          Typed, validated top-level Settings object (P1-2).
  risk.py               Risk-limit group (RISK_PER_TRADE, MAX_CONCURRENT_POSITIONS,
                      DRAWDOWN_LIMIT, the new aggregate-exposure cap from P0-4, ...).
  execution.py           Order types, fee/slippage assumptions, exit strategy toggles.
  scoring.py             WEIGHT_* constants, thresholds — every key ta/scoring.py reads.
  logging.py             Log toggles, summary/heartbeat intervals.
  simulator.py           Simulator-internal tunables.
```

`Engine` itself, post-refactor, should be a thin composition object: construct the pieces
above, wire them together via constructor injection, expose `start()`/`stop()`. If `Engine`
still has business logic of its own after this split, that logic hasn't found its module
yet — keep pushing it out rather than accepting a smaller-but-still-mixed `Engine`.

---

## 4. The Looping Development Process

### Phase 0 — Baseline (run once, before any code changes)

1. Confirm `.env` is gitignored; confirm no secrets are already committed anywhere in
   history (a quick `git log -p | grep`-style pass for key-shaped strings is cheap
   insurance).
2. Regenerate the repo map (`tools/generate_map.py` already exists) and diff it against
   `docs/map.json` to catch drift since this document was written.
3. Run every existing `tools/test_*.py` and `tools/verify_*.py` script as-is; capture
   pass/fail and output verbatim into a new `BASELINE.md`. This is your regression floor —
   nothing in P0–P3 should make a currently-passing check start failing without an
   explicit, justified exception logged in the same file.
4. Attempt a bounded paper-mode smoke run (P3-3) and capture the final stats block as an
   additional baseline artifact.
5. Set up `pytest` and a `tests/` skeleton if absent. Wire up whatever CI is feasible in
   this environment (P3-2), gated to paper-mode-only test execution.
6. Create `PROGRESS.md` (or confirm it exists from a prior round) as the living, mutable
   companion to this file — see §6 for its format. This document (`AGENTS.md`) stays
   stable; `PROGRESS.md` is what you update every iteration.

### Phase 1 — The Work Loop (repeat until the backlog in §2 is empty or explicitly deferred)

For each iteration:

  a. Pick the single highest-priority open item from §2 (P0 before P1 before P2 before
     P3; top-to-bottom within a tier).
  b. Re-verify the finding against current code — line numbers and even function names
     may have moved. If it no longer applies, log why in `PROGRESS.md` and move on.
  c. Write a failing/characterizing test *first* that encodes either (i) the correct
     behavior a bug fix should produce, or (ii) the current externally-observable behavior
     a refactor must preserve.
  d. Make the smallest change that satisfies the test.
  e. Run: the new test, the full existing suite from Phase 0, and — for anything touching
     the trading/scoring/risk path — the paper-mode smoke run.
  f. Self-review the diff against §1: scope creep? an unlogged behavior change? new
     `hasattr` duck-typing introduced instead of removed? a new bare `except? a newly
     duplicated constant?
  g. Append an entry to `PROGRESS.md`: item ID, what changed, why, how it was verified, and
     any behavior change explicitly called out per Principle §1.3.
  h. Commit with a message referencing the item ID (e.g. `P0-1: fix config-override
     ordering in main.py`).
  i. Re-scan: did this change reveal new issues? Add them to §2 (or a `PROGRESS.md`
     addendum) with a priority tier before continuing.
  j. Return to (a).

### Phase 2 — Consolidation Pass (after P0–P3 in §2 are clear)

- Close the coverage gap disclosed in §0: read through the files this audit didn't —
  starting with `simulator.py`, `orderbook.py`, `engine/exchanges/bitget.py`,
  `bitget_client.py`, and the remaining strategy files, then the `ta/patterns/` and
  `ta/indicators/` modules, then `tools/`. Apply the same rigor (trace actual call graphs,
  don't just read docstrings) that produced §2. Add findings to a new dated section rather
  than folding them silently into §2, so the audit trail stays legible across rounds.
- Re-run `tools/verify_headers.py`-style consistency checks; regenerate
  `docs/map.json` (`tools/generate_map.py`) to reflect the new module layout from §3.
- Produce a short human-facing summary of everything changed, organized by the same
  priority tiers, plus a fresh prioritized backlog for anything intentionally deferred
  (P4 and beyond, plus whatever Phase 2 turned up).

---

## 5. Verification & Testing Standards

- Adopt `pytest`. Prefer plain functions + fixtures over heavier test-framework machinery
  unless the codebase already leans a different way once you've looked.
- Critical financial math (position sizing, fee/PnL calculations, TP/SL/breakeven
  placement) gets exact-value regression tests, not just smoke coverage — a wrong number
  here is a wrong number in someone's account.
- Every module extracted per §3 carries its own unit tests, written against its new
  narrow interface, independent of `Engine`.
- Consider `ruff` (lint) and `mypy`/`pyright` (gradual typing — a natural companion to
  formalizing the Protocol/ABC contracts in P1-3) if available in this environment; note
  in `PROGRESS.md` if they aren't and you're skipping them.
- The paper-mode smoke test (P3-3) is not optional scaffolding — it's the one check that
  exercises the real integration surface between modules, and it's what P0-3 in particular
  needs to be taken seriously.

---

## 6. Definition of Done (per pass)

A pass through this document is done when:
- Every P0 item is either fixed-and-verified or has a documented reason it was reclassified
  (not silently dropped).
- P1's proposed module boundaries exist in some form, each with its own tests, and `Engine`
  no longer contains the business logic that moved out.
- The P2 table is empty or each remaining row has a `PROGRESS.md` note explaining why it's
  deferred.
- `BASELINE.md`'s checks all still pass, plus whatever new tests this pass added.
- `PROGRESS.md` gives a human a complete, chronological account of what changed and why
  without needing to re-read every diff.

## 7. Progress Tracking & Handback Format

`PROGRESS.md` (created in Phase 0) is the mutable log this document is not. Each entry:

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

At the end of a session (context limit, natural stopping point, or backlog exhausted),
close with a short summary at the top of `PROGRESS.md`: what tier the backlog is currently
at, what's left, and any P0/P1 items that turned out to need a human decision rather than
an autonomous one (e.g. P2-3's "was `asset_conf` meant to be distinct?", P2-15's placeholder
exchange fate, or anything from P0-3 if the duplicate-entry race is confirmed real and the
fix has trading-behavior implications worth a second opinion).

---

## 8. Round 1 Clarifications — Answers to the Coding Agent's Questions (2026-07-28)

Before starting implementation, the coding agent (self-identified as "Jules") reviewed this
document and raised clarifying questions on several P0–P2 items rather than guessing —
exactly the behavior Principle §1.6 asks for. The decisions below are now baked directly
into the relevant items in §2; this section is the dated record of that exchange, kept for
the audit trail per the "living, append-only" instruction in §0.

**Confirmed as originally proposed, no changes needed:**
- **P0-1** (config-override ordering) — confirmed, with one addition now reflected inline:
  `JBaseStrategy.get_config()` must also stop reading the bare `config` module, and the
  override-application logic must be the same code path for every entry point, not
  `compare.py`'s independent copy.
- **P0-5** (order-type wiring) — confirmed; extended to cover `TP_ORDER_TYPE`/
  `SL_ORDER_TYPE` alongside `ENTRY_ORDER_TYPE` as one change, not entry-only.
- **P0-6** (state-type parity) — confirmed as proposed: store real objects, not
  stringified ones, in the in-memory fallback.
- **P0-7** (simulator constructor contract) — confirmed as proposed; add a
  post-construction assertion in `load_strategy` as defense-in-depth.

**Decided — full reasoning now inline at the item itself in §2:**
- **P0-2** (model split-brain) — explicit constructor injection of one shared
  `LearningModel`; rejected the `self.simulator.engine.model` back-reference path as a
  layering inversion.
- **P0-3** (duplicate-entry race) — first-accepted-wins with skip logging as the starting
  policy; check `git blame` on the redundant second tradability check before removing it.
- **P0-4** (aggregate exposure cap) — default 10% of equity aggregate cap,
  `MAX_CONCURRENT_POSITIONS` default dropped to 15. These are starting engineering
  defaults sized for a solo-operator system, not a personalized risk-tolerance
  recommendation — retune against real paper-trading data.
- **P1-2** (settings model) — `pydantic-settings` over plain dataclasses.
- **P2-3** (`asset_conf`) — default to removing it absent further input; original intent
  isn't recoverable from the code and is genuinely a call only the repo owner can make.
- **P2-11** (DB path isolation) — mode-aware `config.DB_PATH`; in-memory SQLite for
  `compare.py`'s transient warm-up cache specifically.
- **P2-15** (placeholder exchanges) — mark via existing header tooling rather than
  relocate; roadmap-vs-prune itself remains the repo owner's product call.

**Genuinely open — flagged, not decided, by design:** P2-3's original intent for
`asset_conf` and P2-15's roadmap timeline for the placeholder exchanges are product/history
questions no amount of code-reading resolves. Proceed on the stated defaults; don't block
the loop waiting on them, but don't treat the defaults as final either — they're logged
here and in `PROGRESS.md` precisely so they're easy to revisit.
