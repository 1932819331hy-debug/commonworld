# Deploying the platform

How the Commonworld platform (the Cloudflare Worker and its D1 database, folder `platform/`) gets to
`commonworld.one`. The Atlas is built from this same repository and shipped inside the Worker, so one deploy
releases both.

Until `platform/` exists in this repository, the production workflow does nothing.

## Environments

| | Staging | Production |
|---|---|---|
| Address | `staging.commonworld.one` | `commonworld.one` (and `www`) |
| Worker | `commonworld-api-staging` | `commonworld-api` |
| Database (D1) | `commonworld-staging` | `commonworld-prod` |
| Who deploys | the maintainers' agent (Hark), with its own staging-only Cloudflare token, outside GitHub | the GitHub workflow `Deploy platform (production)`, after the owner's approval |
| Token in GitHub | none | yes, as a secret of the GitHub environment `production` |

Staging is where every change is tried first. Production is only ever deployed from a commit that is already on
`main`.

## Secrets: what lives where

| Secret | Where | Who sets it | What it is for |
|---|---|---|---|
| `CLOUDFLARE_API_TOKEN` | GitHub → Settings → Environments → `production` → Environment secrets | owner | Production-only Cloudflare token. Scopes: Account → Workers Scripts: Edit, Account → D1: Edit, Zone `commonworld.one` → Workers Routes: Edit. Nothing else. Separate from the staging token. |
| `CLOUDFLARE_ACCOUNT_ID` | same place | owner | Which Cloudflare account to deploy to. Not secret on its own, kept next to the token. |
| `CW_PRIVATE_TERMS` | GitHub → repository secrets (already used by CI) | owner | Forbidden-text check of the Atlas build. Required: CI on `main` and on same-repo PRs, and the production deploy, stop without it; only PRs from forks (which get no secrets) skip the check with a warning. |
| `KEY_PEPPER` | **only in Cloudflare**, as a secret of the Worker `commonworld-api` | owner | Hashes API keys, login links, sessions and IPs. **Never in GitHub**, never in a commit, issue, log or chat. The workflow neither needs nor sees it. |

Because the Cloudflare token is an *environment* secret, GitHub hands it to the job only after the approval. A
workflow run on a pull request, a fork or any other branch never gets it.

## Release flow

1. **Branch.** Work happens on a branch, never directly on `main` for platform code.
2. **Pull request.** Open a PR into `main`. CI (`ci`, `quality` and the other checks) runs on it.
3. **Reviews.** At least one independent review besides the author (a person or a separate review agent). The
   code owner (`.github/CODEOWNERS`) is asked automatically for `/platform/` and `/.github/`.
