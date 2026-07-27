"""
1. Summary: Automated 3-part header comment applier.
2. Description: Loops through a pre-defined mapping of file paths to their respective summaries, descriptions, and contexts. Strips any pre-existing leading module docstrings from target Python files or shebang-prefixed launcher scripts, and inserts standard 3-part comments at the top of each.
3. Context: Used to automate the execution of Part A file headers. Can be run repeatedly to refresh file docstrings deterministically.
"""
import os
import ast

# Map of file path -> (Summary, Description, Context)
HEADERS_MAP = {
    "backtest": (
        "Executable shell launcher for the python backtesting system.",
        "Ignores parent wrapper SIGINT signals so the child backtest process can handle key interrupts gracefully, print final reports, and exit without corruption. Runs backtest.py with all CLI arguments passed.",
        "Dependent on backtest.py. Uses subprocess and sys.executable to run."
    ),
    "compare": (
        "Executable shell launcher for the multi-variant strategy comparison system.",
        "Ignores parent wrapper SIGINT signals so the child comparison/A/B testing process can handle key interrupts gracefully, print final comparison tables, and exit cleanly. Runs compare.py with all CLI arguments passed.",
        "Dependent on compare.py. Uses subprocess and sys.executable to run."
    ),
    "main": (
        "Executable shell launcher for the live/demo trading bot execution engine.",
        "Passes all CLI arguments and runs main.py using the current active Python interpreter.",
        "Dependent on main.py. Uses subprocess and sys.executable to run."
    ),
    "backtest.py": (
        "Backtesting execution coordinator with multi-variant and timeline support.",
        "Runs historical backtests for a list of strategies or strategy families sharing capital in a single loop. Handles date boundaries, database warmups, asset discovery, stream logging redirection, contract specs caching, and graceful finalizations.",
        "Relies on config.py, database.py, simulator.py, tools/logger.py, and tools/publisher.py."
    ),
    "compare.py": (
        "Multi-variant orchestrator and live stream coordinator for real-time A/B testing of configurations.",
        "Spins up multiple parallel worker subprocesses (Variants) running the live simulation loop concurrently on shared memory. Includes a data coordinator that handles a single websocket feed and pushes trade signals/ticker updates to variant-specific queues to prevent API rate limiting.",
        "Relies on config.py, engine/core.py, bitget_client.py, and tools/logger.py."
    ),
    "main.py": (
        "Main entry point for starting the live or demo trading robot.",
        "Resolves CLI arguments and loads a single strategy or recursively discovers and loads a strategy family. Instantiates the execution engine in the requested mode (paper, demo, live) and launches the core async loop.",
        "Relies on engine/core.py, engine/entry.py, config.py, and tools/logger.py."
    ),
    "config.py": (
        "Global application configuration context, risk definitions, and technical parameters.",
        "Declares centralized keys for environments, account limits, execution styles, strategy rules, scoring multipliers, and logging thresholds. Encapsulates an immutable ConfigContext class to isolate parameters cleanly in multi-threaded/A/B test variants.",
        "Imported and read by almost every component in the repository to parameterize operations."
    ),
    "database.py": (
        "Persistent SQLite database storage interface for logs, candles, and positions.",
        "Handles initialization of the market_data.db database and coordinates saving/retrieving historical candlestick data, trade logs, and execution parameters. Implements clean multi-threaded execution and safe asynchronous shutdowns.",
        "Relies on standard library sqlite3. Utilized by backtest.py, simulator.py, and bitget_client.py."
    ),
    "bitget_client.py": (
        "REST and WebSocket API client wrappers for the Bitget exchange interface.",
        "Encapsulates V2 private signature creation, API rate limiting with strict safety margins, connection pooling, and multi-threaded WebSocket subscriptions. Fetches market symbols, order book snapshots, historical tickers, and handles demo vs. live API routing.",
        "Relies on aiohttp and pytz. Used by engine/exchanges/bitget.py and compare.py."
    ),
    "models.py": (
        "Reinforcement learning trading models and feature-based prediction engines.",
        "Manages Q-Learning weight maps, feature normalizations, and action determinations. Integrates strict boundary safeguards to prevent NameErrors and index crashes during real-time updates and predictions.",
        "Relies on config.py and ta/features.py. Used by strategies to obtain predictive entry recommendations."
    ),
    "orderbook.py": (
        "Memory-efficient order book mirror and simulated order book generator.",
        "Defines OrderBook to maintain a real-time copy of bid/ask levels for spread/imbalance calculation. Defines SimulatedOrderBook to generate realistic dummy books until actual exchange data streams arrive.",
        "Used by engine/core.py and simulator.py to calculate spread and book metrics."
    ),
    "simulator.py": (
        "High-fidelity paper trading simulation engine with multi-timeframe order matching.",
        "Mimics live contract endpoints by tracking virtual margins, calculating transaction fees, and validating OCO limit orders against ticks. Supports 3-way take-profit splits and trailing stops with zero-slippage execution.",
        "Relies on config.py, database.py, orderbook.py, and tools/publisher.py. Serves as the exchange interface in paper simulation."
    ),
    "engine/__init__.py": (
        "Package initialization file for the trading engine orchestration layer.",
        "Simplifies import pathways by exposing the primary Engine class from engine/core.py at the package level.",
        "Imported by main.py and compare.py to instantiate the application engine."
    ),
    "engine/base.py": (
        "Abstract Base Classes defining execution standards for exchange drivers and trading strategies.",
        "Establishes strict contracts for query methods (tickers, positions, orders) and transaction execution methods (orders, scaling). Establishes contracts for strategy modules to ingest market data and manage active trades.",
        "Inherited by BaseExchange drivers in engine/exchanges/ and BaseStrategy classes in strategies/."
    ),
    "engine/core.py": (
        "Unified trading loop manager and execution system coordinator.",
        "Manages the core asynchronous loops for periodic heartbeats, compounding equity monitoring, and strategy evaluations. Connects signals to the router, maintains active positions, logs performance stats, and performs startup legacy synchronization with exchanges.",
        "Instantiated by main.py and compare.py. Relies on SignalRouter and SimulationEngine/BitgetExchange to function."
    ),
    "engine/entry.py": (
        "Unified Signal Router executing orders across paper and live exchange interfaces.",
        "Parses standardized signal dictionaries emitted by strategies and directs execution handlers. Maps simulated OCO limit targets to the paper engine and maps live limit orders to REST API endpoints.",
        "Instantiated by Engine. Relies on BitgetExchange and SimulationEngine wrappers to place trades."
    ),
    "engine/simulation.py": (
        "Wrapper class integrating the mock trading simulator into the unified exchange interface.",
        "Adopts the standard BaseExchange abstract methods to execute and track orders in paper-mode. Proxies ticker snapshots and historical candles to database backfills and feeds real-time ticks into Simulator's order loops.",
        "Inherits from Simulator and BaseExchange. Instantiated by Engine when running in paper mode."
    ),
    "engine/exchanges/__init__.py": (
        "Exchange interface driver module exporter.",
        "Exposes the primary base class and implemented exchange drivers to the rest of the application.",
        "Imported by engine/core.py and engine/entry.py to load active exchange modules."
    ),
    "engine/exchanges/bitget.py": (
        "Production-ready Bitget V2 API exchange integration driver.",
        "Inherits from DataAcquisitionManager and coordinates real-time REST trading orders and public WebSocket feeds. Standardizes positions, order statuses, contract symbols, margins, and fills into the application's unified schema.",
        "Inherits from BaseExchange and DataAcquisitionManager. Instantiated by Engine for live and demo execution modes."
    ),
    "engine/exchanges/bingx.py": (
        "Placeholder exchange driver class for the BingX exchange.",
        "Declares empty driver interfaces for BingX contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "engine/exchanges/bitunix.py": (
        "Placeholder exchange driver class for the BitUnix exchange.",
        "Declares empty driver interfaces for BitUnix contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "engine/exchanges/blofin.py": (
        "Placeholder exchange driver class for the BloFin exchange.",
        "Declares empty driver interfaces for BloFin contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "engine/exchanges/coinex.py": (
        "Placeholder exchange driver class for the CoinEx exchange.",
        "Declares empty driver interfaces for CoinEx contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "engine/exchanges/dydx.py": (
        "Placeholder exchange driver class for the dYdX exchange.",
        "Declares empty driver interfaces for dYdX contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "engine/exchanges/hyperliquid.py": (
        "Placeholder exchange driver class for the Hyperliquid exchange.",
        "Declares empty driver interfaces for Hyperliquid contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "engine/exchanges/kucoin.py": (
        "Placeholder exchange driver class for the KuCoin exchange.",
        "Declares empty driver interfaces for KuCoin contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "engine/exchanges/margex.py": (
        "Placeholder exchange driver class for the Margex exchange.",
        "Declares empty driver interfaces for Margex contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "engine/exchanges/mexc.py": (
        "Placeholder exchange driver class for the MEXC exchange.",
        "Declares empty driver interfaces for MEXC contract trading. Serves as a reference skeleton for future integrations.",
        "Inherits from BaseExchange. Currently inactive and bypasses real-time routing."
    ),
    "strategies/__init__.py": (
        "Package initializer for the custom trading strategies layer.",
        "Exposes and documents the strategies namespace within the repository.",
        "Loaded dynamically during strategy discovery in main.py and backtest.py."
    ),
    "strategies/base_strategy.py": (
        "Abstract framework class for authoring backtestable multi-timeframe strategies.",
        "Implements common boilerplate for loading configuration contexts, validating historical warmups, checking reentry cooldowns, and executing ATR-based stop or target calculations.",
        "Base class for all strategies in strategies/built/ and strategies/sweeps/. Inherits from BaseStrategy interface."
    ),
    "strategies/scalper.1.jules.py": (
        "Jules high-frequency compounding scalper strategy.",
        "Harnesses moving average slopes, DRT momentum, and machine learning model predictions to execute tight scalps. Evaluates macro trends on higher timeframes and structures entry targets using ATR volatility.",
        "Relies on models.py and indicators in ta/. Loaded by main.py or backtest.py as a primary trading strategy."
    ),
    "strategies/built/levelFinder.1.agt.py": (
        "Multi-timeframe order block level finder and trade executor.",
        "Identifies institutional order blocks on 1m, 3m, 5m, and 15m intervals. Takes entries on solidified candle closures, with a three-way split take profit target model.",
        "Relies on ta/patterns/ob.py for pattern identification. Extensively backtested in multi-variant portfolios."
    ),
    "strategies/sweeps/killzone/killzone_sweep.1.mustafa.py": (
        "Killzone session liquidity sweep reversal strategy.",
        "Monitors specific London and New York session killzones to identify institutional liquidity sweeps. Captures rapid trend reversals when prices wick past local session extremes and close back inside the range.",
        "Relies on ta/patterns/sessions.py and ta/patterns/sweep.py."
    ),
    "strategies/sweeps/killzone/killzone_sweep_overnight.1.mustafa.py": (
        "Overnight session liquidity sweep reversal strategy.",
        "Identifies and monitors overnight session horizontal support/resistance boundaries. Places reversal trades when high volume surges wick outside these overnight levels and recover on low-timeframe structure breaks.",
        "Relies on ta/patterns/sessions.py and ta/patterns/sweep.py."
    ),
    "strategies/sweeps/range/range_sweep_ATR.1.mustafa.py": (
        "Volatility-adjusted range sweep strategy.",
        "Tracks price consolidation using rolling ATR volatility bands rather than time-based sessions. Enters positions on sweep-reversals of dynamically calculated ATR boundaries, filtering out over-extended parabolic moves.",
        "Relies on ta/patterns/sweep.py and ATR indicators."
    ),
    "ta/__init__.py": (
        "Initializer file for technical analysis package.",
        "Exposes feature extraction methods and indicator calculations.",
        "Imported by strategy modules and feature engines across the app."
    ),
    "ta/features.py": (
        "Stateless feature extraction module.",
        "Pulls indicators and SMC patterns into a unified feature matrix dictionary representing active market conditions.",
        "Invoked statelessly by engine simulators or real exchange modules before score calculations."
    ),
    "ta/scoring.py": (
        "Unified Scoring Engine evaluating and weighting technical metrics.",
        "Gathers all the technical indicators and evaluates them into normalized directional/non-directional scores. Resolves denominator dilution by separating directional scores from quality penalties.",
        "Imported by Engine. Crucial gatekeeper determining whether to enter buy or sell positions."
    ),
    "ta/levels.py": (
        "Technical support and resistance horizontal price level locator.",
        "Locates local swing peak and trough extremes with tie-breakers, clusters them based on range budget spreads, and checks chronological candle closes to identify level breakout states.",
        "Utilized by support/resistance trading strategies and point-of-interest filters."
    ),
    "ta/strategy_interface.py": (
        "Abstract specification interface for simple technical strategies.",
        "Defines expected signature for get_signal() on historical candles data.",
        "Provides contract definitions for lightweight modular signal detectors."
    ),
    "ta/utils.py": (
        "General math, rolling window, and localized timezone converters.",
        "Provides SMA, EMA, and timezone helper tools. Translates exchange UTC timestamps to America/Toronto for accurate session mapping.",
        "Imported by almost all indicators and session detection modules."
    ),
    "ta/candles/engulfing.py": (
        "Stateless pattern recognizer for body-only engulfing candles.",
        "Identifies engulfing candlestick signals where only the body overlaps the previous bar body. Disregards candle wicks for a conservative entry signal.",
        "Utilized by candle patterns analysis and indicators features pipeline."
    ),
    "ta/candles/engulfing_total.py": (
        "Stateless pattern recognizer for total candle engulfing.",
        "Identifies aggressive engulfing setups where the active candle body completely engulfs both the previous body and wicks.",
        "Utilized by candle patterns analysis and indicators features pipeline."
    ),
    "ta/candles/sentiment.py": (
        "Stateless pattern recognizer analyzing body location inside candle range.",
        "Classifies candle sentiment based on whether the candle body is located in the top, bottom, or middle of the full range.",
        "Utilized by candle patterns analysis and indicators features pipeline."
    ),
    "ta/indicators/adx.py": (
        "Average Directional Index (ADX) trend strength calculator.",
        "Computes ADX and directional indicators (+DI, -DI) over rolling periods to measure macro trend strength.",
        "Imported by feature extraction modules to filter out weak-trending configurations."
    ),
    "ta/indicators/atr.py": (
        "Average True Range (ATR) volatility series calculator.",
        "Measures market volatility using rolling ATR calculations to dynamically determine protective stop and profit targets.",
        "Imported by strategies and features layers to scale risk and exits."
    ),
    "ta/indicators/book_delta.py": (
        "Order book quantity volume imbalance delta calculator.",
        "Calculates volume imbalances between the top bids and asks inside the active order book.",
        "Used by scoring and feature extraction components to gauge short-term micro liquidity pressure."
    ),
    "ta/indicators/cvd.py": (
        "Cumulative Volume Delta (CVD) rolling series calculator.",
        "Tracks aggressive buying and selling volume deltas accumulated over a rolling time window.",
        "Used by feature extraction and scoring modules to measure institutional order flow direction."
    ),
    "ta/indicators/ema.py": (
        "Exponential Moving Average (EMA) mathematical indicator.",
        "Calculates standard fast and slow EMAs to verify trend directions and moving crossovers.",
        "Used as a core trend filter across many SMC and sweep strategies."
    ),
    "ta/indicators/flow.py": (
        "Order Flow and aggressive trade pressure analyzer.",
        "Monitors trade streams to compute aggregated buy and sell volume velocity changes.",
        "Used to identify active institutional interest blocks and volume surges."
    ),
    "ta/indicators/macd.py": (
        "Moving Average Convergence Divergence (MACD) oscillator.",
        "Computes MACD lines, signal curves, and hist slopes to spot momentum shifts and reversals.",
        "Used by the ScoringEngine as a heavy-weighted indicator of price momentum."
    ),
    "ta/indicators/rsi.py": (
        "Relative Strength Index (RSI) momentum oscillator.",
        "Measures speed and change of price movements to identify overbought and oversold conditions.",
        "Used by mean-reversion strategies and momentum filters."
    ),
    "ta/indicators/supertrend.py": (
        "Average True Range (ATR) based trailing Supertrend calculator.",
        "Computes upper and lower bands to output active trend directions and stop placement levels.",
        "Injected as a key trend feature evaluated by the ScoringEngine."
    ),
    "ta/indicators/vd.py": (
        "Volume Delta single-period buyer/seller velocity calculator.",
        "Measures difference between aggressive buying volume and aggressive selling volume for individual periods.",
        "Provides base data series utilized by the Cumulative Volume Delta indicator."
    ),
    "ta/patterns/__init__.py": (
        "Package initializer for Smart Money Concepts (SMC) technical patterns.",
        "Exposes and indexes various stateless pattern discovery submodules (like order blocks, breaker blocks, liquidity pools, and FVGs) at the patterns package level.",
        "Loaded by feature extraction pipelines to compute pattern matrices."
    ),
    "ta/patterns/breaker.py": (
        "Failed Order Block (Breaker Block) stateless pattern recognizer.",
        "Identifies order blocks whose polarity has failed and flipped due to strong counter-trend breakout closes exceeding invalidation margins.",
        "Provides stateless pattern data used by SMC features extraction."
    ),
    "ta/patterns/drt.py": (
        "Directional Trend (DRT) linear regression slope calculator.",
        "Performs linear regression on candle closes to calculate price velocity and acceleration curves.",
        "Extremely strong predictor evaluated with high weight by the ScoringEngine."
    ),
    "ta/patterns/fvg.py": (
        "Fair Value Gap (FVG) stateless recognition module.",
        "Spots imbalances across 3-candle structures where price delivered too rapidly, leaving a gap between wicks.",
        "Used to map liquidity vacuums and draw-on-liquidity zones."
    ),
    "ta/patterns/idm.py": (
        "Smart Money Concept Inducement (IDM) stateless recognizer.",
        "Identifies inducement wicks that trigger premature retail entries before institutional market moves.",
        "Used by SMC strategies to bypass fake breakout traps."
    ),
    "ta/patterns/liquidity.py": (
        "Buy-Side (BSL) and Sell-Side (SSL) liquidity pool mapper.",
        "Identifies price levels containing clustered stop-losses located above swing highs and below swing lows.",
        "Utilized by sweep strategies to target logical take-profit locations."
    ),
    "ta/patterns/momentum.py": (
        "Short-term volume surges and delivery speed shifts detector.",
        "Spots momentum thrusts and aggressive institutional candle sizes.",
        "Used by the feature layer to flag high-liquidity breakouts."
    ),
    "ta/patterns/ob.py": (
        "Stateless Order Block (OB) identification module.",
        "Locates institutional buying/selling block areas with ATR-based warmup and mitigation checks.",
        "Crucial stateless pattern-discovery module used by Agt levelFinder strategies."
    ),
    "ta/patterns/phases.py": (
        "Market consolidation and expansion phases recognizer.",
        "Classifies market cycles into Accumulation, Manipulation, and Distribution states.",
        "Provides macro context for timing reversal vs breakout setups."
    ),
    "ta/patterns/poi.py": (
        "High-probability Point of Interest (POI) confluence engine.",
        "Unites overlapping Order Blocks, FVGs, and Liquidity Pools into unified POI zones.",
        "Used by institutional strategies to locate optimal entry zones."
    ),
    "ta/patterns/sessions.py": (
        "Trading session boundaries and horizontal extreme tracker.",
        "Computes London, New York, and Tokyo trading ranges with anchor timestamps.",
        "Relied upon by Killzone and session-sweep strategies."
    ),
    "ta/patterns/spread.py": (
        "Statistical Arbitrage (Spread Divergence) detector.",
        "Measures relative divergences between highly correlated asset pairs.",
        "Provides override signals enabling stat-arb trades during correlation blocks."
    ),
    "ta/patterns/sr.py": (
        "Horizontal Support and Resistance locator.",
        "Detects horizontal floors and ceilings based on historical candle touch frequencies.",
        "Provides baseline zones for breakout and bounce strategies."
    ),
    "ta/patterns/structure.py": (
        "Market Structure breaks (BOS, MSS, CHOCH) tracker.",
        "Monitors local swings to identify breaks of structures, confirming trend reversals.",
        "Highly useful for validating structural alignments before entries."
    ),
    "ta/patterns/sweep.py": (
        "Liquidity sweep and wick stop-hunt detector.",
        "Identifies candle wicks that pierce past local extremes but close back inside the range, signifying a stop hunt.",
        "The underlying technical foundation of all sweep strategies."
    ),
    "ta/patterns/sweep_reversal.py": (
        "Session Sweep Reversal signal calculator.",
        "Computes entry triggers once a session sweep completes and a low-timeframe market structure shift confirms.",
        "Provides signal logic for advanced session-based strategies."
    ),
    "ta/patterns/swings.py": (
        "Local Swing High and Swing Low peak extreme detector.",
        "Performs peak/trough local extreme search with tie-breakers to find clean swing points.",
        "Foundation module for mapping market structure, liquidity, and support/resistance zones."
    ),
    "ta/patterns/trend.py": (
        "Trend direction and market bias recognition system.",
        "Synthesizes multiple indicators to determine overall trend bias.",
        "Provides macro bias features evaluated with high weight by the ScoringEngine."
    ),
    "ta/patterns/volume_profile.py": (
        "Intraday volume profiling and POC finder.",
        "Identifies High Volume Nodes and the Point of Control across historical cycles.",
        "Used to verify price areas of heavy interest and horizontal support."
    ),
    "tools/add_headers_auto.py": (
        "Automated 3-part header comment applier.",
        "Loops through a pre-defined mapping of file paths to their respective summaries, descriptions, and contexts. Strips any pre-existing leading module docstrings from target Python files or shebang-prefixed launcher scripts, and inserts standard 3-part comments at the top of each.",
        "Used to automate the execution of Part A file headers. Can be run repeatedly to refresh file docstrings deterministically."
    ),
    "tools/analyze_btc_session.py": (
        "Analyzes Bitcoin price correlation with session-specific trading volumes.",
        "Queries and visualizes Bitcoin price movements during global market session overlaps.",
        "Helper diagnostic tool for optimizing BTC-related trend configurations."
    ),
    "tools/analyze_data.py": (
        "Visualizes and logs metrics of historical candles.",
        "Reads SQLite candle records and renders trend indicators.",
        "Diagnostic telemetry script for qualitative testing."
    ),
    "tools/analyze_data_v2.py": (
        "Secondary data visualizer for technical indicator telemetry.",
        "Constructs plots of EMA, MACD, and volume deltas over historical candles.",
        "Diagnostic script for optimizing technical criteria."
    ),
    "tools/analyze_latest_session.py": (
        "Summarizes trading stats and order logs from the most recent run.",
        "Reads local log files and prints trade performance tables.",
        "Helper script for quick post-run telemetry evaluation."
    ),
    "tools/check_api.py": (
        "Verifies exchange connectivity and API REST credentials.",
        "Signs and dispatches standard REST queries to check API permissions.",
        "Crucial debugging helper used during live connection setups."
    ),
    "tools/comprehensive_analysis.py": (
        "Consolidated trade history log metrics analyzer.",
        "Aggregates CSV/text telemetry output files to calculate win rates and drawdowns.",
        "Used for offline quant research and performance validation."
    ),
    "tools/debug_atr_expansion.py": (
        "Tests and debugs ATR-based volatility expansion capping.",
        "Simulates hyper-extended moves and tracks strategy rejection behavior.",
        "Validates that ATR volatility ceilings function correctly."
    ),
    "tools/downloader.py": (
        "Historical OHLCV data downloader from Bitget REST endpoints.",
        "Retrieves multi-timeframe candles and populates the local SQLite database.",
        "Core acquisition tool ensuring offline backtests have rich historical data."
    ),
    "tools/extract_docs.py": (
        "Internal utility script to pull and print existing docstrings from Python modules.",
        "Walks target files and parses AST representations to extract top-level docstrings.",
        "Used for code analysis and metadata audits."
    ),
    "tools/generate_map.py": (
        "Repository map JSON generator.",
        "Walks the working tree, ignores excluded directories/files (such as dependencies, VCS metadata, database files, and markdown documentation), and extracts the one-line Part A summary from every hand-authored source file. Builds a flat JSON array indexing paths, raw GitHub URLs pointing to the development branch, and their descriptions, then serializes it to docs/map.json.",
        "Runs standalone or as part of verification workflows. Relies on Git commands to retrieve owner and repository telemetry."
    ),
    "tools/list_targets.py": (
        "Internal utility script to count and list all files in scope for metadata headers.",
        "Analyzes directory layouts and filters out VCS, build, and test artifacts.",
        "Used during build audits and repository mapping."
    ),
    "tools/logger.py": (
        "Implements dual console/file logging pipelines with timezone and virtual timestamp prefixes.",
        "Provides a Tee class to capture console stdout and writes detailed metrics/signals to temp directories.",
        "Crucial logging module supporting dual real-time and backtest virtual-time logging."
    ),
    "tools/optimize_btc_thresholds.py": (
        "Runs parameter grid-searches to identify optimal Bitcoin momentum threshold parameters.",
        "Sweeps BTC momentum targets and evaluates trade outcomes over history.",
        "Used by quant analysts to tune trend filters."
    ),
    "tools/publisher.py": (
        "Console Publisher for uniform application outputs.",
        "Formats and prints standard heartbeats, order placements, fills, and position closures.",
        "Provides beautiful, standardized terminal output across all simulator and backtest modes."
    ),
    "tools/test_levels.py": (
        "Regression tests for horizontal support/resistance level clustering.",
        "Runs assertions against swing points, clustering spread budgets, and breakout logic.",
        "Verifies the stability of ta/levels.py."
    ),
    "tools/test_ob_breaker.py": (
        "Tests stateless pattern-discovery for order blocks and breaker blocks.",
        "Verifies ATR warmups, relative doji caps, and chronological validations.",
        "Guarantees that OB and breaker block detections are free of look-ahead bias."
    ),
    "tools/test_order_pnl_reconciliation.py": (
        "Reconciles math behind gross wins, transaction fees, and net profits.",
        "Checks Simulator OCO limit arithmetic and maker/taker calculations.",
        "Ensures PnL reports accurately account for all transaction costs."
    ),
    "tools/test_scoring.py": (
        "Validates that ScoringEngine score distributions align with weights and thresholds.",
        "Tests penalty offsets, directional multipliers, and entry decisions.",
        "Guarantees correct operation of the continuous scoring pipeline."
    ),
    "tools/test_symbols.py": (
        "Verifies Bitget API asset discovery and caching features.",
        "Performs async calls to check market specifications and local contract listings caching.",
        "Guarantees that symbol caches function without network latency."
    ),
    "tools/test_vd_cvd.py": (
        "Checks Volume Delta and Cumulative Volume Delta numerical boundaries.",
        "Verifies that CVD computations are robust against missing values and NaN extremes.",
        "Validates correct execution of aggression indicators."
    ),
    "tools/trading_utils.py": (
        "Houses centralized calculations for order rounding, price precision, and net profit subtraction.",
        "Provides precision handlers ensuring order sizes and prices conform to exchange limits.",
        "Imported by simulators and engines to standardise rounding operations."
    ),
    "tools/verify_headers.py": (
        "Validator verifying all target files contain correct 3-part headers.",
        "Parses the AST representation of Python files and checks launcher files to verify they contain Summary, Description, and Context tags matching our Part A standards.",
        "Runs as a final validation pass."
    ),
    "tools/verify_pnl_calculations.py": (
        "Double-checks compounding equity calculations after fee deductions.",
        "Validates reinvestment percentages and risk margins on a simulated account.",
        "Used to test capital growth models."
    ),
    "tools/verify_pnl_calculations_v2.py": (
        "Secondary tester validating backtest OCO fill arithmetic.",
        "Validates simulation execution edge cases.",
        "Diagnostic validation script."
    ),
    "tools/verify_pnl_calculations_v3.py": (
        "Tertiary validator ensuring simulator PnL calculations match live ledger results.",
        "Validates fee-deducted gross-to-net equations against realistic account ledgers.",
        "Verifies math accuracy."
    ),
    "tools/verify_rrr.py": (
        "Confirms risk-to-reward ratio targets and break-even stop moves function under slippage.",
        "Simulates stop movements and exit targets to verify risk compliance.",
        "Verifies correct operation of partial-take profit splits."
    ),
    "tools/list_targets.py": (
        "Internal utility script to count and list all files in scope for metadata headers.",
        "Analyzes directory layouts and filters out VCS, build, and test artifacts.",
        "Used during build audits and repository mapping."
    ),
    "tools/extract_docs.py": (
        "Internal utility script to pull and print existing docstrings from Python modules.",
        "Walks target files and parses AST representations to extract top-level docstrings.",
        "Used for code analysis and metadata audits."
    )
}

