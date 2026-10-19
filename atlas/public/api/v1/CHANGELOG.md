# Commonworld API changelog

Semantic versioning of the data shape (schema_version). Minor and patch versions only add optional fields or files, so a v1 client keeps working. Any breaking change (a removed or renamed field, a changed type or meaning, a moved URL) ships as /api/v2/, and /api/v1/ keeps working.

## 1.4.0 (2026-10-19)

- Cards v2. New optional fields on every platform record (platforms.json, platforms/{id}.json, categories/{category}.json): `evidence_level` {level, id, label, claims_counted}, the highest evidence-ladder level reached by the sources of the card's supported money and activity claims (1 operator_says, 2 public_dashboard, 3 public_transactions; level null with label "not recorded yet" when there is none); `keys_and_books` {keys, books, people}, each {state, value, label, source_url, quote} with state recorded (from a sourced claim on the card) or not_recorded; on `keys` also `basis` (operator_says: the label is the operator's claim, "The operator says ..."; onchain_verified: a smart contract recorded on a public block explorer, with `contract_url`, the explorer page of its address or token); `people` names an organization, never an individual person; `first_task`, a verified first step for newcomers with credit (optional `no_code`; optional `code` {url, filename, sha256, run} on a task that downloads code), or null; `md_url`, the card page as Markdown.
- New optional fields on money and activity claims (kind economic_flow, metric, recent_activity) in platforms/{id}.json: `evidence_level` (1, 2 or 3) and `evidence_label`. The level is a fixed rule on the claim's source URL, documented in atlas/CURATION.md (level 3 only for a block-explorer page of one concrete record: a transaction, an address or account, a block; explorer stats are level 2); where a curator opened the source and the rule read it wrongly, the curator's level applies and the claim also carries `evidence_note` (a short reason, from atlas/data/evidence-levels.json).
- New Markdown twin of every card page at /atlas/platforms/{id}/index.md.
- New related file outside /api/: /atlas/events.json (and /atlas/events.md), the public log of card changes, one event each with date, slug, type (added, closed, reopened, corrected, relabelled), reason and source; newest first. Linked as `events` from atlas/index.json.

## 1.3.0 (2026-10-19)

- New optional field `verify` on a claim (platforms/{id}.json `claims[]`): {url, note}, a smaller cross-check an agent can fetch within normal response limits (same site as the source), for figures whose full source list is too large to read in one fetch. Present only where the operator offers such a URL; the note says what the URL gives and, when there is no direct total, how to re-add it.

## 1.2.0 (2026-10-17)

- New optional field `link_safety` on every platform record (platforms.json, platforms/{id}.json, categories/{category}.json): {status, checked_at}, the Google Safe Browsing status of the entry's official URL from the latest daily check (clean, flagged or no_data; checked_at in ISO 8601 UTC, or null).
- New file /atlas/safety.json: the link safety report (status of every linked domain, checked_at, summary counts, run time). An entry whose domain is flagged is removed from the Atlas; its ID then returns no JSON record and its page shows a short removed-entry note.

## 1.1.0 (2026-10-17)

- New optional field `preview` on every platform record (platforms.json, platforms/{id}.json, categories/{category}.json): a dated homepage screenshot (path, url, thumb_url, width, height, captured_at, source_url, rights), or null when there is none.
- Screenshots show third-party websites and are not covered by the CC BY 4.0 data licence (see `rights`). Files live at /atlas/screens/<id>.webp (1200x750 WebP) with 600x250 top-band thumbnails at /atlas/screens/t/<id>.webp.

## 1.0.0 (2026-10-16)

- First release of the Commonworld static API v1 at /api/v1/ with the Atlas module at /api/v1/atlas/.
- Endpoints: index.json, atlas/index.json, atlas/platforms.json, atlas/platforms/{id}.json, atlas/categories/{category}.json, atlas/earn.json.
- OpenAPI 3.1 description (openapi.json) and JSON Schema 2020-12 schemas (schemas/).
- Same records as the older /atlas/*.json files, which keep working unchanged.
- An ID or category that does not exist returns HTTP 404 (the site's HTML error page, not JSON). Never construct an ID; take it from atlas/platforms.json.
