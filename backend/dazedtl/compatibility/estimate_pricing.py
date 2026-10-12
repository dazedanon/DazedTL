"""Price a finished local estimate's kept requests with Claude's own token count.

The estimate worker runs without a credential or network, so its Claude input
is the approximate count. This process sets up the same frozen environment,
then opens the network only for Anthropic's free token-count endpoint; it
never sends a translation request.
"""

import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == "__main__":
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
