#!/usr/bin/python3 -IB
"""Debian entry point, isolated from user site packages and PYTHONPATH."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib" / "asis-swarm"))

from asis.cli import main  # noqa: E402

raise SystemExit(main())
