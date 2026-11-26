# CFA weekly card

Page: https://claude.ai/artifact/7L9ApUMePWy4aWrt4ZY5kW (source: analyses/output/cfa_weekly_card.html)

The page renders from its own database:
- `weeks/{monday}`: {week_of, title, summary, status draft|final, status_note, made, questions[]}
  - question: {id, topic (CFA L1 area), concept, fact, q, kind "mc"|"num", choices[], answer (choice index or number), tol, unit, working, source}
- `attempts/{monday}`: written by the page when Rk answers: {week_of, answers: {qid: {value, correct, at, topic}}, updated}
- `review/{monday}__{qid}`: spaced-repetition deck, written by the page. A missed question enters box 1 (due in 7 days); a right review moves it up a box (next review in 14, 28, 56 days); right in box 4 = mastered (box 5); a miss sends it back to box 1. The page shows a "due for review" panel and re-asks the originals on their due dates.
- Questions may carry `review_of` (a review doc id): the Sunday run's fresh-number variant of a concept that is due, shown with a "Concept back for review" tag.

Rules for generating a card: build every question only from numbers in the desk's own records (Desk Daily days, Desk Ledger predictions, meta/flows, method/notes), compute numeric answers in a script, flag web-only figures in `fact`, name the source, and bring back 1-2 concepts Rk missed in earlier `attempts`. Scheduled runs write data only; they never republish the page.

`week-2026-11-23.json` is the first card as seeded on 26 Nov 2026.
