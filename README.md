# Blue Sky Breakout Bot (Paper Trading)

Console bot implementing the Blue Sky breakout strategy from
`blue-sky-breakout-bot-spec.md`. **Paper trading only** — no live orders are
placed in this phase.

## Setup

1. `pip install -r requirements.txt`
2. Register an app at https://developers.kite.trade to get a Kite Connect
   API key and secret (requires an active Kite Connect subscription).
3. Copy `.env.example` to `.env` and fill in `KITE_API_KEY` / `KITE_API_SECRET`.
4. `python main.py`, then choose `0) Refresh Kite login token` — this opens a
   login URL, you log in via Zerodha in your browser, then paste the
   `request_token` from the redirect URL back into the console. This is
   required once per day (Kite access tokens expire daily).
5. Choose `1) Run daily cycle` each evening after market close. You'll be
   prompted to type in that day's Blue Sky Fresh Breakout candidates
   (symbol, pivot price, RS rating, current price, 50-day MA) as read from
   bananapatterns.com yourself.

## What this does NOT do (yet)

- Place live orders — `KiteLiveExecutor` is a stub.
- Scrape or automate access to bananapatterns.com.
- Model taxes, brokerage, or slippage in simulated P&L.

## Post-implementation notes for the user

- Before running for real, you need your own Kite Connect API key/secret
  (paid Zerodha developer subscription) and to complete the daily login flow
  (menu option `0`).
- The bot starts with `starting_capital` (₹10,00,000 default) as simulated
  cash the first time it runs (no existing equity history in `bot_state.db`).
- Delete `bot_state.db` to reset the paper-trading book from scratch.
- Per source-spec §6, run this in paper mode for at least a full quarter
  before considering live capital, and treat `KiteLiveExecutor` as a
  separate future project requiring its own design/plan cycle.
