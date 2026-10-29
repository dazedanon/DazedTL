"""Locate the engine shipped with DazedTL, independently of cwd and environment."""

import sys
import threading
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
    # tqdm guards its bars with a multiprocessing lock by default, whose first
    # bar starts multiprocessing's resource tracker, another Python, on Linux
    # and macOS. Engine bars are shared only by threads of one process.
    from tqdm import tqdm

    tqdm.set_lock(threading.RLock())
    return ENGINE_ROOT
