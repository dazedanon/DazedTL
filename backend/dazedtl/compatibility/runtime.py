"""Locate the engine shipped with DazedTL, independently of cwd and environment."""

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1] / "engine"


def activate():
    if not (ENGINE_ROOT / "modules/rpgmakermvmz.py").is_file():
        raise RuntimeError(
            "DazedTL's bundled engine is missing. Restore the application files."
        )
    source = str(ENGINE_ROOT)
    if source not in sys.path:
        sys.path.insert(0, source)
    from .openrouter_batch import install as install_openrouter

    install_openrouter()
    return ENGINE_ROOT
