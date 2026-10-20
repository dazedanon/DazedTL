"""Whether saved work is still current.

The rule is defined once, in the bundled engine's ``util/freshness.py``, so
run workers and engine scripts follow it without importing the app; this
module only makes it importable from the app.
"""

import sys

from dazedtl.compatibility.runtime import ENGINE_ROOT

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from util.freshness import (
    SETTLED_NS,
    Basis,
    Change,
    Digests,
    compare,
    settled,
    signature,
    signature_settled,
)

__all__ = [
    "SETTLED_NS",
    "Basis",
    "Change",
    "Digests",
    "compare",
    "settled",
    "signature",
    "signature_settled",
]
