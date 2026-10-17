# Atlas changelog

Curated changes to the Atlas data and its rules, newest first. Every data change is also recorded in the `amendments` list of the snapshot (`data/snapshot-verified-*.json`). API shape changes are in [`public/api/v1/CHANGELOG.md`](public/api/v1/CHANGELOG.md).

## 2026-10-17 — Link safety decision log

- New page [`/atlas/decisions/`](https://commonworld.one/atlas/decisions/): every removal and return in the Atlas as a public, dated decision, newest first, with the entry ID, the domain as plain text (written with `[.]`), who acted (actor ID from [`data/trust-roles.json`](data/trust-roles.json)), the reason and the evidence link. Generated from `data/removed.json` at build time.
- Markdown twin [`/atlas/decisions/index.md`](https://commonworld.one/atlas/decisions/index.md) and JSON [`/atlas/decisions.json`](https://commonworld.one/atlas/decisions.json) (decisions, trust roles, the link safety rule, `generated_at`). The JSON is in the Dataset JSON-LD; the page is in the sitemap and both llms.txt files, and linked from [How the Atlas works](https://commonworld.one/atlas/about/#link-safety).
- `check.py`: the page, its Markdown twin and the JSON must list every decision; evidence links carry `rel="nofollow noopener"`; any `index.md` must be linked from its HTML page as `rel="alternate" type="text/markdown"`. The removed-domain scan allows exactly one thing more: the recorded evidence URL of a third-party checker (Google transparency report), only in the decision log files. Unit tests: `tests/test_decisions_log.py`.
- SEO: the page carries a CollectionPage whose main entity is a Dataset (JSON and Markdown downloads) with an ItemList of the decisions, plus BreadcrumbList; sitemap lastmod is the newest decision date; every page footer links "Decision log", and removed-entry notes and `/atlas/safety.json` point to it. `check.py` checks canonical, title, description, OG/Twitter, the JSON-LD, sitemap lastmod, the table's accessible name and headers, and inbound links.

## 2026-10-17 — Who can act on link safety

- New [`data/trust-roles.json`](data/trust-roles.json): nerd27dk and the agents hark, codex and continuum (through his commits with `Contributed-by: <name>`) can each remove and restore an entry at once.
- [`data/removed.json`](data/removed.json) now keeps `decisions`: who, when, why and an evidence link for every removal and return (a return also records the clean re-check). The removal of `venice-ai-x402` is recorded.
- `check.py` (via [`tools/trust_check.py`](tools/trust_check.py)) fails when a removed entry has no decision, a decision names an actor not in trust-roles.json, or a returned domain is not clean in the latest safety report. Unit tests: `tests/test_trust_roles.py`. [`CURATION.md`](CURATION.md#link-safety): "Who can act" and "Every decision is on the record".

## 2026-10-17 — Link safety

- New standard **Link safety** ([`CURATION.md`](CURATION.md#link-safety)): every linked domain is checked daily against Google Safe Browsing; a flagged domain's entry is removed and its page becomes a removed-entry stub; it can return after the flag clears and a re-check.
- New check script [`tools/safebrowsing_check.py`](tools/safebrowsing_check.py) and daily workflow **Atlas link safety** (`.github/workflows/link-safety.yml`): commits only `data/link-safety.json`, opens/updates the issue "Link safety: flagged domains".
- The safety state is part of the live data: [`/atlas/safety.json`](https://commonworld.one/atlas/safety.json) (in the Dataset JSON-LD and `/atlas/llms.txt`) and a `link_safety` `{status, checked_at}` field on every record (API schema_version 1.2.0).
- One entry removed after a Google Safe Browsing flag (`venice-ai-x402`); its page is now a noindex removed-entry note. The Atlas has 311 entries.
- `check.py` now fails if a removed entry still appears in any listing or data file, if its stub is missing or indexable, or if any built file names its domain.
