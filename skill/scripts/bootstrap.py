#!/usr/bin/env python3
"""Idempotent skill bootstrap: install groundling from bundled wheels.

Runs once per sandbox lifetime — the sentinel file prevents re-install
on subsequent invocations. Override sentinel location via
GROUNDLING_SENTINEL env var (used by tests).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_SENTINEL = "/tmp/.groundling-installed"


def main():
    p = argparse.ArgumentParser(description="Install groundling skill deps.")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip pip install; still write sentinel.")
    args = p.parse_args()

    sentinel = Path(os.environ.get("GROUNDLING_SENTINEL", DEFAULT_SENTINEL))
    if sentinel.exists():
        print(f"groundling already installed (sentinel: {sentinel}); skipping.")
        return

    skill_dir = Path(__file__).parent.parent
    wheels = skill_dir / "wheels"

    if args.dry_run:
        print(f"[dry-run] would install groundling from {wheels}/")
    else:
        if not wheels.exists() or not list(wheels.glob("*.whl")):
            print(f"error: no wheels in {wheels}", file=sys.stderr)
            sys.exit(1)
        # --break-system-packages: the Anthropic code-exec sandbox uses
        # a PEP 668 externally-managed system Python; pip refuses to
        # install without this flag. Safe here because the sandbox is
        # ephemeral — we're not corrupting a long-lived environment.
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-index",
             "--find-links", str(wheels), "--break-system-packages",
             "groundling"],
            check=True,
        )
        print("groundling installed.")

    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()


if __name__ == "__main__":
    main()
