"""Focused contracts at the maintained-engine boundary, without importing a sibling checkout."""

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
import sys
import unittest
from unittest.mock import patch

from dazedtl.compatibility.translation import TranslationEngine, ProviderFailure, provider_errors


class CompatibilityContracts(unittest.TestCase):
    def test_native_update_completion_property_survives_public_serialization(self):
        @dataclass
        class Update:
            translation_commit: str | None
            pending_conflicts: tuple = ()
            @property
            def complete(self):
                return self.translation_commit is not None and not self.pending_conflicts
        package = ModuleType("util")
        module = ModuleType("util.version_update")
        package.version_update = module
        engine = TranslationEngine.__new__(TranslationEngine)
        for result in (Update("saved"), Update(None, ("data/Items.json",))):
            with self.subTest(result=result):
                module.continue_with_official = lambda _source: result
                with patch.dict(sys.modules, {"util": package, "util.version_update": module}):
                    value = engine.version(Path("unused"), "continue", {})
                self.assertEqual(value["complete"], result.complete)
                self.assertEqual(value["pending_conflicts"], result.pending_conflicts)

    def test_provider_errors_do_not_reveal_credentials_or_request_bodies(self):
        @provider_errors
        def request():
            raise ValueError("Invalid Authorization header: Bearer fixture-private-key; private request body")
        with self.assertRaises(ProviderFailure) as raised:
            request()
        self.assertNotIn("fixture-private-key", str(raised.exception))
        self.assertNotIn("private request body", str(raised.exception))
        self.assertIsNone(raised.exception.status_code)
