# Atlas curation standards

How the Commonworld Atlas decides what stays in the catalog. How each card is verified is in [`PROTOCOL.md`](PROTOCOL.md); what changed and when is in [`CHANGELOG.md`](CHANGELOG.md).

## Link safety

The Atlas sends people to other websites, so every link it publishes should be safe to open.

- **Checked every day.** Every domain linked from the published data (official URLs and the source links behind each claim) is checked daily by the [Commonworld trust engine](../TRUST.md) against Google Safe Browsing, MetaMask eth-phishing-detect, ScamSniffer and the CERT Polska Warning List, through [`tools/link_safety.py`](tools/link_safety.py), run by the GitHub Actions workflow **Atlas link safety** ([`.github/workflows/link-safety.yml`](../.github/workflows/link-safety.yml)). The sources, what each result means and the full standard are in [`TRUST.md`](../TRUST.md).
- **Published with the data.** The result of the latest check is part of the live dataset: [`/atlas/safety.json`](https://commonworld.one/atlas/safety.json) lists every linked domain with its status (`clean`, `flagged` or `no_data`), the answer of each source (verdict, check time in UTC, evidence link), summary counts and the run time, and every entry in the JSON exports carries `link_safety` `{status, checked_at}` for its official URL. The workflow commits the report file (`data/link-safety.json`); the normal site build publishes it.
- **Any single flag means removed, at once.** If any one source flags a domain, the workflow removes every entry that links to it, records the decision (actor `hark`, the source and what it said, the evidence link), rebuilds the site, and commits only when the full build check passes; it also opens or updates the issue "Link safety: flagged domains". The entry leaves every listing, count, search index and data file, and no page links to it any more. A domain a curator is already looking at can be put in [`data/trust-hold.json`](data/trust-hold.json): it is reported but not removed.
- **IDs keep working.** Slugs are permanent, so the entry's page stays as a short neutral note, "This entry was removed from the Atlas after a safety check", without the name or any outbound link, marked noindex and left out of the sitemap. Removed entries are listed in [`data/removed.json`](data/removed.json).
- **Entries can come back.** The daily check keeps looking at the domains of removed entries. Once no source flags a domain any more and a fresh check passes, the entry can return: a restore decision with a clean re-check, then the card comes back from git history.
- **Who can act.** Four trusted actors can remove an entry and restore it, each on their own and at once: the maintainer [nerd27dk](https://github.com/nerd27dk) and the agents hark, codex and continuum, who act through his commits signed with the trailer `Contributed-by: <name>`. The list lives in [`data/trust-roles.json`](data/trust-roles.json).
- **Every decision is on the record.** Each removal and each return is written to `decisions` in [`data/removed.json`](data/removed.json): what (slug and domain), who, when, why, and a link to the evidence; a return also records the clean re-check. The build check (`site/check.py`) accepts a removal only with its decision, a decision only from a listed actor, and a return only when the latest safety report shows the domain as clean.
- **Appeals.** Anyone who thinks an entry was removed by mistake can open an issue titled "Appeal: <domain>" in this repository or write to the contact address on the About page. We reply within 7 days (see [`TRUST.md`](../TRUST.md#appeals)).
- **Published as a log.** The decisions are published at [`/atlas/decisions/`](https://commonworld.one/atlas/decisions/), newest first: date, action, entry ID, domain as plain text (written with `[.]`, never a link), who acted, why, and the evidence link. The same log is available as Markdown ([`/atlas/decisions/index.md`](https://commonworld.one/atlas/decisions/index.md)) and JSON with the trust roles ([`/atlas/decisions.json`](https://commonworld.one/atlas/decisions.json)). Both are generated from `data/removed.json` at build time, and the build check fails if any decision is missing.

## Events log

Every change to a card is also one line in a public, append-only events log, so anyone can follow what changed and check it.

- **One line per event** in [`data/events.jsonl`](data/events.jsonl): `date` (YYYY-MM-DD, UTC), `slug` (the permanent entry ID), `type`, a short `reason`, and `source` (the https page the change was checked on).
- **Types.** `added` (new card), `closed` (marked closed, by a human or by the weekly check), `reopened` (an automated closure lifted because the site answers again), `corrected` (a claim, summary or link changed after re-checking the source), `relabelled` (a claim's basis label or category changed, the fact itself did not).
- **Written with the change.** A curated change and its event land in the same commit; the weekly refresh ([`refresh.py`](refresh.py)) writes `closed` and `reopened` lines itself. Automated number updates are not events (they are in the snapshot's `amendments` and the refresh PR), and link-safety removals have their own decision log (above).
- **Published.** [`/atlas/events.json`](https://commonworld.one/atlas/events.json) (newest first) and [`/atlas/events.md`](https://commonworld.one/atlas/events.md), generated at build time and named in `llms.txt`.
- **Checked.** The build check (`site/check.py`, with [`site/events.py`](site/events.py)) fails on a malformed line, an unknown entry ID, a date older than the line before, a duplicate, or a curated amendment from 2026-10-19 on whose cards have no matching event. The log starts on 2026-10-19; earlier changes are in [`CHANGELOG.md`](CHANGELOG.md).

## Cards v2

Every card (its page, its Markdown twin at `/atlas/platforms/<id>/index.md`, its JSON record and the API) shows three more things. The rules live in code, [`site/cards_v2.py`](site/cards_v2.py); `site/check.py` recomputes them from the published claims and fails the build on any drift, and [`tests/test_cards_v2.py`](../tests/test_cards_v2.py) pins them with examples. On the site: [How the Atlas works](https://commonworld.one/atlas/about/#evidence-ladder).

### Evidence ladder

Every money or activity claim (kind `economic_flow`, `metric` or `recent_activity`) gets a level from its source URL, by a fixed rule:

| Level | Label | What the source is | Rule on the source URL |
|---|---|---|---|
| 3 | public transactions | On-chain or other public records anyone can open and check independently. | The host is a public block explorer (`EXPLORER_HOSTS`: etherscan.io, basescan.org, solscan.io, explorer.solana.com, mempool.space, blockscout.com, kitescan.ai and others, subdomains included), or the host calls itself a scanner or explorer and the path is a record page (`/tx/…`, `/address/…`, `/token/…`, `/block/…`). |
| 2 | public dashboard | A public stats page, dashboard or API anyone can open. | Not level 3, and: a known public dashboard host (`DASHBOARD_HOSTS`: dune.com, chainward.ai, defillama.com, tokenterminal.com, x402scan.com), or a host starting with `api.` or `stats.`, or a path segment `api`, `stats`, `statistics`, `analytics`, `dashboard`, `metrics`, `leaderboard` or `status`, or a versioned path (`/v1/`), or a `.json` file. |
| 1 | operator says | The platform's own words: site text, docs, posts (and other text pages such as articles). | Every other URL, and every archived copy (web.archive.org). |

- Where a URL could be read two ways, the rule takes the **lower** level. A claim without a source URL has no level.
- The **card level** is the highest level reached by its *supported* money and activity claims (`evidence_level` {level, id, label, claims_counted}). A card without one shows "not recorded yet".
- In the per-entry JSON every money and activity claim carries `evidence_level` (1, 2 or 3) and `evidence_label`.
- To move a card up the ladder, add a claim whose source is a public dashboard or public transactions.

#### Curator review of a level

The URL rule is a first reading. A curator may set the level of a card's claims with one source URL by hand in
[`data/evidence-levels.json`](data/evidence-levels.json), **only after opening that source**:

```json
"touchstone": [{"source_url": "https://touchstone.cv/d/…", "evidence_level": 2,
                "evidence_note": "Public JSON disclosure log: signed, sequenced entries with server timestamps that anyone can open.",
                "reviewed_on": "2026-10-19"}]
```

- Raise a level only when the content shows it: a public JSON log, feed or data file on a plain path, or a live dashboard page
  whose figures are in the page (level 2).
- Lower a level when the source carries no live figures: a dated report on a dashboard host, an endpoint that lists zero items or
  a placeholder, an error, or a host that was offline at review. When unsure, take the lower level.
- An entry must change the level (check.py fails on an entry equal to the URL rule), the note is required, at most 200 characters,
  in positive wording, and is published on the claim as `evidence_note` (card page tooltip and line, Markdown twin, JSON, API).
- Every review that changes a card gets a `relabelled` line in [`data/events.jsonl`](data/events.jsonl).

### Keys and books

An idea from The Caretaker, an agent on The Colony. Three questions per card, each `{state, value, label, source_url, quote}`:

- **Who holds the keys** (`keys`): custody of funds or accounts: `operator`, `user_wallet` (users hold their own wallet or keys) or `smart_contract`.
- **Open books** (`books`): its money figures (payouts, balances, volume) are publicly checkable: `public_transactions` or `public_dashboard`.
- **People behind it** (`people`): `named`, with the names (people or a company) as a source names them.

Rules:

- A value is filled **only from a supported claim already on the card**. Curated values live in [`data/keys-and-books.json`](data/keys-and-books.json): `source_url` must be that claim's source URL and `quote` must appear in its quote or statement; the build check fails otherwise.
- Open books are also derived automatically: the highest-level supported money-flow claim at ladder level 2 or 3 fills `books` with its source.
- Every other answer is `state: not_recorded`, shown as "not recorded yet". The wording is always neutral and positive; check.py fails on negative words in the site-written v2 text.

### First task

One simple first step for a newcomer, human or agent, kept in [`data/first-tasks.json`](data/first-tasks.json) (title, steps, done_when, contributed_by, contributed_via, source_url, verified_by, verified_on, verification). A task proposed by a platform or a contributor is published only after a curator ran it, with credit "Contributed by <nick>" and a link to where it was proposed. Cards without a verified task show no first-task block (`first_task: null`); there are no generic default tasks.
