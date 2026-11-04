# marketsim

An agent-based market simulator where the crowd is made of **traders**, not
generic people. You describe a future situation (a rate surprise, a liquidity
crunch, a fraud revelation...) as a scenario file. Hundreds of trading agents
with different strategies then react to it through a real limit order book.
You get a report showing how price, liquidity and each trader type's P&L play
out, across many random runs.

## Privacy by design

- **Runs 100% locally.** Pure Python standard library, so there is nothing to
  install and no third-party packages. TimesFM is an optional add-on (see below).
- **No network calls, no API keys, no telemetry.** Scenarios, price data and
  results never leave the machine it runs on. The only exception: the optional
  TimesFM backend downloads Google's model weights once, unless you give it a
  local copy.
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

## Baseline forecasts with TimesFM-3

The simulator can start from a forecast of a real price history. Fair value
then follows the forecast's median path, with uncertainty matched to the
forecast's 10–90% band, and your scenario events push it off course. The
report shows a **Scenario vs baseline forecast** chart: how far the shock
takes the market away from where history alone says it was heading.

```bash
python -m marketsim forecast my_prices.csv --horizon 60                # just the forecast
python -m marketsim run rate_hike_surprise --forecast-csv my_prices.csv --runs 50
python -m marketsim run rate_hike_on_forecast --runs 50                # forecast set in the scenario file
```

Or put it in a scenario file:

```json
"baseline_forecast": {"csv": "../data/my_prices.csv", "column": "close",
                      "ticks_per_step": 10, "model": "auto", "vol_from_band": true}
```

- **Data:** a CSV with one row per period (oldest first) and a price column.
  `close`, `adj close`, `price` or `value` are found automatically; otherwise
  pass `--column`. At least 32 rows are needed, and more is better. The file
  is read locally and never uploaded.
- **Models:**
  - `timesfm`: Google's TimesFM-3, run on this machine. Install it with
    `pip install -r requirements-timesfm.txt`. **Its pretrained weights are
    licensed for non-commercial, non-production use only.** Only the model
    weights are downloaded (once, from Hugging Face); your data is not sent
    anywhere. Set `MARKETSIM_TIMESFM_CHECKPOINT` to a local copy to run fully
    offline.
  - `statistical`: a stdlib random walk with drift fitted to the same
    history. Always available.
  - `auto` (default): TimesFM if it is installed, otherwise statistical.
    The CLI and the report always say which one was used.
- **Units:** each CSV row becomes `ticks_per_step` simulation ticks. Prices
  in the simulation are indexed so that the last observed value equals the
  scenario's `initial_price`.
- `examples/synthetic_prices.csv` is **synthetic** demo data. Replace it
  with your own history.

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
