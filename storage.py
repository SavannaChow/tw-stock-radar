# -*- coding: utf-8 -*-
"""Shared paths for files that must survive a container rebuild."""
from __future__ import annotations

import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("RADAR_DATA_DIR", str(HERE))).expanduser().resolve()
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def runtime_path(name: str) -> Path:
    """Return a file path inside the configured persistent runtime directory."""
    return RUNTIME_DIR / name
