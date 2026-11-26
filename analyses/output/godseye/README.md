# God's Eye View

Published at https://claude.ai/artifact/NgYn6kfoW4pbqwuhS4Tma1 (private to Rk), linked from the HQ nav.

A map of how money and stress move between the markets the desk tracks: 19 stations, 25 routes.
Built by `analyses/godseye/godseye.py` from the backbone history files and the trackers' latest outputs
(flows, credit, auctions, canada, vixterm). `analyses/backbone/nightly.py` rebuilds `godseye.json` each night.

Every route is labelled: tested on history (correlation of non-overlapping 4-week changes since 2010, by era,
lead test and gap test), mechanical (a formula), or inferred (theory only, no free history). Context only.

Refresh the published page: run `python analyses/godseye/godseye.py`, then republish `gods_eye_view.html`
with `godseye.json` beside it (same URL). The page does not refresh itself.
