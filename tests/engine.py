"""Load real engine modules beside the fake engine packages unit tests build."""

import importlib.util
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "backend/dazedtl/engine"


def engine_module(relative):
    """Executes one engine file under a private name; callers install it in sys.modules."""
    path = ENGINE / relative
    spec = importlib.util.spec_from_file_location("fixture_" + path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Fake engine functions that host layers extend must be real extension points.
EXTENSIONS = engine_module("util/extensions.py")
point = EXTENSIONS.point
