# Real option chains (idea 2) — MarketData.app free plan

Status (26 Nov 2026): LIVE. Two live tests passed (second: full 45-day chain for 5 credits,
no IP lock). Wired in: Desk Ledger method/chains_script holds this script (update it whenever
chains.py changes); meta/book rules now use real prices; the close scorecard writes new trades
as "pending"; the midday run fills them at the decision day's closing quotes, marks open ones,
applies the 80% take-profit and writes meta/chains and days/<date>.options.
First possible fill: Mon 30 Nov midday, for a trade decided at the Fri 27 Nov close.

## Why MarketData.app
- Cboe's site terms bar storing their data or building on it without written consent.
- Yahoo/yfinance terms bar it too. Alpha Vantage options need a paid plan.
- Alpaca's free feed is for US residents only; Rk is in Canada.
- MarketData.app "Free Forever": 100 credits/day; chains include bid/ask, IV, greeks, open
  interest; free data is the prior session (24h delayed). Terms (updated 6 Nov 2026): personal
  non-professional use; may store on devices you control; automation allowed; no restriction on
  derived data; no redistribution or copying their database. No country restriction found.
- Unverified: how many credits one chain request costs on the free plan. Check on first run.

## Setup (Rk, once)
1. Sign up at https://www.marketdata.app/pricing/ (Free Forever) and copy the API token.
2. Project settings → Cloud environment → gear → Network secrets: host `api.marketdata.app`,
   header `Authorization`, value `Bearer <token>`. Never paste the token into chat.
   (api.marketdata.app is already on the network allowlist.)

## Use
    python analyses/desk/chains.py summary            # derived chain numbers, JSON
    python analyses/desk/chains.py price --expiry YYYY-MM-DD --legs '[[1,"P",700],[-1,"P",690]]'
    python analyses/desk/chains.py selftest           # offline maths check (synthetic)
    (--source alpaca keeps the Alpaca path for US users.)

## Limits found in the live test (26 Nov) and how the code handles them
- Credits: about 1 credit per contract returned (one 21-day, +/-8% pull cost ~2,040).
  Trial: 100,000/day (reset 09:30 ET). Free plan after the trial: 100/day.
- One-device lock: MarketData.app locks the account for ~5 minutes when the calling IP changes,
  and the cloud's outbound IP can change between requests.
- So each run makes ONE request: `summary --budget <last limit> --legs ...` returns the chain
  stats, the book's leg prices and the credit headers together. On a one-device 403 it waits
  5.5 minutes and retries once, then stops (never guesses).
- Billing trick (MarketData.app chain docs, 12 Nov 2026): a historical pull with `date` costs
  1 credit per 1,000 contracts, versus 1 per contract without it. Free data is the prior session
  anyway, so the script always sends `date` (the latest released session). A full 21-day chain
  should cost ~2-3 credits, so it fits the 100/day free plan too, gamma included.
  IV and greeks may come back empty on historical pulls; the script computes its own from mids.
- `--budget` (from the last run's `credits.limit`) only drops to a narrow pull if under 10.
- Rk should avoid using the same token from another device during desk run times.

## Timing: the 24h delay
Free data for session D becomes available after 09:30 ET on D+1. So:
- Close run (16:47, day D) decides a paper trade as today.
- Midday run (12:47, day D+1) fetches D's closing chain and books the fill at D's real closing
  quotes, and marks open positions at D's close. Book marks lag one session.
- Chain stats (ATM IV, skew, gamma) in days/{D} are filled the next midday.

## Proposed paper-book pricing rule (replaces the Black-Scholes rule once live)
"Prices come from MarketData.app's free SPY chain (prior session's closing quotes): fills at
mid plus half the bid/ask width on every leg, in and out; marks at mid. A trade decided at
day D's close is filled at D's closing quotes, booked the next session. If a leg has no usable
quote, price it with Black-Scholes using the chain's ATM IV and fitted skew slopes, and flag
the trade 'model-priced'."

## Desk uses
- days/{date}.options: atm_iv, skew_25d, implied_move_pct (front weekly), gamma
  {gex_usd_per_1pct, gamma_sign, flip_level, call_wall, put_wall, oi_as_of}.
- prob_base can use the chain's ATM IV for the call's expiry instead of VIX.
- Gamma sign is an estimate under the usual "dealers long calls, short puts" assumption.
