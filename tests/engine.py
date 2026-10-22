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


_MISSING = object()


class replaced_modules:
    """Puts `modules` in sys.modules in place of the ones of those names, for
    a `with` block or from start() to stop(), as patch.dict(sys.modules, ...)
    does. Afterwards every module is as before: one first imported meanwhile
    may hold a stand-in, so it leaves its parent package as well as
    sys.modules and imports afresh when next needed. patch.dict left the
    package naming it, so a later test that imported it saw two copies."""

    def __init__(self, modules):
        self.modules = modules

    def start(self):
        self.before = dict(sys.modules)
        # What each replaced module's parent package named it, if anything.
        self.named = {}
        for name in self.modules:
            parent, _, child = name.rpartition(".")
            if parent in sys.modules:
                self.named[name] = vars(sys.modules[parent]).get(child, _MISSING)
        sys.modules.update(self.modules)
        return self

    def stop(self):
        for name in (set(sys.modules) - set(self.before)) | set(self.modules):
            parent_name, _, child = name.rpartition(".")
            parent = self.before.get(parent_name)
            if parent is None:
                continue
            named = self.named.get(name, _MISSING)
            current = vars(parent).get(child, _MISSING)
            if named is not _MISSING:
                setattr(parent, child, named)
            elif current is not _MISSING and (
                current is sys.modules.get(name) or current is self.modules.get(name)
            ):
                delattr(parent, child)
        sys.modules.clear()
        sys.modules.update(self.before)

    def __enter__(self):
        return self.start()

    def __exit__(self, *_error):
        self.stop()


# Fake engine functions that host layers extend must be real extension points.
EXTENSIONS = engine_module("util/extensions.py")
point = EXTENSIONS.point
