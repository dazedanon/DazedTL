"""How a worker reports an action's failure that it ends with as its finished event."""
from __future__ import annotations

import traceback

from util import extensions


@extensions.point
def reported(error):
    """Writes the failure's traceback to the worker's standard error, its log;
    a host may also record where it happened."""
    traceback.print_exception(error)
