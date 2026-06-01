"""Idempotent bootstrap: install groundling from bundled wheels exactly once."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BOOTSTRAP = Path(__file__).parent.parent / "skill" / "scripts" / "bootstrap.py"


def test_bootstrap_creates_sentinel_on_first_run(tmp_path):
    """First invocation runs pip install and writes the sentinel file."""
    env = {**os.environ, "GROUNDLING_SENTINEL": str(tmp_path / ".installed")}
    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--dry-run"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / ".installed").exists()
    assert ("would install" in result.stdout.lower()
            or "installed" in result.stdout.lower())


def test_bootstrap_skips_on_second_run(tmp_path):
    """If sentinel exists, bootstrap is a no-op (no pip invocation)."""
    sentinel = tmp_path / ".installed"
    sentinel.touch()
    env = {**os.environ, "GROUNDLING_SENTINEL": str(sentinel)}
    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--dry-run"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert ("already installed" in result.stdout.lower()
            or "skip" in result.stdout.lower())
