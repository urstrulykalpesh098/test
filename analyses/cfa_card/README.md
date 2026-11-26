# CFA weekly card

Page: https://claude.ai/artifact/7L9ApUMePWy4aWrt4ZY5kW (source: analyses/output/cfa_weekly_card.html)

The page renders from its own database:
- `weeks/{monday}`: {week_of, title, summary, status draft|final, status_note, made, questions[]}
  - question: {id, topic (CFA L1 area), concept, fact, q, kind "mc"|"num", choices[], answer (choice index or number), tol, unit, working, source}
- `attempts/{monday}`: written by the page when Rk answers: {week_of, answers: {qid: {value, correct, at, topic}}, updated}

Rules for generating a card: build every question only from numbers in the desk's own records (Desk Daily days, Desk Ledger predictions, meta/flows, method/notes), compute numeric answers in a script, flag web-only figures in `fact`, name the source, and bring back 1-2 concepts Rk missed in earlier `attempts`. Scheduled runs write data only; they never republish the page.

`week-2026-11-23.json` is the first card as seeded on 26 Nov 2026.