def clean_docstring_from_python(content):
    """
    Remove leading module-level docstring from Python content if it exists.
    Returns cleaned content and any remainder.
    """
    lines = content.split('\n')
    # Find if there is an existing docstring at the very top.
    # We can skip blank lines or comments first.
    idx = 0
    while idx < len(lines) and (lines[idx].strip() == '' or lines[idx].strip().startswith('#')):
        idx += 1

    if idx >= len(lines):
        return content

    line = lines[idx].strip()
    if line.startswith('"""') or line.startswith("'''"):
        quote_char = '"""' if line.startswith('"""') else "'''"
        # Find where it ends
        end_idx = idx
        # If it's a single-line docstring
        if line.endswith(quote_char) and len(line) >= 6:
            # e.g., """hello"""
            lines = lines[:idx] + lines[idx+1:]
            return '\n'.join(lines)

        # Multi-line docstring
        # Let's find the closing quote
        found = False
        while end_idx < len(lines):
            if end_idx == idx:
                # check rest of the line
                rest = lines[end_idx][len(quote_char):]
                if quote_char in rest:
                    found = True
                    break
            else:
                if quote_char in lines[end_idx]:
                    found = True
                    break
            end_idx += 1

        if found:
            lines = lines[:idx] + lines[end_idx+1:]
            return '\n'.join(lines)

    return content

