# Eye View Market — handoff prompt (paste into a new session)

I run "Eye View Market", an automated US market research desk built with Claude. It is analysis only — never place trades or give me personal investment advice. Please pick up where the last session stopped.

WHERE EVERYTHING LIVES
- Desk Daily (live dashboard, its own database: days/{date}, meta/latest, meta/scoreboard, meta/book, book/{id}): https://claude.ai/artifact/TcxbaSnEiAddmETVgBKL8q
- Desk Ledger (every call graded, theses, events, runs, reports, lessons, method/notes): https://claude.ai/artifact/7jU3VUdjX9x22fNqXoYbCL
- Read both pages with the Artifact tool and their data with the ArtifactData tool before changing anything. Method rules live in the ledger's method/notes doc; every scheduled run reads it first.
- Repo: urstrulykalpesh098/test, branch claude/miro-fish-7vjyrd. marketsim/ = agent-based market simulator; analyses/ = studies, page sources (analyses/output/desk_daily.html, desk_ledger.html), options lab, baseline backtest (analyses/desk/backtest_baseline.py).

SCHEDULED TASKS (claude.ai routines; all ET, fresh session each run)
- Morning Adversarial Market Briefing 07:56 weekdays — the only run WITH data connectors (FMP, Bigdata.com, Alpha Vantage, Financial Datasets); also writes official FMP prices into Desk Daily and logs its calls in the ledger.
- Desk: pre-open check 08:47 · Desk: midday alert 12:47 (quiet unless a threshold breaks) · Desk: close scorecard 16:47 (grades calls, regime label, three forecasters, paper book) · Desk: Sunday sentiment desk 19:17 (self-review rewrites method/notes, then a Monday Guess page). These four have NO connectors yet (web search only) — I still need to add FMP and Bigdata.com to them in the routines UI.

STATE AS OF 26 NOV 2026 (desk v2.1)
- Track record: 110+ graded calls; desk Brier 0.256 overall (coin flip = 0.25). On 63 S&P calls: desk 0.229 vs plain VIX formula 0.236. Overconfident: its 70–85% calls came true 55%.
- Regime: desk scores 0.175 in Chop but ~0.31 on trend days.
- Options lens: 13 sessions, realized vol 31.7% vs average VIX 23.9 — most days quieter than priced, a few twice as big.
- Every S&P call now stores prob_raw, prob_adj (calibrated), prob_base (formula), prob_sim (bootstrap Monte Carlo) and a blended final prob.
- Paper book: virtual $10,000, defined-risk SPY spreads, model-priced (Black-Scholes from VIX + skew), trades only when the desk and formula differ by 7+ points. Starts Friday 27 Nov.
- Five lessons in the ledger's lessons memory (gap fade, pull tails to 50%, wider ranges, don't default up in a falling tape, wider VIX bands).

IDEAS NOT BUILT YET (pick from these)
2. Real option chains: Cboe's free 15-minute-delayed chains (IV, open interest, bid/ask) read through the Claude app's browser on my Mac — needs my Mac attached; would replace model prices in the paper book and give real skew/gamma.
5. Flows from primary data: CFTC positioning, ETF flows, leveraged-ETF forced rebalance (L(L−1)·r·AUM), margin debt.
6. Event engine: automatic preview + post-mortem for watchlist earnings and big data releases, implied vs actual move, scored in the ledger.
7. Trackers: credit and funding (deals pulled/wide, spreads, CDS) and policy/permitting (January state legislatures, Texas).
8. Weekly learning card mapping that week's market to the CFA Level I curriculum.

HOUSE RULES: plain words, cite sources, flag unverified numbers, never invent data, "not investment advice" on every page, and don't republish the Desk Daily page from scheduled runs (they write data only).

FIRST TASK: read the two pages and their data, tell me in 5 lines how the desk has done since 26 Nov (calls, forecasters, paper book), then ask which idea to build.
