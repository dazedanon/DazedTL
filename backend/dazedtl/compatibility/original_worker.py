"""Records one game's original files for the [background record](original_record.py).

Its progress goes to standard output as JSON lines; a line on standard input,
or its end when DazedTL exits, stops it between chunks of files.
"""

import json
import sys
import threading
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dazedtl.diagnostics import record_crashes

record_crashes("record_original")
from dazedtl.system import private_stdin

# Git's processes must not inherit the pipe Stop arrives on.
commands = private_stdin()
from dazedtl.compatibility.runtime import activate

activate()
from util.version_update import GitWorkflowError

from dazedtl.compatibility import original_files

stopping = threading.Event()


def listen():
    for _line in commands:
        break
    stopping.set()


def send(**event):
    print(json.dumps(event), flush=True)


threading.Thread(target=listen, daemon=True).start()
try:
    original_files.ensure_found(
        sys.argv[1], lambda message: send(message=message), stopping.is_set
    )
except InterruptedError:
    sys.exit(0)
except (OSError, ValueError, GitWorkflowError) as error:
    send(error=str(error))
    sys.exit(1)
