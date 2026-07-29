# AGENTS.md — Remediation & Modularization Directives for `quick` (Round 2)

## 0. Read This First

This is the **second** operating manual for coding-agent work on this repository, superseding
`AGENTS-old.md` (round 1's directives, now historical — do not delete it) as the active
document. It was produced by a human-directed audit on 2026-07-28 that combined static
reading with **empirical verification**: a full local clone, dependency installation, the
existing test suite run to completion, and a live bounded smoke run of `main.py --mode
paper`. Where a claim below says "verified" it means the auditor actually ran code and
observed the result, not just read it.

**Round 1 in one paragraph:** the P0 correctness fixes and the P1-1 god-object decomposition
are substantially real and mostly well-built. But the mandated process — one backlog item
per commit, a `PROGRESS.md` entry per item, "verify before trusting" — was not followed: all
of it landed in a single ~3,300-line commit, `PROGRESS.md` documents only the Phase 0
baseline, and `BASELINE.md` cuts off mid-task before capturing its own smoke-run output.
That process gap is exactly how a real regression (§2, R0-1) and a fake regression test
(§2, R0-3) shipped without anyone catching them. **The single biggest thing this round needs
to do differently is not skip the process again.**

**Coverage disclosure.** This round's audit read, ran, or diffed: `main.py`, `engine/core.py`,
`engine/loop.py`, `engine/positions.py`, `engine/risk.py`, `engine/reporting.py`,
`engine/regimes.py`, `engine/base.py`, `engine/entry.py`, `engine/signal.py`,
`engine/exchanges/bitget.py`, `bitget_client.py`, `config/__init__.py`, `config/settings.py`,
`strategies/base_strategy.py`, `strategies/scalper.1.jules.py`, `ta/scoring.py`,
`ta/utils.py`, `database.py` (write-path structure), `compare.py` (arg parsing +
asset-discovery), `backtest.py` (strategy loading), `models.py` (predict path),
`requirements.txt`, `tools/test_remediation.py`, `.github/workflows/verify_map.yml`,
`.jules/docs/dev/*.md`, and `docs/map.json` (regenerated and diffed — it is currently
accurate, no action needed). **Not** individually re-read this round: `engine/reconciliation.py`'s
internals (only confirmed it has no dedicated tests), `simulator.py`, `orderbook.py`, the
`ta/patterns/*` and `ta/indicators/*` bodies, and most of `tools/`. Treat silence on those as
"not yet checked," not "clean" — closing this gap is still Phase 2 work, carried forward.

This document has the same two jobs as its predecessor: a priority backlog (§2) and a process
for working through it safely and verifiably, in a loop, without a human re-prompting at
every step (§4). **Same living, append-only contract as before**: mark items done in place,
don't delete history, add new findings with the ID scheme below.

---

## 1. Non-Negotiable Operating Principles

All of round 1's principles still apply in full — re-read `AGENTS-old.md` §1 if you haven't.
Restated and strengthened here based on what round 1 actually did:

1. **This code can place real orders with real money.** `MODE=live`/`demo` connect to a real
   exchange. Every test/smoke run/verification runs with `MODE=paper` or a mocked exchange.
   Never invoke live/demo automation. If a task genuinely needs it, stop and ask.
2. **Never surface secrets.** `.env` is confirmed gitignored (re-verified this round — still
   true). Keep it that way.
3. **No silent behavior changes to money-moving logic**, called out explicitly with a
   before→after statement in the commit message *and* in `PROGRESS.md`.
4. **Every change is independently verifiable — and "a test exists" is not the same as "the
   test verifies the thing."** Round 1 shipped a test (`test_p0_3_duplicate_signals_block`)
   that reimplements the assertion inline instead of calling production code, so it would
   pass even if the fix were deleted. Before marking anything verified, ask: *if I reverted
   just the production code and left the test alone, would the test fail?* If you can't
   answer yes with confidence, the test doesn't verify the fix yet.
5. **One backlog item per commit. No exceptions, no batching "while I'm in there."** Round 1
   put P0-1 through P1-2 plus a full module decomposition into one commit. This round, if you
   notice a genuinely trivial, same-line fix while working a different item, note it in
   `PROGRESS.md` as a follow-up and commit it *separately* right after — don't fold it in.
   The tree builds/imports cleanly at every single commit; verify this yourself before each
   commit, don't assume it.
6. **`PROGRESS.md` gets a real entry — format in §7 — before you move to the next backlog
   item, not at the end of a session.** If you finish an item and start the next one without
   writing the entry first, you have violated this principle even if you write it up later
   from memory. Write it immediately, while the diff is in front of you.
7. **When intent is ambiguous, don't guess silently** — document both readings, propose a
   default, flag it, move on.
8. **Preserve the existing decision trail** (`[TECH-001]`, `[ARCH-003]`, `[P0-1]` etc. tags).
   Consolidate, don't delete.
9. **Work on a branch** (e.g. `agent/round-2-hardening`), never directly on `development`.
10. **"Microservice-esque" means discipline, not deployment topology"** — still one process,
    still no network/IPC in the hot path. Same P4-1 exception, same deferral.
11. **A round-1 decision that was explicitly reasoned through (documented in `AGENTS-old.md`
    §8) is binding until a human revisits it — it is not a suggestion to route around if a
    different pattern is more convenient in one file.** R1-4 below exists because this was
    violated once already (`backtest.py` uses the exact back-reference pattern §8 rejected
    for P0-2). If you find a case where the decided approach genuinely doesn't fit, stop,
    document why in `PROGRESS.md`, propose the deviation explicitly, and flag it for human
    review in the handback — don't just implement the alternative silently.

---

## 2. Priority Backlog

IDs starting with `R0`/`R1`/`R2`/`R3` are new this round. IDs like `P0-5` refer back to the
original round-1 item, now annotated with this round's verification. Work strictly top to
bottom within a tier.

### P0 — Correctness & Risk (fix first; wrong behavior here loses money or breaks the app outright)

#### R0-1 — `requirements.txt` is missing `pydantic` and `pydantic-settings`; the app cannot start
**Where:** `requirements.txt`; every entry point (`main.py`, `backtest.py`, `compare.py`) via `config/__init__.py` → `config/settings.py`.
**Evidence (empirically verified):** a clean `python -m venv` + `pip install -r requirements.txt` followed by `python3 -c "import main"` raises `ModuleNotFoundError: No module named 'pydantic_settings'` immediately. `config/settings.py` imports `pydantic_settings.BaseSettings`/`SettingsConfigDict` and `pydantic.Field`/`BaseModel`, neither of which is declared anywhere in `requirements.txt`. This is a total, immediate regression introduced by round 1's own P1-2 migration — nothing in the repo runs from a fresh checkout right now, including the test suite.
**Fix:** Add `pydantic` and `pydantic-settings` (pin to the versions actually tested against) to `requirements.txt`. Also add `pytest` and `pytest-asyncio` — the test suite needs them and they're currently undeclared too (only present because someone's local environment happened to have them). Confirm the pinned versions resolve cleanly together with `aiohttp==3.14.1`.
**Verify:** From a genuinely clean venv, `pip install -r requirements.txt` then `python3 -m pytest` and `python3 -c "import main, backtest, compare"` must all succeed with zero manual intervention. Do this as your literal first action this round, before anything else — nothing else you do can be trusted as "tested" until this is fixed.

