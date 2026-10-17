# Atlas changelog

Curated changes to the Atlas data and its rules, newest first. Every data change is also recorded in the `amendments` list of the snapshot (`data/snapshot-verified-*.json`). API shape changes are in [`public/api/v1/CHANGELOG.md`](public/api/v1/CHANGELOG.md).

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
