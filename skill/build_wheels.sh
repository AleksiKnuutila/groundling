#!/usr/bin/env bash
# Build skill/wheels/ — bundled wheels for offline pip install.
# Target: Claude.ai sandbox (manylinux2014_x86_64, Python 3.12 per
# empirical reports).
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

# Runtime deps must cover everything groundling declares in
# pyproject.toml — pip resolves all required deps when installing
# `groundling` offline, so anthropic/typer/python-dotenv are bundled
# even though the skill scripts themselves only need
# pymupdf/markdown-it-py/jinja2. Use --only-binary=:all: to force
# pre-built wheels (we cannot compile in the sandbox). `uv pip` has
# no `download` subcommand, so we shell out to real pip via
# `uv run --with pip`.
uv run --with pip --no-project -- python -m pip download \
    --platform "$PLATFORM" \
    --python-version "$PYTHON_VERSION" \
    --only-binary=:all: \
    --dest "$WHEELS_DIR" \
    pymupdf markdown-it-py jinja2 \
    anthropic typer python-dotenv

rm -rf dist/

echo ""
echo "Bundled wheels:"
ls -lh "$WHEELS_DIR"/*.whl
