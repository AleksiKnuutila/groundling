#!/usr/bin/env bash
# Smoke-test the pipx install path. Builds the wheel, installs into
# an isolated uv tool env, exercises the CLI end-to-end. Run before
# tagging a release or after touching pyproject.toml / build config.
#
# Usage: ./scripts/smoke_install.sh
# Exit: 0 on success, non-zero on any failure.

set -euo pipefail

# Resolve repo root regardless of where the script is invoked from.
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

echo "== Building wheel =="
rm -rf dist/
uv build --wheel

WHEEL=$(ls -t dist/groundling-*.whl | head -1)
test -f "$WHEEL"
echo "Built: $WHEEL"

echo "== Installing into isolated tool env =="
uv tool install --force "$WHEEL"

echo "== Verifying entry point =="
groundling --help >/dev/null

echo "== Verifying bundled template via 'instructions' =="
groundling instructions | head -5 | grep -q "Grounded Q&A — groundling"

echo "== Verifying init in a temp dir =="
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

groundling init
test -f AGENTS.md
grep -q "BEGIN GROUNDLING INSTRUCTIONS v1" AGENTS.md

echo "== Verifying init idempotency =="
groundling init
count=$(grep -c "BEGIN GROUNDLING INSTRUCTIONS v1" AGENTS.md)
test "$count" = "1" || {
    echo "FAIL: expected 1 BEGIN marker, found $count"
    exit 1
}

echo "== Verifying init preserves user content =="
printf '\n# My own notes\n\nHere is some prose.\n' >> AGENTS.md
groundling init
grep -q "My own notes" AGENTS.md

cd "$REPO_ROOT"
echo "== Cleanup =="
uv tool uninstall groundling
rm -rf dist/

echo ""
echo "SMOKE TEST PASSED"
