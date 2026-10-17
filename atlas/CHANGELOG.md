# Atlas changelog

Curated changes to the Atlas data and its rules, newest first. Every data change is also recorded in the `amendments` list of the snapshot (`data/snapshot-verified-*.json`). API shape changes are in [`public/api/v1/CHANGELOG.md`](public/api/v1/CHANGELOG.md).

## 2026-10-17 — Link safety

- New standard **Link safety** ([`CURATION.md`](CURATION.md#link-safety)): every linked domain is checked daily against Google Safe Browsing; a flagged domain's entry is removed and its page becomes a removed-entry stub; it can return after the flag clears and a re-check.
- New check script [`tools/safebrowsing_check.py`](tools/safebrowsing_check.py) and daily workflow **Atlas link safety** (`.github/workflows/link-safety.yml`): commits only `data/link-safety.json`, opens/updates the issue "Link safety: flagged domains".
- The safety state is part of the live data: [`/atlas/safety.json`](https://commonworld.one/atlas/safety.json) (in the Dataset JSON-LD and `/atlas/llms.txt`) and a `link_safety` `{status, checked_at}` field on every record (API schema_version 1.2.0).
- One entry removed after a Google Safe Browsing flag (`venice-ai-x402`); its page is now a noindex removed-entry note. The Atlas has 311 entries.
- `check.py` now fails if a removed entry still appears in any listing or data file, if its stub is missing or indexable, or if any built file names its domain.