#### R0-2 — TP/SL order type is read for a fee estimate only; it never controls actual exit-order execution (completes P0-5)
**Where:** `bitget_client.py::place_order` (embedded `presetTakeProfitPrice`/`presetStopLossPrice`), `bitget_client.py::place_tpsl_order` (`"triggerType": "market"` hardcoded), `engine/exchanges/bitget.py::place_order` (reads `self.config.TP_ORDER_TYPE` only inside the pre-trade fee-vs-profit filter at the "REJECTED NARROW FEE TRAP" check).
**Evidence:** Traced the full call path for both the embedded-TP/SL path and the standalone `place_tpsl_order` path. Neither ever passes an order-type-equivalent parameter derived from `config.TP_ORDER_TYPE`/`SL_ORDER_TYPE` to the exchange. The *only* place these settings are consulted is `engine/exchanges/bitget.py`'s internal `exit_fee_rate = MAKER_FEE if TP_ORDER_TYPE == "limit" else TAKER_FEE` calculation, used to decide whether a trade clears `MIN_NET_TP_PROFIT_PCT`. This means: if `TP_ORDER_TYPE`/`SL_ORDER_TYPE` don't match what the exchange actually does (a market-triggered close, per Bitget's plan-order/preset mechanics), the profitability gate is silently using the wrong fee assumption — it can let through trades whose *real* expected fees exceed the threshold it thinks it's enforcing. This is a live-trading-relevant correctness bug, not just an unfulfilled toggle.
**Fix:** Two sub-decisions needed, in order: (a) determine whether Bitget's API actually supports a maker-style (post-only/limit-priced) TP/SL execution mode at all for preset/plan orders — if not, `TP_ORDER_TYPE`/`SL_ORDER_TYPE` as user-facing toggles are misleading regardless of wiring and the fix is to make the fee-estimate always assume the exchange's real behavior (likely always taker) and either remove the toggle or clearly document it as "fee-estimate only, execution is always market-triggered on this exchange." (b) If Bitget does support it, wire it through exactly as ENTRY_ORDER_TYPE was wired — pass it into `place_tpsl_order`'s `triggerType`/equivalent instead of hardcoding `"market"`. Do not guess; check Bitget's V2 API docs for what `presetTakeProfitPrice`/`presetStopLossPrice` and the plan-order endpoint actually support before choosing (a) or (b).
**Verify:** A test mirroring `test_p0_5_order_type_wiring` but for the exit path: mock exchange, assert the actual API call parameters reflect the configured `SL_ORDER_TYPE`/`TP_ORDER_TYPE` (or, if (a) is the resolution, assert the fee-estimate now correctly always uses taker fees and the misleading toggle is either removed or documented).

#### R0-3 — P0-3's regression test doesn't exercise the fix it claims to verify
**Where:** `tools/test_remediation.py::test_p0_3_duplicate_signals_block`.
**Evidence:** The test builds its own local `if pos_key in engine.open_positions or pos_key in engine.pending_entries:` check and its own `log.warning(...)` call *inside the test body*, then asserts against that self-authored log line. It never calls `Engine`, `TradingLoop`, or any method that contains the real duplicate-block logic living in `engine/loop.py` (lines ~367–375). Deleting that real logic entirely would not fail this test. The actual production fix looks correctly implemented (verified by direct code read: the atomic `pending_entries` reservation happens synchronously before any `await`, so the race it's meant to close does appear closed) — but it currently has zero regression protection.
**Fix:** Rewrite the test to construct a real `Engine`/`TradingLoop` (or the smallest slice of it that's practical — consider whether `TradingLoop._trading_loop`'s relevant section can be exercised directly against two mock strategies returning colliding signals) and assert on real log output / real routing behavior, not a self-authored stand-in.
**Verify:** Confirm the new test fails if you temporarily comment out the real check in `engine/loop.py`, then restore it and confirm it passes. Do this by hand once as a sanity check; don't just trust the test's shape.

#### R0-4 — `backtest.py`'s learning-model wiring uses the pattern the round-1 clarifications explicitly rejected
**Where:** `backtest.py::StrategyWrapper._load_strategy` (`model = self.simulator.engine.model` when `self.simulator.engine` is set).
**Evidence:** `AGENTS-old.md` §8 explicitly says, of P0-2: *"Rejected: routing through `self.simulator.engine.model` — that requires the exchange/simulator layer to hold a back-reference to the `Engine` that owns it, a layering inversion... Don't build support for a strategy-private, unshared model speculatively."* `main.py` and `compare.py` correctly use direct constructor injection (`model=engine.model`). `backtest.py` instead fetches it via exactly the rejected back-reference. It works today only because `exchange.engine = <the owning Engine>` already exists for unrelated reasons (leverage-limit lookups), so this doesn't introduce a *new* circular reference — but it does silently reintroduce the exact pattern that was reasoned through and rejected, inconsistently with the other two entry points, and it degrades to the old split-brain behavior (each strategy builds its own model) in any code path where `self.simulator.engine` isn't set — which is plausible for `backtest.py`'s lighter-weight TA-module and confluence-chaining backtest modes that may not construct a full `Engine`.
**Fix:** Either (a) refactor `backtest.py`'s call sites to construct/thread a shared model explicitly the same way `main.py`/`compare.py` do (preferred, for consistency), or (b) if there's a concrete reason backtest specifically needs the back-reference approach, document that reason explicitly in this file and in `PROGRESS.md` as a formal, human-reviewed exception to principle §1.11 — don't leave it as an undocumented inconsistency either way.
**Verify:** Audit every `backtest.py` code path that can load a strategy (single-strategy, TA-module, confluence-chaining via `->`) and confirm each one either gets a real shared model or is confirmed not to need one (e.g., pure TA-pattern backtests with no `LearningModel`-dependent strategy in play).

#### P0-1 through P0-7 (round 1) — status after re-verification
All seven re-verified against current code this round. Summary (see the accompanying chat
response for full detail; don't duplicate investigation, just re-confirm before touching):
- **P0-1** (config override ordering): confirmed correctly fixed. `ConfigContext(**overrides)`
  applied before any downstream component reads config; no more `setattr` on the bare module.
- **P0-2** (model split-brain): confirmed correctly fixed for `main.py`/`compare.py` via direct
  constructor injection. See R0-4 above for the `backtest.py` gap.
- **P0-3** (duplicate-entry race): production fix confirmed correctly implemented. See R0-3
  above for the test gap.
- **P0-4** (aggregate exposure cap): confirmed correctly fixed — `MAX_AGGREGATE_MARGIN_PCT=0.10`,
  `MAX_CONCURRENT_POSITIONS=15`, implemented in `RiskGate.is_asset_tradable`, real passing test.
- **P0-5** (order type wiring): entry path confirmed correctly fixed with a real test. See R0-2
  above — the TP/SL half of this item is not actually done despite being marked in scope.
- **P0-6** (state type parity): confirmed correctly fixed, well-tested with real assertions.
- **P0-7** (simulator wiring contract): confirmed correctly fixed (constructor contract +
  fail-loud `is_ready()` + post-construction assertion in `load_strategy`).

---

### P1 — Architecture & Single-Concern Modularity

#### R1-1 — Finish P1-1: `Engine` still owns business logic; `PositionLedger`'s interface is inconsistently used
**Where:** `engine/core.py::_report_entry`/`_report_exit`/`_log_heartbeat`/`_log_periodic_summary` (still ~500 lines of logic on `Engine` reaching into `self.reporter.X`/`self.ledger.X` from outside); `engine/reporting.py::TradeReporter` (currently almost pure data — one real method, `print_final_stats`); `engine/positions.py::PositionLedger` (has a clean method interface — `add_position`/`remove_position`/`add_pending`/`remove_pending` — that `engine/core.py` and `engine/loop.py` bypass in multiple places, e.g. `engine/loop.py` lines ~477-478 do `del self.ledger.open_positions[pos_key]` / `self.ledger.pending_entries.remove(pos_key)` directly instead of calling the ledger's own removal methods).
**Fix:** Move the recording logic (not just the data) into `TradeReporter` as real methods — `reporter.record_entry(...)`, `reporter.record_exit(...)` — so `Engine` calls them with raw trade facts and `TradeReporter` owns all of its own bookkeeping, exactly as `PositionLedger` already does for positions. Then audit every direct `.open_positions[...]` / `.pending_entries` touch in `engine/core.py` and `engine/loop.py` and route it through `PositionLedger`'s methods; add any missing ones (e.g. `is_pending(pos_key)`, `is_open(pos_key)`) rather than reaching into internals. `Engine` should end this item smaller than it starts it.
**Verify:** Unit tests for `TradeReporter.record_entry`/`record_exit` independent of `Engine`. Grep for direct `.open_positions[` / `.pending_entries` access outside `positions.py` after the change — should return nothing except inside `PositionLedger` itself.

#### R1-2 — Finish P1-2: no validation constraints exist yet; `ConfigContext` still reflects the pre-migration pattern; overrides bypass validation entirely
**Where:** `config/settings.py` (all 8 settings groups — every field is an unconstrained primitive, zero `Field(ge=..., le=...)` anywhere despite this being the stated reason for the migration); `config/__init__.py::ConfigContext.__init__` (still does `for k, v in globals().items(): if ... setattr(self, k, v)` — the same reflection-over-globals pattern, now one layer removed from the typed settings instead of eliminated); only `EnvironmentSettings` extends `BaseSettings` (actually reads env vars) — the other 7 groups are plain `BaseModel` with Python-coded defaults only, never touched by env loading.
**Fix, in order of value:**
1. Add real `Field()` constraints to every bounded value — all `WEIGHT_*` fields, `RISK_PER_TRADE`, `MAX_AGGREGATE_MARGIN_PCT`, `DRAWDOWN_LIMIT`, and similar fraction/percentage fields get `ge=`/`le=` bounds; `MAX_CONCURRENT_POSITIONS`, `MAX_TRADES_LIMIT` etc. get `gt=0`. This is the actual point of the migration and currently delivers zero benefit over the old flat module.
2. Make `ConfigContext.__init__`'s override path (`**kwargs`) validate through Pydantic rather than raw `setattr` — e.g. re-validate the relevant settings group with the override merged in, so a CLI typo that sets a float field to a string, or a weight to `-500`, fails loudly instead of being silently accepted. This is the highest-risk input path (human-typed, tunes live-trading parameters) and currently has *less* validation than the rest of the system.
3. Confirm with the repo owner whether the 7 non-environment groups are meant to be env-configurable at all (the original `.env` example only ever showed `BITGET_*`/`MODE`) — if not, document that explicitly as intentional; if so, make them `BaseSettings` too.
**Verify:** A test that constructs `ConfigContext(WEIGHT_RSI=999)` or `ConfigContext(RISK_PER_TRADE="not a number")` and asserts it raises, not silently accepts.

#### R1-3 — Finish P1-3: `hasattr`/`getattr` duck-typing still ungoverned
**Where:** `BaseStrategy`/`BaseExchange` ABCs (`engine/base.py`) unchanged in scope since round 1 — still only 2 abstract methods on `BaseStrategy`, still no formal contract for `is_ready`, `required_history`, `params`, `db`, `symbol_map`/`rev_symbol_map`, `asset_correlations`, `ready_assets`, etc. All the original call sites (`RiskGate`, `TradingLoop`, `Engine`) still probe defensively via `hasattr`/`getattr(..., default)`.
**Fix:** As originally scoped — audit every call site, formalize genuinely-required members into the ABCs, model genuinely-optional capabilities as `typing.Protocol` checks instead of inline `hasattr`.
**Verify:** mypy/pyright (if adopted per §5) should be able to catch a missing required member at type-check time once this is done; that's the practical test of "did this actually change anything."

#### R1-4 — Finish P1-4: `OrderRequest` dataclass exists but is never used
**Where:** `engine/signal.py::OrderRequest` — well-designed, has `to_dict`/`from_dict` for backward compat — but a repo-wide search confirms it is not imported or constructed anywhere outside its own file. `SignalRouter.route_signal` still takes/returns raw dicts with the same manual `kwargs.pop(key, None)` pattern flagged originally.
**Fix:** Wire it in for real: have `SignalRouter.route_signal` accept (or immediately convert to) an `OrderRequest`, and have at least one strategy's `get_entry_signal` construct one instead of a bare dict, proving the round-trip (`from_dict`/`to_dict`) actually works end to end before declaring this done.
**Verify:** A test constructing a signal both ways (dict and `OrderRequest`) and confirming `route_signal` behaves identically; a real collision (two different fields mapping to the same downstream parameter name) should now be a type error at construction, not a runtime surprise — write a test that proves this too.

#### P1-5, P1-6 (round 1) — confirmed correctly resolved, no further action.

---

### P2 — Consistency, Duplication & Hygiene

Re-verified against current code. Status column reflects this round's direct check, not the
original document.

| ID | Where | Status this round | Action |
|---|---|---|---|
| P2-1 | `config/__init__.py::TF_SECONDS`, `strategies/base_strategy.py` (**now duplicated twice in the same file** — `get_readiness_eta` and `get_milestone_report` each hardcode an identical `tf_map` literal), `compare.py` | **Still open**, arguably worse (self-duplication) | Import `config.TF_SECONDS` in both spots in `base_strategy.py` and everywhere else it's hand-copied; delete the local copies. |
| P2-2 | `engine/loop.py` (inline asset filtering) vs `compare.py::DataCoordinator` (separate inline copy) | **Still open**, confirmed both copies still independently maintained | Extract shared `discover_assets(tickers, omitted, count)`; both call it. |
| P2-3 | `ta/scoring.py` | **Done** — `asset_conf` fully removed, confirmed via grep | none |
| P2-4 | `ta/scoring.py` (`MIN_VOLATILITY`, `VOL_PCT_MIN` still absent from `config/settings.py`) | **Still open** | Promote into the appropriate settings group now that one exists (this is easier than it used to be — there's a real typed home for it now). |
| P2-5 | `ta/scoring.py` lines ~255-256 | **Still open, confirmed unchanged** — `ENTRY_SCORE_THRESHOLD` fallback still literally `30.0` vs configured `15.0`; `BY_DEFAULT_REPORT_ONLY` fallback still literally `True` vs configured `False` | Fix the literals or remove them; add the drift test originally requested. |
| P2-6 | `main.py`, `compare.py`, `backtest.py`, `strategies/base_strategy.py`, 3 strategy files, `tools/logger.py` | **Still open** — 17 bare `except:` sites counted this round | Narrow to specific exceptions per original guidance. |
| P2-7 | `main.py` line ~153 | **Still open, confirmed unchanged** — `RISK_PER_TRADE` still logged as "Target net profit per trade" | Fix the label. Bonus finding this round: this startup log line (and the mode line above it) read module-level `MODE`/`RISK_PER_TRADE` imported before argparse runs, so they don't even reflect `--mode`/override values — fix both issues together. |
| P2-8 | `main.py` line 27 | **Still open, confirmed unchanged** | Derive logger name from loaded strategy/mode. |
| P2-9 | `main.py::load_strategy` fuzzy-match fallback | **Partially open** — the new top-level recursive directory walk (added this round for whole-family loading) covers a lot of practical cases, but the specific single-file fuzzy-fallback branch (`for f in os.listdir("strategies")`) is unchanged and still non-recursive | Make this specific fallback use `os.walk`, matching the directory loader's own behavior. |
| P2-10 | `engine/entry.py` line 31 | **Still open, confirmed unchanged** — stale "In a real implementation..." comment sits directly above the real implementation | Delete it. Two-minute fix, still not done. |
| P2-11 | `config/__init__.py::DB_PATH` | **Done** — mode-aware `data/market_data_{mode}.db` confirmed | none |
| P2-12 | `database.py` | **Still open** — `save_weight`/`save_strategy_state`/`save_discovered_assets` confirmed still writing synchronously via `self.connection` directly, undocumented, while the high-volume methods go through the queued writer thread | Document the threading contract or unify, per original guidance. |
| P2-13 | `compare.py::parse_args` line ~305 | **Still open, confirmed unchanged** — raw `for arg in sys.argv[1:]` scan still coexists with `parser.parse_known_args()`'s `remaining` | Scan `remaining` only. |
| P2-14 | `models.py::LearningModel.predict` | **Still open, confirmed unchanged** — still two full `ScoringEngine.evaluate()` calls per prediction | Compute side-independent scores once per original guidance. |
| P2-15 | `engine/exchanges/*.py` | **Done** — `STATUS: placeholder, not implemented` headers confirmed present on all 9 stub drivers | none; roadmap-vs-prune remains the human's call |

**New P2 items found this round:**
- **R2-1** — `engine/loop.py` and `main.py` both call `engine._print_final_stats()` at the end of a run (`loop.py` inside `TradingLoop.run()`, `main.py` in its `finally` block), producing duplicate "===== FINAL STATS =====" output — confirmed via a live run. Pick one call site (recommend keeping it in `main.py`'s `finally` so it fires on every exit path including exceptions, and removing it from `loop.py`).
- **R2-2** — Live smoke run showed "Unclosed client session"/"Unclosed connector" warnings from `aiohttp` on graceful shutdown. Worth a proper `async with`/explicit `.close()` audit in the exchange driver's shutdown path — confirm whether this predates this round's changes or was introduced by them before prioritizing.
- **R2-3** — `.jules/docs/dev/system.md` still describes `engine.py` as a single file ("### 1. Engine (`engine.py`)... The orchestrator of the system") — stale relative to the actual `engine/` package post-decomposition. Low priority but easy; update alongside other doc touch-ups.

---

### P3 — Testing & Verification Infrastructure

**Essentially unchanged from round 1 — re-verify this is still accurate before assuming so, but as of this audit:**

#### P3-1 — Still no `tests/` tree
Tests still live as `tools/test_*.py` / `tools/verify_*.py`, now with one more file added there
(`tools/test_remediation.py`) rather than a proper `tests/` tree. Superseded
`verify_pnl_calculations.py` → `_v2` → `_v3` and `analyze_data.py` → `_v2` still all present,
undecided. Original guidance stands: establish `tests/`, migrate real coverage over
(preserving the financial-correctness assertions in the pnl/rrr scripts exactly), decide
superseded-version fate only after confirming coverage is preserved.

#### P3-2 — Still no test-running CI
The only workflow that exists (`.github/workflows/verify_map.yml`) checks that `docs/map.json`
is current — useful, keep it — but there is no lint/test-on-push/PR workflow at all. Add one.
Every step runs in `MODE=paper` or mocked, per Principle §1.1. This is now more urgent than
in round 1: it would have caught R0-1 (the missing-dependency regression) on the very next
push.

#### P3-3 — Still no codified, asserted paper-mode smoke test
`BASELINE.md`'s attempt at this cuts off mid-sentence with no captured output. This round's
audit ran one manually (`main.py --strategy scalper.1.jules --mode paper`, bounded) and
confirmed it starts, discovers assets, runs the trading loop, and shuts down cleanly on
signal — but this isn't codified anywhere as a repeatable, asserted check. Turn it into an
actual test (bounded duration or tick count, asserting no exceptions and a sane final stats
block), matching the original ask exactly.

#### R3-1 — `engine/reconciliation.py` has no dedicated tests despite being explicitly called out as needing them first
`AGENTS-old.md` said of the pre-extraction `_sync_exchange_state`: *"get this one under test
before refactoring it, given how much financial correctness rides on it."* It was extracted
into `engine/reconciliation.py::ExchangeSync` this round with no dedicated test file — the
only test with "reconciliation" in its name (`tools/test_order_pnl_reconciliation.py`) covers
PnL/fee math, a different concept entirely. This is the single highest-financial-stakes gap
in the current test coverage and should be near the top of P3 work, not an afterthought.

---

### P4 — Forward-Looking (still explicitly deferred — confirmed untouched this round, correctly)

P4-1 (read-only UI facade) and P4-2 (thin entry-point adapters) remain deferred exactly as
before — confirmed via search that nothing in this round's work touched them. P4-3
(placeholder exchange roadmap) remains the repo owner's call.

- **P4-4 — limit-style take-profit via the standalone plan-order endpoint**: Implements a limit-type execution mode for Take Profit by utilizing the standalone plan-order endpoint with an `executePrice`. This requires a separate risk review to assess the gap between entry fill and TP placement where the position is briefly unprotected on that leg.

**Added context, non-blocking:** the repo owner is evaluating a lightweight, non-TUI,
open-source editor/terminal (leading candidates under consideration: Zed, Lapce — both
native/GPU-rendered rather than Electron-based) to eventually replace the current dev
workflow, with P4-1's read-only facade as the natural eventual data source for a custom
dashboard inside it. This is explicitly **after** Round 2's P0–P3 close, per Principle §1.10
— don't let it pull focus, but keep P4-1's design (state snapshots + structured events) in
mind so it doesn't need rework later. No action this round.

---

## 3. Proposed Target Module Layout — status update

Compare against `AGENTS-old.md` §3's proposal:

```
engine/
  loop.py            ✅ exists, matches intent — still calls back into Engine/reporter
                      internals more than the "contains no risk/reporting logic itself"
                      goal wants (see R1-1)
  positions.py        ✅ exists, clean interface — inconsistently used elsewhere (R1-1)
  risk.py              ✅ exists, matches intent
  reporting.py         ⚠️  exists but is data-only; needs the record_entry/record_exit
                      methods described in R1-1 to actually match "TradeReporter" as
                      originally scoped
  regimes.py           ✅ exists, matches intent
  reconciliation.py    ⚠️  exists, matches intent structurally — but has zero dedicated
                      tests despite being flagged as the highest-stakes extraction (R3-1)
  factory.py           ❌ not created — mode→exchange/model selection still lives inline in
                      Engine.__init__, not in a separate factory function. Low priority,
                      revisit after R1-1/R1-2 land.
  signal.py            ⚠️  exists, well-designed, unused (R1-4)

config/
  settings.py          ⚠️  exists, correctly domain-organized — needs validation
                      constraints (R1-2)
  (risk/execution/scoring/logging/simulator as separate files)
                        ❌ implemented as domains *within* settings.py (BaseModel classes)
                      rather than separate files — this is a reasonable equivalent, not a
                      gap; don't split into separate files just to match the original
                      sketch literally, the original document itself said "validate against
                      actual coupling... not a specific file count."
```

`Engine` (`engine/core.py`) is meaningfully smaller than pre-round-1 but is not yet the "thin
composition object" the target describes — see R1-1. Keep pushing logic out; don't accept a
smaller-but-still-mixed `Engine` as done.

---

## 4. The Looping Development Process

Same shape as round 1 (§4 there), with one addition given what went wrong:

### Phase 0 — Baseline & Reconciliation (run once, before any new backlog work)

1. **Fix R0-1 first, literally before anything else.** Confirm `pytest`, `main.py`, `backtest.py`, `compare.py` all run clean from a fresh venv. Nothing else you do this round can be trusted as verified until this is true.
2. **Backfill `PROGRESS.md` for round 1's actual work.** Commit `85b626e0498e40a187564f5a9c6d837ae5bb07aa` ("Remediate P0-P2 correctness/risk issues, decompose Engine god object, and migrate config to Pydantic-Settings...") shipped ~20 backlog items with zero individual `PROGRESS.md` entries. Before starting new work, go through that commit's diff and write the missing entries retroactively, one per item actually completed (P0-1, P0-2, P0-3, P0-4, P0-5-partial, P0-6, P0-7, P1-1, P1-2-partial, P1-5, P1-6, P2-3, P2-11, P2-15 at minimum). This is not busywork — writing each one up forces you to re-examine what actually shipped, which is exactly the process that caught R0-1 through R0-4 this round. Mark this Round 2's own Phase 0 item zero.
3. Re-run `tools/generate_map.py` and diff against `docs/map.json` — confirmed already in sync as of this audit, but re-check before assuming it still is.
4. Run the full existing test suite (`tools/test_*.py`, now including `test_remediation.py`) and capture output into a fresh, *complete* `BASELINE.md` entry — including the paper-mode smoke run's actual output this time, not a cut-off sentence.
5. Confirm `.env` is still gitignored (it is, as of this audit — re-verify).

### Phase 1 — The Work Loop

Identical to `AGENTS-old.md` §4 Phase 1 steps (a) through (j) — re-read them there, they're
still correct. The one thing to actually do differently: **step (g), the `PROGRESS.md`
entry, happens before step (h), the commit — not after, not batched at session end.** If
you're about to `git commit` and haven't written the entry yet, stop and write it first.

Priority order for this loop: R0-1 → R0-2 → R0-3 → R0-4 → remaining P0 (none — all
seven round-1 P0s are closed) → R1-1 → R1-2 → R1-3 → R1-4 → P2 table top to bottom → P3
(R3-1 first, given the financial-stakes argument, then P3-1/P3-2/P3-3).

### Phase 2 — Consolidation Pass (after P0–P3 above are clear)

Same as `AGENTS-old.md` §4 Phase 2: close the remaining coverage gap (`simulator.py`,
`orderbook.py`, `bitget_client.py`'s untraced portions, the `ta/patterns/`/`ta/indicators/`
bodies, most of `tools/`), re-run header/map consistency checks, produce a fresh human-facing
summary and backlog for whatever's left — this becomes the input to round 3.

---

## 5. Verification & Testing Standards

Same as `AGENTS-old.md` §5, plus:

- **Before marking any item verified, apply the test from Principle §1.4**: would the test
  actually fail if you reverted only the production change? If you're not sure, it's not
  verification yet.
- Critical financial math still gets exact-value regression tests, not smoke coverage.
- `ruff`/`mypy`/`pyright` — not yet adopted per this audit's check; note in `PROGRESS.md`
  either way (adopted, or explicitly still skipped and why) rather than leaving it silently
  unaddressed again.

---

## 6. Definition of Done (per pass)

Same criteria as `AGENTS-old.md` §6, with one addition: **a pass is not done if any backlog
item's `PROGRESS.md` entry is missing, even if the code change is complete and correct.**
Round 1 proved that "the code is right but undocumented" silently decays into "the next
person can't tell what's actually true without re-auditing everything" — which is the entire
reason this round took as long as it did.

---

## 7. Progress Tracking & Handback Format

Identical format to `AGENTS-old.md` §7. One process note: when backfilling round 1's entries
(Phase 0, item 2 above), date them accurately as retroactive (e.g. `Date: 2026-07-28
(retroactive, written 2026-07-29)`) rather than implying they were written contemporaneously
— the historical record should be honest about when it was actually produced.

---

## 8. Open Questions — flagged, not decided, by design

These need the repo owner's input; proceed on the stated defaults, don't block on them:

- **R0-2's (a)/(b) fork**: whether Bitget's API genuinely supports non-market TP/SL execution
  for preset/plan orders at all. This determines whether `TP_ORDER_TYPE`/`SL_ORDER_TYPE`
  should be fully wired or retired as a misleading toggle. Default absent further input:
  investigate the API docs first; if ambiguous after that, default to (a) — make the fee
  estimate honest about always-market execution, and treat "real limit-style TP/SL" as a
  separate, explicitly-scoped future item rather than guessing at wiring against an API that
  may not support it.
- **R1-2's third point**: whether the 7 non-environment settings groups should read from
  `.env`/environment variables at all, or whether CLI `KEY=VALUE` overrides are the only
  intended tuning mechanism by design. Default absent further input: assume CLI-override-only
  is intentional (matches the README's documented workflow) and don't add env-loading to
  those groups without confirmation.
- **P2-15's original open question** (roadmap vs. prune timeline for the 9 placeholder
  exchanges) — still the repo owner's product call, still not resolved by code-reading.

---

## 9. Round 2 Clarifications

Preserved decision trail and guidelines established during human-directed clarifying session on 2026-07-29:

### 9.1. R0-1: requirements.txt versions
Pin exact versions (using `==`, not ranges) of `pydantic`, `pydantic-settings`, `pytest`, and `pytest-asyncio`. These versions must be determined empirically by installing standard packages in a clean environment, running all tests and the bounded smoke test successfully, and then recording the exact passing set.

### 9.2. R0-2: TP/SL order execution and fee estimation
Stop-loss (SL) must remain hardcoded-to-market by design for risk management to guarantee exit during fast, adverse market conditions. Therefore, both TP and SL execute at market today. The fee estimator must be updated to honestly reflect this (always use taker fees for both TP and SL), fixing the profitability-gate bug. `SL_ORDER_TYPE=limit` must not be wired to change execution. Limit-style take-profit is deferred to a future roadmap item **P4-4** to allow for a dedicated risk review regarding the gap between entry fill and TP placement.

### 9.3. R0-4: backtest.py model wiring
Refactor all loading paths in `backtest.py` to use direct constructor/thread injection of the shared learning model. Do not retain the back-reference (`self.simulator.engine.model`) anywhere. For confluence chaining, apply the same default (one model per backtest run, injected explicitly, never fished off a back-reference) and document any chaining nuances in `PROGRESS.md`.

### 9.4. R1-2: env-loading for the 7 settings groups
The 7 non-environment settings groups (Risk, Assets, Execution, Strategy, Scoring Weights, Logging, Simulator) must remain as plain `BaseModel` classes, with CLI overrides as their primary/only modification mechanism. This keeps deployment-level configuration separate from runtime execution tuning. A one-line comment must be added in `config/settings.py` stating this is intentional.

### 9.5. R1-1: TradeReporter / PositionLedger signatures
- `TradeReporter`'s `record_entry`/`record_exit` methods must accept plain data parameters (symbol, side, prices, qty, pnl, fees, strategy_id, timestamps, exit reason, etc.) without referencing cross-module objects (no `Engine` reference).
- Database persistence must be decoupled from `TradeReporter` (keep the `db.save_trade` calls in the `Engine` or loop layers, while `TradeReporter` handles stats tracking only).
- `PositionLedger`'s `is_pending` and `is_open` methods must use the same key format (`SYMBOL_side`) as `add_position`/`remove_position`.
- Decouple `OrderRequest` from this item (order requests are outgoing intents; trade records are settled facts).
