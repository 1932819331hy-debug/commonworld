# Atlas curation standards

How the Commonworld Atlas decides what stays in the catalog. How each card is verified is in [`PROTOCOL.md`](PROTOCOL.md); what changed and when is in [`CHANGELOG.md`](CHANGELOG.md).

## Link safety

The Atlas sends people to other websites, so every link it publishes should be safe to open.

- **Checked every day.** Every domain linked from the published data (official URLs, the source links behind each claim, and the links of each card's first task, keys-and-books and evidence-level records) is checked daily by the [Commonworld trust engine](../TRUST.md) against Google Safe Browsing, MetaMask eth-phishing-detect, ScamSniffer and the CERT Polska Warning List, through [`tools/link_safety.py`](tools/link_safety.py), run by the GitHub Actions workflow **Atlas link safety** ([`.github/workflows/link-safety.yml`](../.github/workflows/link-safety.yml)). The sources, what each result means and the full standard are in [`TRUST.md`](../TRUST.md).
- **Published with the data.** The result of the latest check is part of the live dataset: [`/atlas/safety.json`](https://commonworld.one/atlas/safety.json) lists every linked domain with its status (`clean`, `flagged` or `no_data`), the answer of each source (verdict, check time in UTC, evidence link), summary counts and the run time, and every entry in the JSON exports carries `link_safety` `{status, checked_at}` for its official URL. The workflow commits the report file (`data/link-safety.json`); the normal site build publishes it.
- **Any single flag means removed, at once.** If any one source flags a domain, the workflow removes every entry that links to it, records the decision (actor `hark`, the source and what it said, the evidence link), rebuilds the site, and commits only when the full build check passes; it also opens or updates the issue "Link safety: flagged domains". The entry leaves every listing, count, search index and data file (its first task, keys-and-books and evidence-level records are dropped from the curation files too; they stay in git history for a restore), and no page links to it any more. A domain a curator is already looking at can be put in [`data/trust-hold.json`](data/trust-hold.json): it is reported but not removed.
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
- **Checked.** The build check (`site/check.py`, with [`site/events.py`](site/events.py)) fails on a malformed line, an unknown entry ID, a date older than the line before, a duplicate, or a curated amendment from 2026-10-19 on whose cards have no matching event. The cards v2 curation files change cards outside the amendments, so each of their records carries a date and needs its event on that day: an evidence-level review (`reviewed_on`) a `relabelled` line, a keys-and-books value (`reviewed_on`, required) and a first task (`verified_on`) a `corrected` line. Changing such a record means a new date and a new event. The log starts on 2026-10-19; earlier changes are in [`CHANGELOG.md`](CHANGELOG.md).

## Cards v2

Every card (its page, its Markdown twin at `/atlas/platforms/<id>/index.md`, its JSON record and the API) shows three more things. The rules live in code, [`site/cards_v2.py`](site/cards_v2.py); `site/check.py` recomputes them from the published claims and fails the build on any drift, and [`tests/test_cards_v2.py`](../tests/test_cards_v2.py) pins them with examples. On the site: [How the Atlas works](https://commonworld.one/atlas/about/#evidence-ladder).

### Evidence ladder

Every money or activity claim (kind `economic_flow`, `metric` or `recent_activity`) gets a level:

| Level | Label | What the source is | How the level is set |
|---|---|---|---|
| 3 | public transactions | One public on-chain record that anyone can open and check independently. | **Only by a curator** who opened the record: an entry in [`data/evidence-levels.json`](data/evidence-levels.json) (see "Curator review of a level"). The URL rule never gives level 3. |
| 2 | public dashboard | A public stats page, dashboard or API anyone can open. | URL rule: any page on a block explorer (`EXPLORER_HOSTS`), a record page included; a known public dashboard host (`DASHBOARD_HOSTS`: dune.com, chainward.ai, defillama.com, tokenterminal.com, x402scan.com); a host starting with `api.` or `stats.`; a path segment `api`, `stats`, `statistics`, `analytics`, `dashboard`, `metrics`, `leaderboard` or `status`; a versioned path (`/v1/`); a `.json` file. |
| 1 | operator says | The platform's own words: site text, docs, posts (and other text pages such as articles). | URL rule: every other URL, and every archived copy (web.archive.org). |

- Where a URL could be read two ways, the rule takes the **lower** level.
- **Explorer allowlist** (`EXPLORER_HOSTS` in [`site/cards_v2.py`](site/cards_v2.py), exact hosts, after a leading `www.`; no userinfo, no port): etherscan.io, optimistic.etherscan.io, sepolia.etherscan.io, basescan.org, sepolia.basescan.org, arbiscan.io, nova.arbiscan.io, polygonscan.com, zkevm.polygonscan.com, bscscan.com, celoscan.io, lineascan.build, scrollscan.com, snowtrace.io, ftmscan.com, gnosisscan.io, era.zksync.network, blastscan.io, solscan.io, explorer.solana.com, solana.fm, blockscout.com, eth.blockscout.com, base.blockscout.com, optimism.blockscout.com, gnosis.blockscout.com, mempool.space, blockstream.info, blockchair.com, explorer.hiro.so, tronscan.org, tonviewer.com, tonscan.org, suiscan.xyz, explorer.aptoslabs.com, oklink.com, kitescan.ai. A new explorer is added in code and here, in the same change.
- **Record format** (`record_url_ok()`, used for a curator's level 3 and a custody `contract_url`). The code checks the FORMAT only; the curator checks the content. The URL is printable ASCII, **https**, has no query or fragment, its host is exactly one of the explorers in the explorer → network map (`RECORD_ROUTES`), and its whole path (an optional trailing slash aside) is one of that explorer's record routes with a well-formed identifier of its network (hex is case-insensitive, base58 is the Bitcoin alphabet, a block number has no leading zero and at most 12 digits; route names are lowercase):
  - **EVM** (the EVM hosts above, `eth.`/`base.`/`optimism.`/`gnosis.blockscout.com` and kitescan.ai included): `/tx/0x<64 hex>`, `/address/0x<40 hex>`, `/token/0x<40 hex>`, `/block/<number or 0x + 64 hex>`.
  - **Solana**: solscan.io `/tx/<base58, 86-88>`, `/account/<base58, 32-44>`, `/token/<base58, 32-44>`, `/block/<number>`; explorer.solana.com and solana.fm `/tx/…`, `/address/…`, `/block/<number>`.
  - **Bitcoin** (mempool.space, blockstream.info): `/tx/<64 hex>`, `/address/<base58 26-35 starting 1 or 3, or bech32 bc1…>`, `/block/<64 hex or number>`.
  - **TON**: tonviewer.com `/transaction/<64 hex>`, `/<TON address>`; tonscan.org `/tx/<64 hex>`, `/address/<TON address>`.
  - **Sui** (suiscan.xyz): `/mainnet/tx/<base58, 43-44>`, `/mainnet/account/0x<64 hex>`. **Aptos** (explorer.aptoslabs.com): `/txn/<0x + 64 hex or version>`, `/account/0x<64 hex>`.
  - Explorers outside this map (blockscout.com, blockchair.com, oklink.com, tronscan.org, explorer.hiro.so) have no record format, so a level 3 there is not accepted until the map gains them (a code change with tests, in the same change as this list).
- The **card level** is the highest level reached by its *supported* money and activity claims (`evidence_level` {level, id, label, claims_counted}). A card without one shows "not recorded yet". In the per-entry JSON every money and activity claim carries `evidence_level` (1, 2 or 3) and `evidence_label`. A claim without a source URL has no level.

#### Curator review of a level

A curator may set the level of a card's claims with one source URL by hand in
[`data/evidence-levels.json`](data/evidence-levels.json), **only after opening that source**:

```json
"touchstone": [{"source_url": "https://touchstone.cv/d/…", "evidence_level": 2,
                "evidence_note": "Public JSON disclosure log: signed, sequenced entries with server timestamps that anyone can open.",
                "reviewed_on": "2026-10-19"}]
```

- **Level 3** only for a record the curator opened on the explorer, whose URL passes the record format above (check.py fails otherwise).
- **Level 2** for a public JSON log, feed or data file on a plain path, or a live dashboard page whose figures are in the page. A public, dated Git commit history (`https://github.com/<owner>/<repo>/commits`) is a public log, level 2: no ledger of money, so never level 3.
- **Lower** a level when the source carries no live figures: a dated report on a dashboard host, an endpoint that lists zero items or a placeholder, an error, or a host that was offline at review. When unsure, take the lower level.
- An entry must change the level (check.py fails on an entry equal to the URL rule). The note is required, at most 200 characters, in positive wording, and is published on the claim as `evidence_note`. Every entry gets a `relabelled` line in [`data/events.jsonl`](data/events.jsonl) on its `reviewed_on` day.

### Keys and books

An idea from The Caretaker, an agent on The Colony. Three questions per card, each `{state, value, label, source_url, quote}`:

- **Who holds the keys** (`keys`): custody of funds or accounts: `operator`, `user_wallet` (users hold their own wallet or keys) or `smart_contract`. Each value has a `basis`:
  - `operator_says` (the default): custody rests on the operator's own text. The card shows it as the operator's claim: "The operator says a smart contract holds the funds", "The operator says it holds the funds", "The operator says users hold their own wallet or keys".
  - `onchain_verified`: only for `smart_contract`, and only with `contract_url`, the explorer page of the contract's **address or token** on a public block explorer (`/address/<addr>`, `/token/<addr>`, `/account/<addr>`; checked by the build with the record format above). A transaction or block page (`/tx/`, `/block/`) is a public record too, but it does not name the contract that holds the funds, so it is not accepted. Then the card states it plainly and links the contract.
- **Open books** (`books`): its money figures (payouts, balances, volume) are publicly checkable: `public_transactions` or `public_dashboard`.
- **People behind it** (`people`): `named`, with the **organization** behind it (a company, team or project) as a source names it. The Atlas lists places, not people: an individual person's name is never recorded here. `names` must be exactly one entry of the curated allowlist `org_names` in the same file, with nothing after it (no notes in brackets: free text next to a name could carry a person's name); the build check fails on any other value. How the organization relates to the platform goes in the optional `role`, one of a fixed list: `acquired` (shown as "Meta (acquired it)") or `announced` ("Soapbox (announced it)"). When a source names only a person, the field stays "not recorded yet".

Rules:

- A value is filled **only from a supported claim already on the card**. Curated values live in [`data/keys-and-books.json`](data/keys-and-books.json): `source_url` must be that claim's source URL and `quote` must appear in its quote or statement; the build check fails otherwise.
- Open books are also derived automatically: the highest-level supported money-flow claim at ladder level 2 or 3 (3 only from a curator) fills `books` with its source.
- Every other answer is `state: not_recorded`, shown as "not recorded yet". The wording is always neutral and positive; check.py fails on negative words in the site-written v2 text.

### First task

One simple first step for a newcomer, human or agent, kept in [`data/first-tasks.json`](data/first-tasks.json) (title, steps, done_when, contributed_by, contributed_via, source_url, verified_by, verified_on, verification; optional no_code). A task proposed by a platform or a contributor is published only after a curator did it, with credit "Contributed by <nick>" and a link to where it was proposed. Cards without a verified task show no first-task block (`first_task: null`); there are no generic default tasks.

- **Nothing to download or run.** A first task is done by reading public pages, for example in a browser. One fail-closed rule (`task_text_errors()` in `site/cards_v2.py`): a task may not have a `code` field, and no text field (title, steps, done_when, no_code, verification, contributor and verifier fields) may contain a download, install or run instruction: backticks, a shell command or package tool (`curl`, `wget`, `pip`, `npm`, `npx`, `uv`, `bash`, `python` and similar), the words download, install, script, shell, terminal or command line, a pipe, a shell prompt, a link to a script or binary file (`.py`, `.sh`, `.js`, `.exe` and similar), or a raw.githubusercontent.com or gist link. Prose that trips the rule is reworded.
- **No hidden text.** No control characters (outside steps), Unicode line separators (U+2028, U+2029, U+0085), zero-width characters (U+200B-U+200D, U+2060, U+FEFF) or bidi controls (U+202A-U+202E, U+2066-U+2069).
- **Manual review.** The rule is a floor: a curator does every new or changed task before it is published and records what was checked in `verification`, with a `corrected` event on its `verified_on` day.

## Weekly screenshots

Homepage screenshots (the `preview` field) live on the orphan branch `atlas-screens`, not on `main`. The GitHub Actions workflow **Atlas weekly screenshots** ([`.github/workflows/screens.yml`](../.github/workflows/screens.yml), Sundays 04:00 UTC, or by hand for chosen IDs) re-captures them with [`tools/screens.py`](tools/screens.py) and opens a pull request into `atlas-screens` when an image was added or replaced. It **never merges on its own**: a curator compares every old and new image (previews are attached to the run) and merges by hand. Per-card settings are in [`tools/screens-overrides.json`](tools/screens-overrides.json).
