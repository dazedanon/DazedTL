"""Price a finished local estimate's kept requests with Claude's own token count.

The estimate worker runs without a credential or network, so its Claude input
is the approximate count. ``count`` runs this module as its own process, which
sets up the same frozen environment, then opens the network only for
Anthropic's free token-count endpoint; it never sends a translation request.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Above the longest a count can retry (eight requests at a time, each waiting
# up to 30 seconds three times), so only a hung process ends here.
TIMEOUT = 600


def count(directory, workspace, plan, estimate, stopped=lambda: False):
    """``estimate`` priced with Claude's own count. A count that can't run or
    fails keeps it approximate, which it says; stopping ends the count with
    InterruptedError."""
    from desktop.backend.manual import worker_environment
    from desktop.backend.settings import SettingsStore

    directory = Path(directory)
    if (
        estimate.get("provider") != "anthropic"
        or not estimate.get("approximate_input")
        or not plan.get("key_name")
        or os.getenv("DAZEDTL_TEST_OFFLINE") == "1"
        or not (directory / "log/estimate_requests.json").is_file()
    ):
        return estimate
    try:
        runtime = SettingsStore(workspace).runtime(plan["settings"], plan["key_name"])
    except OSError, ValueError, KeyError:
        return estimate
    # A credential edited to another endpoint since the estimate is not
    # Anthropic's to receive.
    if not runtime["key"] or runtime.get("api") != plan["settings"].get("api"):
        return estimate
    with (directory / "log/startup.txt").open("a", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).resolve()), str(directory)],
            cwd=directory,
            env={**worker_environment(workspace, plan), "PYTHONDONTWRITEBYTECODE": "1"},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
        )
    with process:
        try:
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(runtime["key"] + "\n")
            process.stdin.close()
            deadline = time.monotonic() + TIMEOUT
            while True:
                if stopped():
                    raise InterruptedError("Stopped while counting Claude tokens.")
                try:
                    process.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() > deadline:
                        return estimate
            # The process writes one short line, so its pipe never fills.
            counted = json.loads(process.stdout.read().strip().splitlines()[-1])
        except InterruptedError:
            raise
        except OSError, ValueError, IndexError:
            return estimate
        finally:
            if process.poll() is None:
                process.kill()
    return {**estimate, **counted} if isinstance(counted, dict) else estimate


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    protocol = sys.stdout
    # The engine prints its estimate as it prices; only the result goes out.
    sys.stdout = sys.stderr
    secret = sys.stdin.readline().strip()
    from dazedtl.compatibility.runtime import activate

    activate()
    from dazedtl.compatibility.worker_policy import install

    install()
    from desktop.backend.manual_environment import prepare

    network = (
        socket.create_connection,
        socket.socket.connect,
        socket.socket.connect_ex,
    )
    prepare(sys.argv[1])
    socket.create_connection, socket.socket.connect, socket.socket.connect_ex = network
    os.environ.pop("DAZEDTL_TEST_OFFLINE", None)
    os.environ["key"] = secret
    from util.translation import estimateTranslationCosts

    estimate = estimateTranslationCosts()
    protocol.write(json.dumps(estimate) + "\n")
    protocol.flush()
