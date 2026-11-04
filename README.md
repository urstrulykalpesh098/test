# marketsim

An agent-based market simulator where the crowd is made of **traders**, not
generic people. You describe a future situation (a rate surprise, a liquidity
crunch, a fraud revelation...) as a scenario file. Hundreds of trading agents
with different strategies then react to it through a real limit order book.
You get a report showing how price, liquidity and each trader type's P&L play
out, across many random runs.

## Privacy by design

- **Runs 100% locally.** Pure Python standard library, so there is nothing to
  install and no third-party packages.
- **No network calls, no API keys, no telemetry.** Scenarios and results never
  leave the machine it runs on.
- Reports are written to `reports/`, which is git-ignored so results are not
  committed by accident.
- Scenarios hold market assumptions only. Don't put personal or account data
  in them; nothing in the simulator needs it.

## Quick start (Python 3.10+)

```bash
python -m marketsim list                                  # bundled scenarios
python -m marketsim traders                               # trader types and parameters
python -m marketsim run rate_hike_surprise                # one run
python -m marketsim run rate_hike_surprise --runs 100     # Monte Carlo: range of outcomes
python -m marketsim run my_scenario.json --seed 42 --out reports/mine
python -m unittest discover -s tests -t .                 # tests
```

Each run writes `report.html` (charts, event impact, who made and lost
money), `summary.json` and `timeseries.csv`.

## Trader types

| Type | Behaviour |
|---|---|
| `market_maker` | Quotes both sides; widens with volatility; skews away from inventory; pulls liquidity under stress |
| `institutional` | Large, well-informed value funds; work orders in slices |
| `fundamentalist` | Buy below and sell above a lagged, noisy, individually biased estimate of fair value |
| `momentum` | Trend followers: long when the short MA is above the long MA, short when below |
| `mean_reversion` | Fade stretched moves back toward the recent average |
| `retail` | Herd on sentiment, chase returns, act on stale news, panic-sell at a stop-loss |

Every behaviour parameter can be overridden per scenario under `params`.
Typos are rejected with the list of valid names.

## How it works

Each tick:
1. Scheduled **events** fire. They can jump fair value, shift market
   sentiment, start a volatility regime or stress market makers.
2. Hidden **fair value** follows a random walk. Agents only see it with their
   own lag and noise, so institutions learn news first and retail last.
3. **Sentiment** decays and feeds back from recent returns.
4. Active agents submit or cancel orders. The engine enforces cash, margin,
   position and short limits, then matches orders with price-time priority.

## Writing a scenario

Copy `scenarios/baseline.json` and edit `events`:

```json
{"tick": 300, "headline": "Central bank surprises with a 50bp hike",
 "fundamental_change": -0.06,  "sentiment": -0.6,
 "fundamental_vol": 0.003, "duration": 150}
```

| Field | Meaning |
|---|---|
| `fundamental_change` | Relative jump in fair value (`-0.06` = -6%) |
| `sentiment` | Added to market mood, clamped to [-1, 1] |
| `fundamental_vol` + `duration` | Temporary volatility regime (per-tick volatility of fair value) |
| `mm_stress` + `duration` | 0–1; market makers quote smaller and wider |

Run `python -m marketsim validate my_scenario.json` to check a file.

## Limits

This is a stylised model for exploring *how* different trader populations
transmit a shock: overshoots, liquidity gaps, who gets hurt. It is not
calibrated to any real instrument and is **not a price forecast or investment
advice**. Translating a real-world situation into event sizes is your
judgement call. Comparing against the `baseline` scenario, and using `--runs`
to see a distribution rather than a single path, helps keep results honest.
