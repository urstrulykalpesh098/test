# Eye View HQ page

Published at https://claude.ai/artifact/R7i5cJx8SC6fpW9oQm7ZcM (private to Rk).

Files published with the page: `data.json` = `hub_data.json` from `analyses/backbone/nightly.py`,
`history.json` = FRED series since 2016-11 (built by the snippet in the HQ guide).
Capabilities: `db` (collection `guesses/{call id}` = Rk's you-vs-desk calls: p, asset, asof, at)
and `sample` (Ask the desk, answers via page tools over data.json and history.json).

The page shows the snapshot it was published with. To refresh it, run nightly.py, copy hub_data.json
to data.json and republish the same artifact URL (a Claude session does this; scheduled runs must not).
