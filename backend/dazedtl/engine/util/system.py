"""DazedTL's platform layer for engine code: see backend/dazedtl/system.py.

The engine runs only inside DazedTL, whose backend folder holds it; engine
processes start with only the engine folder importable.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[3])
if _BACKEND not in sys.path:
    sys.path.append(_BACKEND)

from dazedtl.system import *  # noqa: E402, F403
from dazedtl.system import __all__  # noqa: E402, F401