def apply_headers():
    print(f"Applying headers to {len(HEADERS_MAP)} target files...")

    for rel_path, (summary, desc, context) in HEADERS_MAP.items():
        if not os.path.exists(rel_path):
            print(f"Skipping non-existent file: {rel_path}")
            continue

        with open(rel_path, 'r', encoding='utf-8') as f:
            content = f.read()

        is_python_file = rel_path.endswith('.py')
        is_launcher_file = rel_path in ['backtest', 'compare', 'main']

        new_content = ""

        if is_launcher_file:
            # Find the shebang
            lines = content.split('\n')
            if lines and lines[0].startswith('#!'):
                shebang = lines[0]
                remainder = '\n'.join(lines[1:])
                # Clean any previous launcher header
                # We'll strip any leading # lines that are part of a header
                rem_lines = remainder.split('\n')
                rem_idx = 0
                while rem_idx < len(rem_lines) and (rem_lines[rem_idx].strip() == '' or rem_lines[rem_idx].strip().startswith('#')):
                    # check if it's the start of python imports. If it is, stop.
                    stripped = rem_lines[rem_idx].strip()
                    if stripped.startswith('import') or stripped.startswith('from') or stripped.startswith('try:'):
                        break
                    rem_idx += 1
                cleaned_rem = '\n'.join(rem_lines[rem_idx:])

                header_str = (
                    f"{shebang}\n"
                    f"# 1. Summary: {summary}\n"
                    f"# 2. Description: {desc}\n"
                    f"# 3. Context: {context}\n"
                    f"{cleaned_rem}"
                )
                new_content = header_str
            else:
                header_str = (
                    f"# 1. Summary: {summary}\n"
                    f"# 2. Description: {desc}\n"
                    f"# 3. Context: {context}\n"
                    f"{content}"
                )
                new_content = header_str

        elif is_python_file:
            # Strip previous docstrings safely
            cleaned = clean_docstring_from_python(content)

            # Construct standard 3-part docstring
            docstring_str = (
                f'"""\n'
                f'1. Summary: {summary}\n'
                f'2. Description: {desc}\n'
                f'3. Context: {context}\n'
                f'"""\n'
            )

            # Combine
            new_content = docstring_str + cleaned.lstrip()

        else:
            print(f"Warning: Unknown file type for {rel_path}")
            continue

        # Overwrite the file with new_content
        with open(rel_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        print(f"Applied header to: {rel_path}")

if __name__ == "__main__":
    apply_headers()
