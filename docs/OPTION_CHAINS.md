# Real option chains (idea 2) — Alpaca free data

Status (26 Nov 2026): code built and self-tested on synthetic data. Not yet run on live
data: waiting for Rk's free Alpaca keys.

## Why Alpaca
- Cboe's site terms bar storing their data or building on it without written consent.
- Yahoo/yfinance terms bar it too. Alpha Vantage options need a paid plan.
- Alpaca's free Basic plan includes US options on the "indicative" feed (15-min delayed,
  quotes "modified", not real OPRA). Terms: personal, non-commercial use; no republishing.
  So the desk stores only derived numbers (prices of its own paper trades, IV, skew, gamma),
  never raw chains.

## Setup (Rk, once)
1. Open a free Alpaca account (paper trading only, no money). Terms say the service is
   intended for US residents.
2. In the paper account, generate API keys.
3. In Project settings → Cloud environment → gear → Network secrets, add for BOTH hosts
   data.alpaca.markets and paper-api.alpaca.markets:
   - header `APCA-API-KEY-ID` = key id
   - header `APCA-API-SECRET-KEY` = secret
   Never paste keys into chat. The two hosts are already on the network allowlist.

## Use
    python analyses/desk/chains.py summary            # derived chain numbers, JSON
    python analyses/desk/chains.py price --expiry YYYY-MM-DD --legs '[[1,"P",700],[-1,"P",690]]'
    python analyses/desk/chains.py selftest           # offline maths check (synthetic)

## Proposed paper-book pricing rule (replaces the Black-Scholes rule once live)
"Prices come from Alpaca's free indicative SPY chain (15-min delayed, modified quotes):
fills at mid plus half the bid/ask width on every leg, in and out; marks at mid. If any leg
has no usable quote, price that leg with Black-Scholes using the chain's ATM IV and its
fitted skew slopes, and flag the trade 'model-priced'. Never store raw quotes."

## Desk uses
- days/{date}.options: atm_iv, skew_25d, implied_move_pct (front weekly), gamma
  {gex_usd_per_1pct, gamma_sign, flip_level, call_wall, put_wall, oi_as_of}.
- prob_base can use the chain's ATM IV for the call's expiry instead of VIX.
- Gamma sign is an estimate under the usual "dealers long calls, short puts" assumption.
