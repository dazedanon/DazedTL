"""The installed runtime must work without either historical engine checkout."""

import os
import sys
import unittest
from pathlib import Path

from dazedtl import system

from tests.probe import Probe

# Each probe spends most of its time starting interpreters, so it starts when
# discovery imports this module and runs alongside the other tests.
probe = Probe("engine_runtime.py")
claude = Probe("claude_estimate.py")


class EngineRuntimeTests(unittest.TestCase):
    def test_offline_startup_and_parser_ignore_external_engine_paths(self):
        # Existing unit fixtures replace engine APIs. This one small real parser
        # journey catches missing imports/assets and child-launch regressions.
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)

    def test_claude_estimate_counts_claudes_tokens_before_it_completes(self):
        # The estimate worker has no key or network, so a Live review showed
        # its approximate Claude count, about 10% low. The run must count again
        # with its saved key, at the count endpoint only, before it completes.
        returncode, output = claude.result()
        self.assertEqual(returncode, 0, output)

    @unittest.skipIf(os.name == "nt", "Windows has no resource tracker")
    def test_a_workers_first_progress_bar_starts_no_other_python(self):
        # tqdm's default lock started multiprocessing's resource tracker, one
        # more interpreter, in every translation worker that opened a bar.
        script = f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / "backend")!r})
from dazedtl.compatibility.runtime import activate
activate()
from multiprocessing import resource_tracker
from tqdm import tqdm
with tqdm(total=1, file=sys.stderr) as bar:
    bar.update()
print(resource_tracker._resource_tracker._pid)
"""
        result = system.run(
            [sys.executable, "-I", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.stdout.strip(), "None", result.stderr)
