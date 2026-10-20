#!/usr/bin/env bash
# Commonworld v1 - D1 restore from a d1-backup.sh dump, in one command, then verify row counts: PASS / FAIL.
#
#   scripts/d1-restore.sh <dump> <target-db> [--env X] [--manifest FILE] [--local] [--cwd DIR] [--keep-workdir] [--verify-only] [--i-know]
#
#   scripts/d1-restore.sh backups/commonworld-prod-20261019T030000Z.sql.gz.age commonworld-restore-check
#
# <dump>      .sql, .sql.gz or .sql.gz.age (age: needs AGE_IDENTITY_FILE = path to the private key file).
# <target-db> an EXISTING, EMPTY D1 database (create it first: npx wrangler d1 create <name>). The script refuses a
#             target that already has tables: restore into a fresh DB, verify, then point the Worker's database_id at
#             it. For an in-place rewind of the live DB use D1 Time Travel instead (docs/ops/BACKUP-RESTORE.md).
# --manifest  defaults to <dump without .sql*>.manifest.json next to the dump; if found, the artifact sha256 is
#             checked and the target is compared with the manifest's counts. Without one, the counts come from the dump.
# --verify-only  skip the import, only compare an already restored target with the manifest / dump.
# --i-know    required to target a production DB name (commonworld-prod, or any name in CW_PROD_DB_NAMES).
#
# Method (restore drill 2026-10-18; a raw dump import fails on FK order and D1 commits each --file separately):
#   all CREATE TABLE -> rows per table in FK-parent-first order -> indexes/triggers/views -> sqlite_sequence,
#   one `wrangler d1 execute --file` per step (scripts/d1_kit.py plan), then one count SELECT per 25 tables.
# Exit code: 0 = PASS, 1 = FAIL or error, 2 = usage / refused.
set -euo pipefail

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

DUMP="" ; TARGET="" ; ENV_NAME="" ; MANIFEST="" ; WHERE="--remote" ; WCWD="" ; KEEP=0 ; IKNOW=0 ; VERIFY_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_NAME="${2:?--env needs a value}"; shift 2 ;;
    --manifest) MANIFEST="${2:?--manifest needs a value}"; shift 2 ;;
    --local) WHERE="--local"; shift ;;
    --cwd) WCWD="${2:?--cwd needs a value}"; shift 2 ;;
    --keep-workdir) KEEP=1; shift ;;
    --i-know) IKNOW=1; shift ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    -h|--help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) if [ -z "$DUMP" ]; then DUMP="$1"; elif [ -z "$TARGET" ]; then TARGET="$1"; else echo "unexpected argument: $1" >&2; usage; fi; shift ;;
  esac
done
[ -n "$DUMP" ] && [ -n "$TARGET" ] || usage
[ -f "$DUMP" ] || { echo "d1-restore: no such file: $DUMP" >&2; exit 2; }

PROD_NAMES="${CW_PROD_DB_NAMES:-commonworld-prod}"
for p in $PROD_NAMES; do
  if [ "$TARGET" = "$p" ] && [ "$IKNOW" != 1 ]; then
    echo "d1-restore: REFUSED: '$TARGET' is the production database. Restore into a new empty DB instead," >&2
    echo "            or re-run with --i-know if you really mean to write into production." >&2
    exit 2
  fi
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$HERE/d1_kit.py"
V1="$(cd "$HERE/.." && pwd)"
WCWD="${WCWD:-$V1}"
WRANGLER="${WRANGLER:-$V1/node_modules/.bin/wrangler}"
[ -x "$WRANGLER" ] || WRANGLER="npx --yes wrangler"
ENV_ARGS=() ; [ -n "$ENV_NAME" ] && ENV_ARGS=(--env "$ENV_NAME")

umask 077
WORK="$(mktemp -d)"
cleanup() { if [ "$KEEP" = 1 ]; then echo "d1-restore: workdir kept: $WORK (contains row data - delete it)" >&2; else rm -rf "$WORK"; fi; }
trap cleanup EXIT

if [ -z "$MANIFEST" ]; then
  guess="${DUMP%.age}"; guess="${guess%.gz}"; guess="${guess%.sql}.manifest.json"
  [ -f "$guess" ] && MANIFEST="$guess"
fi

# 1. Integrity + decrypt/decompress into the private workdir.
if [ -n "$MANIFEST" ]; then
  want="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["sha256"])' "$MANIFEST")"
  have="$(sha256sum "$DUMP" | cut -d' ' -f1)"
  [ "$want" = "$have" ] || { echo "d1-restore: FAIL: sha256 of $DUMP does not match the manifest" >&2; exit 1; }
  echo "d1-restore: sha256 ok (manifest $(basename "$MANIFEST"))" >&2
