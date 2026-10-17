# Atlas curation standards

How the Commonworld Atlas decides what stays in the catalog. How each card is verified is in [`PROTOCOL.md`](PROTOCOL.md); what changed and when is in [`CHANGELOG.md`](CHANGELOG.md).

## Link safety

The Atlas sends people to other websites, so every link it publishes should be safe to open.

- **Checked every day.** Every domain linked from the published data (official URLs and the source links behind each claim) is checked daily against [Google Safe Browsing](https://transparencyreport.google.com/safe-browsing/search) by [`tools/safebrowsing_check.py`](tools/safebrowsing_check.py), run by the GitHub Actions workflow **Atlas link safety** ([`.github/workflows/link-safety.yml`](../.github/workflows/link-safety.yml)).
- **Published with the data.** The result of the latest check is part of the live dataset: [`/atlas/safety.json`](https://commonworld.one/atlas/safety.json) lists every linked domain with its status (`clean`, `flagged` or `no_data`), the time it was checked (UTC), summary counts and the run time, and every entry in the JSON exports carries `link_safety` `{status, checked_at}` for its official URL. The workflow commits only the report file (`data/link-safety.json`); the normal site build publishes it.
- **Flagged means removed.** If a domain is flagged, the workflow opens or updates the issue "Link safety: flagged domains" and the curator removes the entry from the Atlas: it leaves every listing, count, search index and data file, and no page links to it any more. The check itself never edits the data.
- **IDs keep working.** Slugs are permanent, so the entry's page stays as a short neutral note, "This entry was removed from the Atlas after a safety check", without the name or any outbound link, marked noindex and left out of the sitemap. Removed entries are listed in [`data/removed.json`](data/removed.json).
- **Entries can come back.** The daily check keeps looking at the domains of removed entries. Once Google Safe Browsing no longer flags a domain and a fresh check passes, the entry can return: a restore decision with a clean re-check, then the card comes back from git history.
- **Who can act.** Four trusted actors can remove an entry and restore it, each on their own and at once: the maintainer [nerd27dk](https://github.com/nerd27dk) and the agents hark, codex and continuum, who act through his commits signed with the trailer `Contributed-by: <name>`. The list lives in [`data/trust-roles.json`](data/trust-roles.json).
- **Every decision is on the record.** Each removal and each return is written to `decisions` in [`data/removed.json`](data/removed.json): what (slug and domain), who, when, why, and a link to the evidence; a return also records the clean re-check. The build check (`site/check.py`) accepts a removal only with its decision, a decision only from a listed actor, and a return only when the latest safety report shows the domain as clean.
