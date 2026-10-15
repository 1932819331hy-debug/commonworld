# Atlas verification protocol

Version 1, used for the first verified release of the Commonworld Atlas (2026-10-15). Licence: CC BY 4.0. Any agent or person can follow it to re-check a card; corrections are welcome as GitHub issues.

## Brief given to each verifying agent

Goal: for each row in your batch, establish with evidence what is TRUE NOW about the platform, so only verified cards enter the public Atlas catalog. We act like a search-engine crawler with agents: every statement carries a source, a quote/observation and a UTC time.

Input row fields: legacy data from a scout census on 2026-10-15 (NOT evidence — treat as hints), plus `layer1` = an automated HTTP check done 2026-10-15 ~18:06 UTC (ok_content / ok_thin_or_js / network_error / http_404 / http_other / blocked_or_challenge / no_url). Layer-1 failures are NOT proof of death.

## For every row, check these claims (use web_fetch / web_search / curl in shell / GitHub API / public APIs)
1. `canonical_url` — the official URL. If missing (no_url), find it (official site, GitHub org, docs). If you cannot find any official presence after a real search, say so.
2. `site_reachable` — does the official page serve real content now? If layer1 or your first fetch failed, try at least TWO other methods before concluding anything: http vs https / www, alt URLs, an API/docs/status endpoint, GitHub repo, web_search for recent mentions, web.archive.org latest snapshot date. Cloudflare/JS shells = `needs_browser`, never "dead".
3. `description` — one-sentence factual description in YOUR OWN words (English), with the primary source URL and a short quote supporting it.
4. `recent_activity` — newest dated sign of life you can see (post, commit, release, changelog, tweet) with its date and URL.
5. `metric` / `economic_flow` (money: volumes, payouts, orders, transactions) — only if the platform or a credible source publishes it. Record exact value, unit, scope, time window, source URL, observed_at. Do NOT copy legacy numbers; re-observe or mark unverified. Separate operator claims from independent observations.
6. `announced_closed` — if the project appears dead: look for an official shutdown/sunset statement. "Dead" requires either an official statement OR ≥2 independent signals (e.g. domain fails by 2 methods AND no activity anywhere for 90+ days). Otherwise `unresolved`.

## Entity type
Mark `entity_type`: `platform` (agents live/work/get paid/are listed there), `tool_catalog` (a registry/directory of tools/servers like MCP registries — one card per catalog), `protocol`, `project` (single tool/agent, not a platform), or `not_relevant`.

## Outcomes per claim
`supported` | `contradicted` | `inaccessible` (tried ≥3 methods, list them) | `needs_browser` | `unchecked`.

## Row verdict
- `include_verified` — canonical_url + site_reachable + description all supported.
- `include_closed_history` — closure supported (official or ≥2 signals); card kept as history.
- `needs_browser` — blocked by JS/Cloudflare; needs a real browser pass.
- `unresolved` — conflicting or insufficient evidence (explain).
- `exclude` — not an agent platform / duplicate (explain, name the duplicate id).

## Slug
Propose `slug`: lowercase, hyphenated full name (e.g. the-colony, colony-chat, agent-colony). Never shorten to a generic word.

## Output (mandatory)
Write `results/batch-NN.json` (array, one object per input row, same `id`):
```
{"id":1,"name":"…","slug":"…","entity_type":"platform","verdict":"include_verified",
 "canonical_url":"…","description_en":"…",
 "claims":[{"kind":"site_reachable","statement":"…","value":null,"unit":null,"window":null,
   "basis":"direct_observation|operator_claim|independent_source|inference",
   "source_url":"…","quote":"≤200 chars","observed_at":"2026-10-15T18:40:00Z",
   "methods":["web_fetch https://…","curl -I …"],"outcome":"supported"}],
 "legacy_diffs":["legacy said X, now Y"],"notes":"…"}
```
Also write `results/batch-NN.md`: counts by verdict, rows needing a browser, notable corrections vs legacy (esp. money and closures), and any NEW platforms you stumbled upon (name + URL, do not research them).

Times: UTC ISO. Unknown = null, never 0. Never invent a URL or number. Work efficiently: aim ~3–5 tool calls per healthy row, more only for failing/money rows. Save the JSON incrementally (rewrite the file every ~8 rows) so partial work survives. If something loops more than twice, record it as unresolved and move on.
