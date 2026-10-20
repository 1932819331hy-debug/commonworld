#!/usr/bin/env bash
# Copy the Commonworld trust engine (public repo commonworld-one/commonworld, folder trust/src) into src/trust-engine/.
# Usage: scripts/vendor-trust.sh /path/to/commonworld   (a checkout of the public repo)
# The CLI (cli.ts, Node-only) is not vendored. test/trust.test.ts checks the vendored copy keeps its header.
set -euo pipefail
PUB=${1:?path to a checkout of commonworld-one/commonworld}
SHA=$(git -C "$PUB" rev-parse --short HEAD)
DEST=$(cd "$(dirname "$0")/.." && pwd)/src/trust-engine
mkdir -p "$DEST/sources"
for f in types.ts domain.ts http.ts engine.ts index.ts sources/google-safe-browsing.ts sources/index.ts sources/list.ts; do
  { echo "// Vendored from commonworld-one/commonworld trust/src/$f @ $SHA (scripts/vendor-trust.sh). Do not edit here: change the engine upstream and re-vendor."; cat "$PUB/trust/src/$f"; } > "$DEST/$f"
done
echo "vendored trust engine @ $SHA into $DEST"
