# Eye View HQ page

Published at https://claude.ai/artifact/R7i5cJx8SC6fpW9oQm7ZcM (private to Rk).

Files published with the page: `data.json` = `hub_data.json` from `analyses/backbone/nightly.py`,
`history.json` = FRED series since 2016-11 (built by the snippet in the HQ guide).
Capabilities: `db` (collection `guesses/{call id}` = Rk's you-vs-desk calls: p, asset, asof, at)
and `sample` (Ask the desk, answers via page tools over data.json and history.json).

Nightly refresh: the page first reads db doc `hub/latest` ({json: hub_data.json as a string, built_at, updated_at}),
falling back to the published data.json. The scheduled task "Desk: refresh Eye View HQ" (trig_01GZJwF5kUmxmgKQE6uegdV5,
19:41 ET daily) copies the latest hub_data.json from the desk branch into that doc after the GitHub job runs.
The page itself is never republished by scheduled runs; history.json (Ask the desk) is as of the last publish.
