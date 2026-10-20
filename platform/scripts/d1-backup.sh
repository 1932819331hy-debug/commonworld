#!/usr/bin/env bash
# Commonworld v1 - D1 backup: export -> gzip -> (optional age encryption) -> sha256 -> manifest JSON.
#
#   scripts/d1-backup.sh <db-name> [--env X] [--out DIR] [--local] [--cwd DIR]
#
#   scripts/d1-backup.sh commonworld-prod --env production
#   scripts/d1-backup.sh commonworld-staging --env staging --out /tmp/cwbk
#
# Writes into --out (default ./backups, relative to where you run it):
#   <db>-<UTC stamp>.sql.gz            the dump (or .sql.gz.age when AGE_RECIPIENT is set; then no plain copy is kept)
#   <db>-<UTC stamp>.sha256            `sha256sum -c` file for the artifact
#   <db>-<UTC stamp>.manifest.json     timestamp (UTC), db, env, row count per table, sqlite_sequence counters,
#                                      last applied migration (d1_migrations), artifact name/size/sha256.
#                                      Holds no row data, only counts - safe to keep unencrypted next to the dump.
# and prints the three paths (last line: the manifest).
#
# Read-only on the database: `wrangler d1 export` only reads. Counts are computed from a local sqlite load of the
# dump itself (D1 does not allow PRAGMA table_info remotely, and counting the dump is what a restore must match).
#
# Encryption: set AGE_RECIPIENT to an age PUBLIC key (age1...). The private key never comes near this script or CI;
# only whoever restores needs it (scripts/d1-restore.sh reads AGE_IDENTITY_FILE). Key generation is a launch-day
# owner step, see docs/ops/BACKUP-RESTORE.md.
#
# Needs: wrangler (npx, from platform/), python3, gzip, sha256sum, and `age` only if AGE_RECIPIENT is set.
# Auth: CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID in the environment (never printed), or a wrangler login.
set -euo pipefail

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

DB="" ; ENV_NAME="" ; OUT="./backups" ; WHERE="--remote" ; WCWD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_NAME="${2:?--env needs a value}"; shift 2 ;;
    --out) OUT="${2:?--out needs a value}"; shift 2 ;;
    --local) WHERE="--local"; shift ;;
    --cwd) WCWD="${2:?--cwd needs a value}"; shift 2 ;;
    -h|--help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [ -z "$DB" ] && DB="$1" || { echo "unexpected argument: $1" >&2; usage; }; shift ;;
  esac
done
[ -n "$DB" ] || usage

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$HERE/d1_kit.py"
V1="$(cd "$HERE/.." && pwd)"
WCWD="${WCWD:-$V1}"
WRANGLER="${WRANGLER:-$V1/node_modules/.bin/wrangler}"
[ -x "$WRANGLER" ] || WRANGLER="npx --yes wrangler"
ENV_ARGS=() ; [ -n "$ENV_NAME" ] && ENV_ARGS=(--env "$ENV_NAME")

if [ -n "${AGE_RECIPIENT:-}" ]; then
  command -v age >/dev/null || { echo "AGE_RECIPIENT is set but 'age' is not installed" >&2; exit 1; }
  case "$AGE_RECIPIENT" in age1*) ;; *) echo "AGE_RECIPIENT must be an age public key (age1...)" >&2; exit 1 ;; esac
fi

umask 077
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
# One clock read for both (python, not `date`, so the format is identical everywhere).
read -r STAMP CREATED < <(python3 -c 'import datetime as d; t=d.datetime.now(d.timezone.utc); print(t.strftime("%Y%m%dT%H%M%SZ"), t.strftime("%Y-%m-%dT%H:%M:%SZ"))')
BASE="$OUT/$DB-$STAMP"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT   # the plain .sql never outlives this script

echo "d1-backup: exporting $DB ${ENV_NAME:+(env $ENV_NAME) }$WHERE ..." >&2
T0=$(date +%s)
(cd "$WCWD" && $WRANGLER d1 export "$DB" "$WHERE" "${ENV_ARGS[@]}" --output "$TMP/dump.sql" -y) >"$TMP/wrangler.log" 2>&1 || {
  echo "d1-backup: wrangler d1 export failed:" >&2; grep -v -i 'token' "$TMP/wrangler.log" | tail -20 >&2; exit 1; }
[ -s "$TMP/dump.sql" ] || { echo "d1-backup: export produced an empty file" >&2; exit 1; }
echo "d1-backup: exported $(wc -c <"$TMP/dump.sql") bytes in $(( $(date +%s) - T0 )) s" >&2

python3 "$KIT" counts "$TMP/dump.sql" >"$TMP/counts.json"
SQL_SHA="$(sha256sum "$TMP/dump.sql" | cut -d' ' -f1)"

gzip -9 -n -c "$TMP/dump.sql" >"$TMP/dump.sql.gz"
if [ -n "${AGE_RECIPIENT:-}" ]; then
  ART="$BASE.sql.gz.age"
  age -r "$AGE_RECIPIENT" -o "$ART" "$TMP/dump.sql.gz"
  ENCRYPTED=true
else
  ART="$BASE.sql.gz"
  mv "$TMP/dump.sql.gz" "$ART"
  ENCRYPTED=false
fi
ART_SHA="$(sha256sum "$ART" | cut -d' ' -f1)"
(cd "$OUT" && sha256sum "$(basename "$ART")") >"$BASE.sha256"

WVER="$( (cd "$WCWD" && $WRANGLER --version 2>/dev/null) | tail -1 || true)"
python3 - "$TMP/counts.json" "$BASE.manifest.json" <<PY
import json, sys
c = json.load(open(sys.argv[1]))
m = {
  "format": "commonworld-d1-backup/1",
  "created_utc": "$CREATED",
  "db": "$DB",
  "env": "$ENV_NAME" or None,
  "source": "${WHERE#--}",
  "wrangler": "$WVER" or None,
  "last_migration": c["last_migration"],
  "table_count": c["table_count"],
  "total_rows": c["total_rows"],
  "tables": c["tables"],
  "sqlite_sequence": c["sqlite_sequence"],
  "sql_sha256": "$SQL_SHA",
  "artifact": {"file": "$(basename "$ART")", "bytes": $(wc -c <"$ART"), "sha256": "$ART_SHA",
               "gzip": True, "encrypted": $( [ "$ENCRYPTED" = true ] && echo True || echo False ),
               "age_recipient": "${AGE_RECIPIENT:-}" or None},
}
json.dump(m, open(sys.argv[2], "w"), indent=2, sort_keys=False)
open(sys.argv[2], "a").write("\n")
PY

LAST="$(python3 -c '
import json, sys
m = json.load(open(sys.argv[1])); l = m["last_migration"]
print("%d tables, %d rows, last migration %s" % (m["table_count"], m["total_rows"], ("%s %s" % (l["id"], l["name"])) if l else "none"))
' "$BASE.manifest.json")"
echo "d1-backup: OK $DB: $LAST, encrypted=$ENCRYPTED" >&2
echo "$ART"
echo "$BASE.sha256"
echo "$BASE.manifest.json"
