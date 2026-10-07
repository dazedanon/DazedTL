"""Load real engine modules beside the fake engine packages unit tests build."""

import importlib.util
import sys
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


def engine_package(relative):
    """Imports one engine package under a private name, so its modules keep
    their relative imports without the engine's top-level packages."""
    path = ENGINE / relative
    name = "fixture_" + path.name
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, path / "__init__.py", submodule_search_locations=[str(path)]
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


# Fake engine functions that host layers extend must be real extension points.
EXTENSIONS = engine_module("util/extensions.py")
point = EXTENSIONS.point
