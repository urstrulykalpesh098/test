# God's Eye View

Published at https://claude.ai/artifact/NgYn6kfoW4pbqwuhS4Tma1 (private to Rk), linked from the HQ nav.

A map of how money and stress move between the markets the desk tracks: 19 stations, 25 routes.
Built by `analyses/godseye/godseye.py` from the backbone history files and the trackers' latest outputs
(flows, credit, auctions, canada, vixterm). `analyses/backbone/nightly.py` rebuilds `godseye.json` each night.

Every route is labelled: tested on history (correlation of non-overlapping 4-week changes since 2010, by era,
lead test and gap test), mechanical (a formula), or inferred (theory only, no free history). Context only.

Nightly refresh (no republish needed): `nightly.py` (GitHub job, weeknights 23:15 UTC) also writes the small
`analyses/output/hub/godseye_latest.json` (last 8 weeks + nodes + edges). The close run copies it into this page's db
as doc `godseye/latest` = {json: <file contents as a string>, built_utc, updated_at}. The page loads the published
`godseye.json` (3 years of weeks) and merges the db weeks on top, so the map, story, plain words and chat all show
the newest week. If the db doc is missing, the page shows the published snapshot. Republish only to change the page
or to extend the history file.
