"""Locations of repo-level folders (prompts/, knowledge/). Override with env vars."""

from __future__ import annotations

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def prompts_dir() -> Path:
    return Path(os.environ.get("UNCLOG_PROMPTS_DIR", _REPO / "prompts"))


def knowledge_dir() -> Path:
    return Path(os.environ.get("UNCLOG_KNOWLEDGE_DIR", _REPO / "knowledge"))
