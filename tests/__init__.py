"""Tests import only this checkout's backend, never a user's engine workspace."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
