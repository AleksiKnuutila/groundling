#!/usr/bin/env bash
# Build the release-ready Claude Skill zip.
#
# The Anthropic Skills API rejects zips with files at the root —
# everything must be inside a single top-level folder. We use
# `groundling/` (matches the SKILL.md `name:` field).
#
# Output: skill/dist/groundling-skill.zip
#
# Usage: ./skill/build_zip.sh [version]
#   version (optional) — appended to filename, e.g. v0.1.0 →
#     groundling-skill-v0.1.0.zip
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

VERSION="${1:-}"
if [ -n "$VERSION" ]; then
    ZIP_NAME="groundling-skill-${VERSION}.zip"
else
    ZIP_NAME="groundling-skill.zip"
fi
ZIP="$REPO_ROOT/skill/dist/$ZIP_NAME"

./skill/build_wheels.sh

echo "== Staging files =="
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/groundling"
cp -r \
    skill/SKILL.md \
    skill/reference.md \
    skill/LICENSE.txt \
    skill/scripts \
    skill/wheels \
    "$STAGE/groundling/"

# Strip pycache + .gitkeep noise that snuck in via the source dirs.
find "$STAGE/groundling" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/groundling" -name .gitkeep -delete

echo "== Building $ZIP_NAME =="
mkdir -p skill/dist
rm -f "$ZIP"
( cd "$STAGE" && zip -qr "$ZIP" groundling )

# Also emit a stable-named copy for `releases/latest/download/`
# install URLs that don't have to be bumped per release.
if [ -n "$VERSION" ]; then
    STABLE="$REPO_ROOT/skill/dist/groundling-skill.zip"
    cp "$ZIP" "$STABLE"
    echo "Also wrote $STABLE"
fi

echo ""
echo "Built $ZIP"
du -h "$ZIP"
echo ""
echo "Top-level zip entries:"
unzip -l "$ZIP" | awk 'NR>3 {print $NF}' | grep -v '^$' | awk -F/ '{print $1}' | sort -u
