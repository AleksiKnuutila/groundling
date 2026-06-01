#!/usr/bin/env bash
# End-to-end skill smoke: build zip, install from bundled wheels into
# a fresh venv, run prep + render on the BYD corpus, verify single-file
# self-contained answer.html.
#
# Idempotent: re-running cleans up prior runs.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

./skill/build_wheels.sh

echo "== Building skill zip =="
mkdir -p skill/dist
ZIP="$REPO_ROOT/skill/dist/groundling-skill.zip"
rm -f "$ZIP"
( cd skill && zip -r "$ZIP" SKILL.md reference.md LICENSE.txt scripts wheels )
echo "Built: $ZIP ($(du -h "$ZIP" | cut -f1))"

echo "== Simulating sandbox install (resolver-only on dev host) =="
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

unzip -q "$ZIP" -d "$TMP/skill"

# Validate the wheel bundle is complete via pip's offline resolver.
# We can't actually run the manylinux2014_x86_64 wheels on aarch64 dev
# hosts, but we can confirm pip would resolve everything against the
# Claude.ai target platform.
uv run --python 3.12 --with pip --no-project -- python -m pip install \
    --no-index \
    --find-links "$TMP/skill/wheels" \
    --platform manylinux2014_x86_64 \
    --python-version 3.12 \
    --only-binary=:all: \
    --target "$TMP/site-packages" \
    groundling
test -d "$TMP/site-packages/groundling"

echo "== Functional check: prep + render with host-arch deps =="
# Use the worktree's dev venv (which has the same groundling source
# installed editable) to actually run the scripts on the BYD corpus.
CORPUS=/tmp/grounded-qa-e2e
test -d "$CORPUS" || { echo "no BYD corpus at $CORPUS"; exit 1; }

PREP="$TMP/prep"
uv run python "$TMP/skill/scripts/prep.py" \
    --corpus "$CORPUS" --out "$PREP"
test -f "$PREP/BYD-2025-Q1.linearized.txt"
test -f "$PREP/BYD-2025-Q1.chunks.json"

ANS="$TMP/answer.md"
cat > "$ANS" <<'MD'
Q1 revenue was [RMB 170 billion](chunk://BYD-2025-Q1/p2:t0r1c1 "170,360,448,000.00").
MD

OUT="$TMP/answer.html"
uv run python "$TMP/skill/scripts/render.py" \
    --prep-dir "$PREP" --corpus "$CORPUS" \
    --answer "$ANS" --out "$OUT" 2>&1 | tail -3

test -f "$OUT"
grep -q 'class="cite"' "$OUT"
grep -q 'data:image/png;base64,' "$OUT"
! grep -q 'src="cites/' "$OUT"
! grep -q '<iframe' "$OUT"

echo "== Bootstrap idempotency check =="
# Bootstrap should detect the sentinel file from a prior run and skip.
# Use a custom sentinel to keep this self-contained.
SENTINEL="$TMP/.installed-test"
GROUNDLING_SENTINEL="$SENTINEL" uv run python "$TMP/skill/scripts/bootstrap.py" --dry-run | grep -qi "would install"
GROUNDLING_SENTINEL="$SENTINEL" uv run python "$TMP/skill/scripts/bootstrap.py" --dry-run | grep -qi "already installed"

echo ""
echo "SKILL SMOKE TEST PASSED"
echo "Zip size: $(du -h "$ZIP" | cut -f1)"
echo "answer.html size: $(du -h "$OUT" | cut -f1)"
