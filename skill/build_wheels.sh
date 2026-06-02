#!/usr/bin/env bash
# Build skill/wheels/ — bundled wheels for offline pip install.
# Target: Anthropic API code-execution sandbox (manylinux2014_x86_64,
# Python 3.12 — sandbox version drifts (was 3.11 in May 2026, 3.12 in
# Jun 2026). Bump PYTHON_VERSION when it drifts again. See
# `docs/journal/` for the latest empirical version.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

PLATFORM="manylinux2014_x86_64"
PYTHON_VERSION="3.12"
WHEELS_DIR="skill/wheels"

echo "== Building groundling wheel =="
rm -rf dist/
uv build --wheel

echo "== Populating $WHEELS_DIR =="
rm -f "$WHEELS_DIR"/*.whl
cp dist/groundling-*.whl "$WHEELS_DIR/"

# Resolve groundling's full transitive closure by passing the local
# wheel as the package to download. pip walks groundling's own
# dependency declarations, so we don't have to enumerate them here
# (and miss transitives like `jiter` which would silently break the
# install at runtime). `uv pip` has no `download` subcommand, so we
# shell out to real pip via `uv run --with pip`.
uv run --with pip --no-project -- python -m pip download \
    --platform "$PLATFORM" \
    --python-version "$PYTHON_VERSION" \
    --only-binary=:all: \
    --dest "$WHEELS_DIR" \
    --find-links "$WHEELS_DIR" \
    groundling

rm -rf dist/

echo ""
echo "Bundled wheels:"
ls -lh "$WHEELS_DIR"/*.whl
