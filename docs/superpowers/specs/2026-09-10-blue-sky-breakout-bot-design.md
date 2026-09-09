# Blue Sky Breakout Bot — Design Spec

Status: approved by user 2026-09-10
Source spec: `blue-sky-breakout-bot-spec.md` (repo root)

## 1. Purpose & scope

Build a console-based (no web UI) trading-automation bot that implements the
"Blue Sky" breakout strategy defined in `blue-sky-breakout-bot-spec.md`,
starting in **paper-trading mode only**. Live order placement is explicitly
out of scope for this build — the source spec itself (§6) requires a full
quarter of paper trading before real capital is risked, and the user's
immediate goal is "test the bot for a few weeks" before going live. The
broker-execution layer is designed with a slot for a live executor, but that
executor is not implemented in this phase.

## 2. Key decisions (resolved during brainstorming)

- **Market**: Indian equities (NSE/BSE), per BananaPatterns' own scope
  (confirmed via bananapatterns.com — "a stock screening, charting and
  market-analytics platform for Indian equities"). The ₹10,00,000 reference
  capital in the source spec is consistent with this.
- **Signal intake**: Manual. BananaPatterns' Terms of Use prohibit automated
  access at scale; the user asked to scrape it anyway, and that request was
  declined — this design does not build a scraper. Instead, the user reads
  the day's Fresh Breakouts / Climbing lists off bananapatterns.com
  themselves and types the candidate data into the console (symbol, pivot
  price, RS rating, current price, 50-day MA). A self-built independent
  breakout/RS screener (option (b) in source-spec §7) is noted as a possible
  future project, not part of this build.
- **Price data feed**: Zerodha Kite Connect market-data API (historical
  candles + LTP), used for 50-day MA computation, stop-breach checks, and
  simulating fills — used identically whether the bot is later switched to
  live mode.
- **Future live broker**: Zerodha (Kite Connect), when/if the user decides to
  go live. Not implemented in this phase.
- **Persistence**: SQLite (not flat CSV/JSON) — chosen for transactional
  safety (a crash mid-write must not corrupt the position log, which matters
  for the reconciliation-halt requirement in source-spec §6) and for easy
  querying when building the daily summary / equity curve / trade history.
- **Invocation model**: On-demand console command run by the user each
  evening after market close — not a background scheduler/daemon. This
  matches "keep it simple console interface" and preserves the human-approval
  gate (source-spec §6) before any order (simulated or real) is submitted.

## 3. Architecture & components

Python 3.11+, using the official `kiteconnect` SDK and stdlib `sqlite3` (no
other required runtime dependencies beyond those two + `python-dotenv` for
config loading).

```
bot/
  config.py           Loads Kite API key/secret + strategy params from .env
  models.py           Dataclasses: Candidate, Position, Trade, PendingOrder
  storage.py          SQLite wrapper: positions, pending_orders, trade_log,
                       equity_history, kill_switch tables
  market_data.py       Wraps Kite historical-candles + LTP endpoints;
                       computes 50-day MA per symbol. Read-only.
  broker_executor.py   BrokerExecutor interface (submit_entry, submit_exit,
                       get_account_equity, get_broker_positions).
                       PaperExecutor: only implementation this phase.
                       KiteLiveExecutor: stub, raises NotImplementedError.
  sizing.py            Position sizing formula (source-spec §5)
  exit_rules.py        Hard-stop / 50-DMA trailing logic (source-spec §4)
  candidate_input.py   Console prompts for manual candidate entry + validation
  risk_controls.py     Kill switch, reconciliation check, daily loss limit,
                       gap-fill detection/alert
  workflow.py          Orchestrates the full daily cycle (source-spec §3)
  cli.py               Console menu / entrypoint
main.py                Entrypoint: `python main.py`
.env.example           Template for Kite API key/secret (never commit .env)
requirements.txt
tests/
  test_sizing.py
  test_exit_rules.py
  test_workflow.py     Uses fake MarketData + fake BrokerExecutor
```

Each unit has one clear responsibility and a narrow interface: `market_data`
and `broker_executor` are the only modules that talk to Kite; everything else
is pure logic or console I/O, which is what makes `workflow.py` testable
without hitting the network.

## 4. Daily workflow (data flow)

User runs `python main.py`, selects "Run daily cycle." Steps, in order:

1. **Load state** from SQLite: open positions, pending orders, equity, kill
   switch. If the kill switch is on, skip straight to the summary — no new
   entries are proposed.
2. **Resolve pending orders first.** Any buy-stop queued from a prior day's
   selection is checked against *today's* actual OHLC (via Kite): if today's
   high ≥ pivot, simulate a fill — at the pivot price, or at today's open if
   price gapped above the pivot (flagged as a gap-fill event). On fill, queue
   the initial stop at `fill_price × 0.93` and log the trade. A pending order
   unmatched for 5 sessions is dropped (mirrors the "fresh breakouts in the
   last 5 sessions" window from source-spec §2); this default is
   configurable.
3. **Evaluate exits** for all open positions using today's close + 50-day MA,
   exactly per source-spec §4 (fixed 7% stop until a close above the 50-DMA
   has occurred at least once since entry; from then on, trail the 50-DMA;
   never reverts to the fixed stop).
4. **Show proposed exits, require confirmation** (even in paper mode — this
   rehearses the human-approval habit source-spec §6 requires before live
   submission), then simulate fills, update equity, write the trade log.
5. **Recompute open slots** = 8 − open positions after exits. If 0, skip to
   the summary.
6. **Prompt for today's candidates**: user types in each Fresh Breakout
   (symbol, pivot, RS, current price, 50-day MA). Bot drops symbols already
   held and anything below the configured RS floor (default ≥70), ranks the
   rest by RS descending, and selects the top N = open slots. Unfilled slots
   stay in cash — no forced trades.
7. **Size selections** (source-spec §5 formula, off current paper-book
   equity), **show proposed entries, require confirmation**, then queue as
   pending buy-stop orders for the next session (or simulate an immediate
   fill if the user indicates price already cleared the pivot at scan time).
8. **Print daily summary**: fills, exits with P&L, candidates skipped because
   the book was full (with RS, so the user can see what was passed up),
   current equity, drawdown from equity peak.

## 5. Risk controls & error handling

- **Reconciliation halt**: in paper mode there is no external broker truth to
  diverge from, so this guards against internal state corruption (e.g. a
  position row missing an expected field) rather than broker/log mismatch.
  It becomes fully meaningful once a live executor exists.
- **Gap protection**: a pending order filling materially above pivot, or an
  exit triggering materially below its stop, is explicitly flagged in the
  daily summary rather than silently absorbed into P&L.
- **Daily loss limit**: a configurable % of equity lost in one session
  automatically trips the kill switch and blocks new entries until manually
  cleared.
- **Kill switch**: a console command flips a persisted SQLite flag. While on,
  the workflow always skips straight to the summary.
- **Kite API failures** (rate limit, expired access token, network error):
  caught per-symbol. A symbol that fails to fetch is reported as "data
  unavailable, skipped this cycle" rather than crashing the run or being
  silently treated as unchanged.
- **Kite auth**: Kite Connect access tokens expire daily and require a
  login/token-exchange flow. `config.py` handles refreshing/prompting for a
  new token when the stored one has expired; the user must have their own
  Kite Connect API key/secret (paid subscription, registered with Zerodha)
  before real market data can be pulled.

## 6. Testing approach

- `sizing.py` and `exit_rules.py`: unit tests as pure functions, covering
  edge cases (exactly-at-MA, gap-through-stop, tie-breaking on RS).
- `workflow.py`: tested against a fake `MarketData` and fake `BrokerExecutor`
  (no real Kite calls), verifying the full daily-cycle logic — pending-order
  carry-over across days, exit-before-entry ordering, slot recomputation,
  RS-floor/rank/select — deterministically against scripted price sequences.
- No live/paper distinction is tested at the Kite-integration layer in this
  phase, since `KiteLiveExecutor` is unimplemented; `market_data.py`'s real
  Kite calls are exercised manually/by the user once they have API
  credentials, not by the automated test suite.

## 7. Explicitly out of scope (this phase)

- Live order placement (`KiteLiveExecutor` is a stub only).
- Automated/scraped signal sourcing from BananaPatterns.
- Self-built breakout/RS screener against raw price data.
- Tax, brokerage, and slippage modeling in simulated P&L.
- Corporate actions handling (splits, bonuses, delisting, symbol changes).
- Web UI of any kind — console only, per explicit user request.
