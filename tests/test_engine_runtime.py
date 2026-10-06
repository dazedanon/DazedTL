"""The installed runtime must work without either historical engine checkout."""

import unittest

from tests.probe import Probe

# The probe spends most of its time starting three interpreters, so it starts
# when discovery imports this module and runs alongside the other tests.
probe = Probe("engine_runtime.py")


class EngineRuntimeTests(unittest.TestCase):
    def test_offline_startup_and_parser_ignore_external_engine_paths(self):
        # Existing unit fixtures replace engine APIs. This one small real parser
        # journey catches missing imports/assets and child-launch regressions.
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)
