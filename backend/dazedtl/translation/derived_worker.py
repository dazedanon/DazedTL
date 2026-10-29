"""Reads values for the [derived store](derived.py) in a process of its own.

Its tasks arrive on standard input as one JSON list; each value it reads
goes to standard output as a JSON line, which the backend saves. DazedTL
stops it when it closes.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dazedtl.diagnostics import record_crashes

record_crashes("derived_reader")
from dazedtl.system import private_stdin

# Git's processes must not inherit the pipe the tasks arrive on.
tasks = json.load(private_stdin())
from dazedtl.translation.derived import run


def emit(section, key, value):
    print(
        json.dumps(
            {"section": section, "key": key, "value": value}, ensure_ascii=False
        ),
        flush=True,
    )


run(tasks, emit)