else
  echo "d1-restore: no manifest found - expected counts will come from the dump itself" >&2
fi
case "$DUMP" in
  *.age)
    [ -n "${AGE_IDENTITY_FILE:-}" ] || { echo "d1-restore: encrypted dump: set AGE_IDENTITY_FILE to the age private key file" >&2; exit 1; }
    age -d -i "$AGE_IDENTITY_FILE" "$DUMP" | gunzip -c >"$WORK/dump.sql" ;;
  *.gz) gunzip -c "$DUMP" >"$WORK/dump.sql" ;;
  *) cp "$DUMP" "$WORK/dump.sql" ;;
esac
if [ -n "$MANIFEST" ]; then
  want="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("sql_sha256") or "")' "$MANIFEST")"
  if [ -n "$want" ] && [ "$want" != "$(sha256sum "$WORK/dump.sql" | cut -d' ' -f1)" ]; then
    echo "d1-restore: FAIL: decompressed SQL does not match sql_sha256 in the manifest" >&2; exit 1; fi
fi

# 2. Expected counts: from the dump; must agree with the manifest when there is one.
python3 "$KIT" counts "$WORK/dump.sql" >"$WORK/expected.json"
if [ -n "$MANIFEST" ]; then
  python3 - "$MANIFEST" "$WORK/expected.json" <<'PY' || exit 1
import json, sys
m, d = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
if m["tables"] != d["tables"] or m.get("sqlite_sequence", {}) != d["sqlite_sequence"]:
    print("d1-restore: FAIL: the dump's own counts differ from its manifest", file=sys.stderr); sys.exit(1)
PY
  cp "$MANIFEST" "$WORK/expected.json"
fi

w() { (cd "$WCWD" && $WRANGLER d1 execute "$TARGET" "$WHERE" "${ENV_ARGS[@]}" -y "$@"); }

if [ "$VERIFY_ONLY" != 1 ]; then
# 3. Target must exist and be empty.
if ! w --json --command "SELECT count(*) AS n FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'" >"$WORK/precheck.json" 2>"$WORK/precheck.err"; then
  echo "d1-restore: cannot query target '$TARGET' (does it exist? create it with: npx wrangler d1 create $TARGET):" >&2
  grep -v -i token "$WORK/precheck.err" | tail -5 >&2; exit 1
fi
N="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[0]["results"][0]["n"])' "$WORK/precheck.json")"
if [ "$N" != 0 ]; then
  echo "d1-restore: REFUSED: target '$TARGET' already has $N table(s). Restore into a new empty database." >&2; exit 2
fi

# 4. Plan + import, one file per step, in order.
python3 "$KIT" plan "$WORK/dump.sql" "$WORK/plan" >"$WORK/files.txt"
COUNT="$(wc -l <"$WORK/files.txt")"
echo "d1-restore: importing into $TARGET ${ENV_NAME:+(env $ENV_NAME) }$WHERE in $COUNT steps ..." >&2
T0=$(date +%s); i=0
while read -r f; do
  i=$((i+1))
  if ! w --file "$f" >"$WORK/step.log" 2>&1; then
    echo "d1-restore: FAIL at step $i/$COUNT ($(basename "$f")):" >&2
    grep -v -i token "$WORK/step.log" | grep -iE 'error|✘' | head -5 >&2
    echo "d1-restore: the target is now partially filled - delete it and start again with a fresh DB." >&2
    exit 1
  fi
  printf '  %2d/%d %s\n' "$i" "$COUNT" "$(basename "$f")" >&2
done <"$WORK/files.txt"
echo "d1-restore: import done in $(( $(date +%s) - T0 )) s" >&2
fi

# 5. Verify every table's count (and the sqlite_sequence counters) against the expected numbers.
python3 "$KIT" verify-sql "$WORK/expected.json" >"$WORK/verify.sql"
j=0; RESULTS=()
while read -r q; do
  j=$((j+1))
  w --json --command "$q" >"$WORK/verify-$j.json" 2>"$WORK/verify-$j.err" || {
    echo "d1-restore: FAIL: verification query $j failed:" >&2; grep -v -i token "$WORK/verify-$j.err" | tail -5 >&2; exit 1; }
  RESULTS+=("$WORK/verify-$j.json")
done <"$WORK/verify.sql"
echo "d1-restore: verifying $TARGET against $( [ -n "$MANIFEST" ] && echo "manifest" || echo "dump counts" ):"
python3 "$KIT" compare "$WORK/expected.json" "${RESULTS[@]}"
