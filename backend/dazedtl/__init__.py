"""DazedTL's backend. Its modules import the bundled engine's packages, such
as ``util``, at module level, so importing the package makes them importable
by the one rule that locates the engine."""

from dazedtl.compatibility.runtime import importable

importable()
