# Desk Scorecard

Weekly scorecard comparing the desk, the plain VIX formula, the simulator and a naive
"trend follows yesterday" baseline, plus the paper book vs SPY.

- Page: https://claude.ai/artifact/M2T7uHbVzqydb38BcrRi8F (Data artifact; the live page source is the artifact's `files/index.html`, styled by the design thread, copy at analyses/design/scorecard_index.html. Keep its data-source/data-field/data-draw bindings when editing).
- `scorecard.py` (stdlib only, self-contained; a copy lives in the Desk Ledger as method/scorecard_script): builds per-week rows and an "All weeks" row from graded ledger calls, and grades one-day S&P up/down calls vs follow-yesterday (60/40, fixed in advance), the formula (50%) and always-down (warning only).

Refresh (the Sunday self-review does this every week, or by hand):
1. ArtifactData list Desk Ledger `predictions` and Desk Daily `days` (limit 1000, out_dir) and get Desk Daily `meta/book` (out_dir).
2. `python3 scorecard.py --pred <predictions dir> --days <days dir> --book <meta_book.json> --rows scorecard_rows.json`
3. Upload `scorecard_rows.json` to the page as an asset, then `update` its `datasets/weeks` with the new `/_blob/` url and `updated {at, by}`.

Caveats: several calls resolve on the same day, so the n of independent outcomes is far smaller than the call count. A falling month flatters down-leaning rules. Not investment advice.

Skill or luck section (27 Nov 2026): dataset `skill` is `python3 analyses/desk/skill.py --pred <predictions dir> --rows skill_rows.json` (pulls FRED itself, or `--history analyses/data/history`). Upload it as an asset and update `datasets/skill` source.url and updated, the same way as `weeks`.
