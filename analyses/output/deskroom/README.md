# Desk Room (demo)

Page: https://claude.ai/artifact/NL7yQRq1UYSwBeSemnB6Dm (source `desk_room.html`, capabilities `db` + `sample`).

Six specialist seats (Volatility, Rates, Credit & funding, Cross-asset, History, Red team) each get
only their own briefing packet from `analyses/output/hub/deskroom_packets.json`
(built nightly by `analyses/deskroom/packets.py`, called from `analyses/backbone/nightly.py`).
"Run a fresh meeting" on the page makes one Claude call per seat, a cross-talk round
(each seat replies to one other), then the Head of desk writes a 5-line brief from the posts only.

db: `meetings/{id}` (saved meetings, newest shown), `packets/latest` ({json, updated_at}; written by
the daily scheduled task "Desk: refresh Eye View HQ + Desk Room"). `seed.json` is the first meeting
and the fallback when the db is unavailable; `packets.json` beside the page is a static fallback.

Analysis only. Not investment advice.
