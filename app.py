"""Compatibility entry point for the former ``uvicorn app:app`` command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "api"))
from smartair.main import app

__all__ = ["app"]
