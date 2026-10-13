"""The installed runtime must work without either historical engine checkout."""

import unittest

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
