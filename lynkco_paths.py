#!/usr/bin/env python3
"""Shared paths for source runs and packaged desktop builds."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


APP_DIR_NAME = "lynkco-daily"
SCRIPT_ROOT = Path(__file__).resolve().parent
IS_FROZEN = bool(getattr(sys, "frozen", False))


def _default_app_root() -> Path:
    system = platform.system().lower()
    if system == "windows":
        base = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif system == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / APP_DIR_NAME


def app_root() -> Path:
    override = os.getenv("LYNKCO_APP_ROOT", "").strip()
    if override:
        root = Path(override).expanduser().resolve()
    elif IS_FROZEN:
        root = _default_app_root()
    else:
        root = SCRIPT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", SCRIPT_ROOT))
    return base / relative_path


APP_ROOT = app_root()