4. **Staging.** The change is deployed to staging and checked there.
5. **Merge** into `main`.
6. **Start the deploy.** The owner opens Actions → *Deploy platform (production)* → *Run workflow*, keeps the branch
   on `main` and pastes the full 40-character sha of the commit to release. The field
   *allow_destructive_migration* stays empty (see [Database migrations](#database-migrations-expand--deploy--contract)).
7. **Approve.** The run checks that the sha is on `main` and that `platform/` exists, then stops at the
   `production` environment. The owner reviews and clicks *Approve and deploy*.
8. **The job then:** checks out exactly that commit → installs → typecheck → tests → reads `atlas/screens.lock`
   at that commit and fetches exactly that `atlas-screens` commit (it must be on the `atlas-screens` branch) →
   builds the Atlas into the Worker's assets → writes the **release manifest** → **migration gate** → prints the
   database's Time Travel bookmark → applies pending D1 migrations → `wrangler deploy --env production` → smoke
   test (`/`, `/health` must say `"environment":"production"`, `/api/v1/index.json`, each must answer 200).

### What a release is made of

The sha alone decides everything that goes live:

| Part | Comes from |
|---|---|
| Platform code (Worker, migrations) | the release sha |
| Atlas data | the same sha |
| Homepage screenshots | the `atlas-screens` commit written in `atlas/screens.lock` at the release sha |

The **release manifest** records the three shas, the sha256 of the built Atlas assets (`platform/.atlas-dist` packed
as a byte-reproducible `tar.gz`: sorted names, mtime 0, owner 0, `gzip -n`) and the wrangler version. It is printed
in the run's summary and kept 90 days as the artifact `release-manifest-<sha>`.

`atlas/screens.lock` is one line: the full sha of an `atlas-screens` commit. The weekly screenshots PR
(`screens.yml`) goes into the `atlas-screens` branch; after it is reviewed and merged, a separate PR on `main` bumps
`atlas/screens.lock` to the new `atlas-screens` commit. CI builds with the locked commit and shows a notice when
`atlas-screens` has newer commits than the lock.

Only one production deploy runs at a time; a second one waits, a running one is never cancelled.

## Database migrations: expand → deploy → contract

Migrations are applied **before** the new Worker goes live, so while they run (and after any Worker rollback) the
database is used by the code that is running now. Rules:

- **Every migration must be backward compatible with the currently running Worker.** Allowed in a normal release:
  new tables, new columns that are nullable or have a default, new indexes, backfills with a `WHERE`.
- **Destructive changes ship in a later release**, after the code no longer uses what they remove: first release
  stops reading/writing the column or table (expand + deploy), a following release drops or renames it (contract).
- **The gate.** Before any migration runs, the workflow lists the migrations not yet applied in production
  (`wrangler d1 migrations list commonworld-prod --remote --env production`) and runs
  `scripts/check-migrations.py` on them. It stops the run if one contains `DROP TABLE`, `ALTER TABLE … DROP`,
  `ALTER TABLE … RENAME`, `DELETE FROM` without `WHERE` or `UPDATE … SET` without `WHERE` (comments and strings are
  ignored), or if the list cannot be read. It is a safety net, not a replacement for reading the migration.
- **Override, one release only:** start the run with *allow_destructive_migration* = the same 40-character sha
  typed a second time. Anything else (empty, `yes`, a short sha) keeps the gate closed. Only for a contract step
  whose code side is already live.
- **Restore = D1 Time Travel** to the bookmark the run printed (step *Time Travel bookmark before migrations*, also
  in the run summary). In `platform/`, with the production token:

  ```sh
  # what the run printed (also shows the bookmark for the current moment)
  npx wrangler d1 time-travel info commonworld-prod --env production
  # bookmark for a moment in time, if the printed one is lost (UTC or unix timestamp)
  npx wrangler d1 time-travel info commonworld-prod --env production --timestamp=2026-10-20T08:00:00Z
  # restore: overwrites the live database, owner decision only
  npx wrangler d1 time-travel restore commonworld-prod --env production --bookmark=<bookmark>
  ```

  Roll the Worker back first (below) if the new code needs the new schema, then restore the database.
- **Drill it on staging before the first production use:** apply a test migration on `commonworld-staging`, note
  the bookmark, restore it with the same commands (`commonworld-staging`, `--env staging`) and check the data and
  the staging Worker. Only then rely on it for production.

The scanner runs in CI too (report only), and its unit tests are `tests/test_check_migrations.py`.

## Rollback

- **Code:** `npx wrangler rollback --env production` (run in `platform/` with the production token) switches the
  Worker back to the previous version in seconds. To go forward again:
  `npx wrangler versions deploy <version-id>@100% --env production`. Or run the workflow again with an older sha
  from `main`.
- **Database:** a Worker rollback does **not** undo migrations, which is why every migration must stay compatible
  with the previous Worker version (see above). If data must be restored, use D1 Time Travel with the bookmark
  printed by the deploy run (commands above). This overwrites the live database, so only on the owner's decision.
- **The very first production deploy** has no earlier working version to roll back to; that case follows the
  launch runbook (routes off, domains back to the previous host).

## Who can approve

Required reviewer of the `production` environment: the repository owner (`@nerd27dk`). The owner is the only
required reviewer and also the one who starts the run, so the environment setting **"Prevent self-reviews" stays
off, by design, for now** (single maintainer): with it on, nobody could approve a deploy. Revisit this when a second
maintainer exists: then turn "Prevent self-reviews" on and add that maintainer as a reviewer. Nobody else, and no
bot or agent, can approve a production deploy. Agents can prepare releases (branch, PR, staging, the sha to deploy),
never approve them.
