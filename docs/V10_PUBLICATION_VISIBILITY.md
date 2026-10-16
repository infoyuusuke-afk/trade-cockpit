# V10 local publication visibility (P0-10)

The Gateway reads **only** the existing Watcher-owned
\`<RuntimeDir>/kioxia_watcher_live.json\`, checks its size, published
schema/source identifier, explicit JST offset, file modification age, and
controller-verified Watcher process status. It exposes only
\`watcher_observed_at_offset\`, \`watcher_timestamp_timezone\`, and
\`watcher_publication_state\` through the existing loopback \`/health\`
response. It never exports trade records or CSV data. The existing Collector
publication check uses its already-published timestamp.

The UI independently polls the same-origin \`/health\`, distinguishing recent
JSON **publication** from stale, unknown, or unverified sources. A recent
publication DOES NOT establish that ticks were recently observed, that sources
are independently authenticated, or that signals are fit for trading.

Brain has no independently verified timestamp owner in this V10 tree and
remains \`UNKNOWN_NOT_PUBLISHED\`. Consequently all four-source evidence and
\`source_authenticated\` remain unverified and every real order route remains
disabled. The old September-25 static analysis stays labelled as historical.
This PR is a Draft, has not been merged or deployed to the OWNER PC.

V10 RUN explicitly deploys its Watcher to \`RuntimeDir\`, where the Watcher
writes the JSON alongside its script. The old implementation read a checkout
path incorrectly, so it could misreport a healthy deployed Watcher as missing
or read an unrelated copy. The Gateway now reads only the explicit RuntimeDir
it already receives from V10 Controller. Missing runtime, a reparse directory,
missing Watcher JSON, or a mismatched publisher identity stays fail-closed.
A decoy file in RepoRoot must not affect results; this is a CI acceptance case.

Port 28584 is a *second instance of V10 Gateway* per Controller, NOT proof of
an independent BRAIN analysis engine. No BRAIN data producer is verified.

Windows CI exercises actual loopback HTTP with a synthetic RuntimeDir and
an unrelated checkout decoy. It never starts Excel or verifies OWNER-PC live ticks.
