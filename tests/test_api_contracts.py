"""Real API requests and replies must match the contracts the renderer is built from."""

import unittest

from tests.probe import Probe

probe = Probe("api_contracts.py")


class ApiContractTests(unittest.TestCase):
    def test_handlers_and_offline_replies_match_contracts(self):
        # Generated renderer types only help while the backend honors them:
        # catch fields the contracts omit, nulls they forbid, and parameters
        # a handler would reject.
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)
