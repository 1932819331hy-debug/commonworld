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
| `CW_PRIVATE_TERMS` | GitHub → repository secrets (already used by CI) | owner | Forbidden-text check of the Atlas build. |
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
   on `main` and pastes the full 40-character sha of the commit to release.
7. **Approve.** The run checks that the sha is on `main` and that `platform/` exists, then stops at the
   `production` environment. The owner reviews and clicks *Approve and deploy*.
8. **The job then:** checks out exactly that commit → installs → typecheck → tests → builds the Atlas into the
   Worker's assets → prints the database's Time Travel bookmark → applies pending D1 migrations →
   `wrangler deploy --env production` → smoke test (`/`, `/health` must say `"environment":"production"`,
   `/api/v1/index.json`).

Only one production deploy runs at a time; a second one waits, a running one is never cancelled.

## Rollback

- **Code:** `npx wrangler rollback --env production` (run in `platform/` with the production token) switches the
  Worker back to the previous version in seconds. To go forward again:
  `npx wrangler versions deploy <version-id>@100% --env production`. Or run the workflow again with an older sha
  from `main`.
- **Database:** a Worker rollback does **not** undo migrations. Every migration should therefore stay compatible
  with the previous Worker version. If data must be restored, use D1 Time Travel with the bookmark printed by the
  deploy run: `npx wrangler d1 time-travel restore commonworld-prod --env production --bookmark=<bookmark>`. This
  overwrites the live database, so only on the owner's decision.
- **The very first production deploy** has no earlier working version to roll back to; that case follows the
  launch runbook (routes off, domains back to the previous host).

## Who can approve

Required reviewer of the `production` environment: the repository owner (`@nerd27dk`). He is currently the only
reviewer, so self-review is allowed for this environment. Nobody else, and no bot or agent, can approve a
production deploy. Agents can prepare releases (branch, PR, staging, the sha to deploy), never approve them.
