"""Focused contracts at the maintained-engine boundary, without importing a sibling checkout."""

from dataclasses import dataclass
import json
from pathlib import Path
from types import ModuleType
import sys
import unittest
from unittest.mock import patch

from dazedtl.compatibility.translation import TranslationEngine, ProviderFailure, provider_errors
from dazedtl.translation.compilation import compile_requests


class CompatibilityContracts(unittest.TestCase):
    def test_line_metadata_reaches_both_provider_payloads_without_changing_the_legacy_batch_contract(self):
        package, context_module, skill_module, provider_module = (ModuleType(name) for name in
            ("util", "util.len_translation", "util.skills", "util.translation"))
        note = "Check whether the visitor or guard left."
        source_context = "門に二人がいる。"
        def contexts(_project, batches):
            self.assertEqual(set(batches[0]), {"id", "sources", "speakers", "source_context", "instruction_key"})
            self.assertEqual(batches[0]["speakers"], {"line": None})
            return [{"context": {"system": "Translate into English", "glossary": "Approved names and voice",
                     "sfx_reference": "SFX", "user": json.dumps(batch["sources"], ensure_ascii=False),
                     "preceding_japanese_source_context": batch["source_context"], "request_instructions": "Field guidance"}}
                    for batch in batches]
        context_module.request_contexts = contexts
        skill_module.ctx = lambda *_args, **_kwargs: "Field guidance"
        provider_module.buildClaudeRequest = lambda **kwargs: {"captured": kwargs}
        provider_module.buildOpenAIRequest = lambda **kwargs: {"captured": kwargs}
        modules = {module.__name__: module for module in (package, context_module, skill_module, provider_module)}
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.project = lambda *_args: None
        engine.compiler_fingerprint = lambda: "compiler"
        plan = {"batches": [{"id": "scene", "sources": {"line": "行った。"}, "kinds": {"line": "dialogue"},
                            "speakers": {"line": None}, "qa_notes": {"line": note}, "source_context": source_context,
                            "scene_context": "Two people at the gate", "instruction_key": "dialogue"}]}
        with patch.dict(sys.modules, modules):
            rows, _compiler = compile_requests(engine, "unused", {}, plan, "English")
            row = rows[0]
            self.assertEqual(row["context"]["line_kinds"], {"line": "dialogue"})
            self.assertEqual(row["context"]["qa_notes"], {"line": note})
            for protocol, mode in (("openai", "live"), ("anthropic", "batch")):
                with self.subTest(protocol=protocol):
                    payload = engine.payload(row, {"protocol": protocol, "provider": protocol,
                                                  "mode": mode, "model": "fixture", "endpoint": "https://provider.invalid/v1"})
                    sent = payload["captured"]
                    self.assertEqual(sent["user"], row["context"]["user"])
                    self.assertIn(note, sent["user"])
                    self.assertEqual(sent["history"], source_context)
                    self.assertIn("Approved names and voice", sent["vocab_text"])
                    self.assertIn("Two people at the gate", sent["request_instructions"])

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
