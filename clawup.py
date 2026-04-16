#!/usr/bin/env python3
"""
clawup — OpenClaw guided setup orchestrator.

Usage:
  python clawup.py [options]
  ./clawup.py [options]

Run with --help to see all options.
"""

import sys
import os

# Allow running from repo root without installing the package
sys.path.insert(0, os.path.dirname(__file__))

from openclaw_setup.cli import cli_main

if __name__ == "__main__":
    sys.exit(cli_main())
