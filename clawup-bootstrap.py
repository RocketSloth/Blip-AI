#!/usr/bin/env python3
"""
clawup bootstrap — zero-dependency launcher for the browser wizard.

For non-technical users. Run this file with Python and it:
  1. Checks your Python version is recent enough (3.10+)
  2. Checks for required libraries (fastapi, uvicorn)
  3. Installs them via pip if missing (with permission)
  4. Starts the wizard server
  5. Opens your browser to the wizard

Usage:
    python clawup-bootstrap.py

No arguments needed. Everything happens in the browser after this.

This file uses only Python's standard library so it can run on a
fresh machine before any other dependencies are installed.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


MIN_PY = (3, 10)
REQUIRED = ["fastapi", "uvicorn", "pydantic"]


def banner() -> None:
    print()
    print("  ╔════════════════════════════════════════════╗")
    print("  ║   clawup — OpenClaw setup wizard           ║")
    print("  ║   Opening in your browser…                 ║")
    print("  ╚════════════════════════════════════════════╝")
    print()


def check_python() -> None:
    if sys.version_info < MIN_PY:
        sys.stderr.write(
            f"\n  Python {MIN_PY[0]}.{MIN_PY[1]}+ is required. "
            f"You have {sys.version_info.major}.{sys.version_info.minor}.\n"
            f"  Install a newer Python from https://www.python.org/downloads/\n\n"
        )
        sys.exit(1)


def missing_packages() -> list:
    missing = []
    for pkg in REQUIRED:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def install_packages(pkgs: list) -> int:
    print(f"  Installing: {', '.join(pkgs)}")
    print("  (one-time setup — about 30 seconds)")
    print()
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *pkgs]
    result = subprocess.run(cmd)
    return result.returncode


def ensure_deps() -> None:
    missing = missing_packages()
    if not missing:
        return

    print(f"  First-time setup: we need to install {len(missing)} Python package(s).")
    try:
        reply = input("  Install now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        sys.exit(1)

    if reply not in ("", "y", "yes"):
        print("  Cancelled. You can install manually with:")
        print(f"    pip install {' '.join(missing)}")
        sys.exit(1)

    code = install_packages(missing)
    if code != 0:
        sys.stderr.write("\n  pip install failed.\n")
        sys.stderr.write("  Try running this manually:\n")
        sys.stderr.write(f"    {sys.executable} -m pip install {' '.join(missing)}\n\n")
        sys.exit(code)


def ensure_on_path() -> None:
    """Make sure this repo's root is on sys.path so openclaw_setup imports."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))


def launch() -> int:
    ensure_on_path()
    from openclaw_setup.web.server import serve
    return serve(port=7999, open_browser=True)


def main() -> int:
    banner()
    check_python()
    ensure_deps()
    try:
        return launch()
    except KeyboardInterrupt:
        print("\n  Shutting down.\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
