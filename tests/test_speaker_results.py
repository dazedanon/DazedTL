"""Paid names must remain inspectable and reusable after declining map work."""

import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.compatibility import speaker_results
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.files import digest

from tests.engine import point


class SpeakerResultTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plan = {
            "mode": "batch",
            "workflow": {"id": "owner"},
            "settings": {"language": "English"},
        }
        write_json(self.root / "plan.json", self.plan)
        self.job = {
            "id": "names",
            "mode": "batch",
            "status": "running",
            "phase": "preparing",
            "plan_hash": digest((self.root / "plan.json").read_bytes()),
        }
        self.glossary = self.root / "game/.dazedtl/glossary.txt"
        write_bytes(self.glossary, b"# Game Characters\n")

    def translator(self, count=2):
        rows = {f"名前{i}": f"Name {i}" for i in range(count)}
        calls = []

        def finalize():
            calls.append(True)
            self.assertEqual(
                speaker_results.read(self.root, self.job)["state"], "running"
            )
            write_bytes(
                self.glossary,
                (
                    "# Game Characters\n"
                    + "".join(
                        f"{source} ({target})\n" for source, target in rows.items()
                    )
                ).encode(),
            )
            return True

        module = SimpleNamespace(
            pendingSpeakerNames=lambda: list(rows),
            finalizeSpeakerParse=point(finalize),
            calls=calls,
            _vocab_speaker_lookup=rows.get,
            _speaker_translation_valid=lambda source, target: (
                rows.get(source) == target
            ),
        )
        return module

    def test_native_save_receipt_survives_batch_decline_and_requires_retained_evidence(
        self,
    ):
        module = self.translator(53)
        speaker_results.install(module, self.root)
        self.assertTrue(module.finalizeSpeakerParse())
        self.assertEqual(len(module.calls), 1)
        self.job.update(status="canceled", phase="canceled")
        self.assertEqual(speaker_results.summary(self.root, self.job)["state"], "saved")
        self.assertEqual(len(speaker_results.summary(self.root, self.job)["rows"]), 3)
        first = speaker_results.page(self.root, self.job)
        second = speaker_results.page(self.root, self.job, first["nextOffset"])
        self.assertEqual(
            (len(first["rows"]), len(second["rows"]), second["nextOffset"]),
            (50, 3, None),
        )
        self.assertEqual(len(speaker_results.reusable([(self.root, self.job)])), 53)
        # Later file work may expand its glossary; the name snapshot stays authoritative.
        write_bytes(self.glossary, b"# Newer run glossary\n")
        self.assertEqual(speaker_results.summary(self.root, self.job)["state"], "saved")
        for offset in (-1, True, 0.5):
            with self.assertRaises(ValueError):
                speaker_results.page(self.root, self.job, offset)
        snapshot = self.root / "log" / speaker_results.GLOSSARY
        snapshot.write_text("changed")
        self.assertEqual(
            speaker_results.read(self.root, self.job)["state"], "unavailable"
        )
        self.assertEqual(speaker_results.reusable([(self.root, self.job)]), [])
        with self.assertRaises(ValueError):
            speaker_results.page(self.root, self.job)

    def test_failure_and_legacy_approval_never_imply_saved_names(self):
        module = self.translator()
        module.finalizeSpeakerParse = point(lambda: False)
        speaker_results.install(module, self.root)
        self.assertFalse(module.finalizeSpeakerParse())
        self.assertEqual(speaker_results.read(self.root, self.job)["state"], "failed")
        (self.root / "log" / speaker_results.RECEIPT).unlink()
        self.job.update(estimate={"speakers": ["名前0"]}, approval={"kind": "speakers"})
        write_bytes(self.glossary, "# Speakers\n名前0 (Name 0)\n".encode())
        self.assertIsNone(speaker_results.read(self.root, self.job))
        self.job.update(approval=None)
        self.assertEqual(speaker_results.read(self.root, self.job)["state"], "running")
        self.job.update(
            status="canceled",
            phase="canceled",
            log=["Speaker translations saved to the game glossary."],
        )
        self.assertEqual(
            speaker_results.read(self.root, self.job)["rows"],
            [{"source": "名前0", "translation": "Name 0"}],
        )
        self.job["plan_hash"] = "changed"
        self.assertEqual(
            speaker_results.read(self.root, self.job)["state"], "unavailable"
        )

    def test_reuse_preserves_curated_aliases_notes_and_is_frozen_before_launch(self):
        text = "# Game Characters\nリーナ / リナ (Lina) - Curated voice and identity.\n\n# Speakers\n門番 (Guard) - Existing note.\n"
        rows = [
            {"source": "リナ", "translation": "Wrong", "runId": "old"},
            {"source": "門番", "translation": "Wrong", "runId": "old"},
            {"source": "回想部屋", "translation": "Recollection Room", "runId": "paid"},
        ]

        def parse(value):
            return [
                ((match[1].strip(), match[2]), line, "# Characters")
                for line in value.splitlines()
                if (match := re.match(r"(.+?)\s+\(([^)]+)\)", line))
            ]

        aliases = lambda value: value.split(" / ")
        keys = lambda value: [value]
        merged, added = speaker_results.merge_missing(text, rows, parse, aliases, keys)
        self.assertEqual(added, rows[-1:])
        self.assertEqual(merged.replace("回想部屋 (Recollection Room)\n", ""), text)
        self.assertEqual(
            speaker_results.merge_missing(merged, rows, parse, aliases, keys),
            (merged, []),
        )
        base = "## Base separator\n# Speakers\n基本 (Base)\n"
        text_with_base = "# Notes\nKeep these notes.\n" + base
        combined, _ = speaker_results.merge_missing(
            text_with_base, rows[-1:], parse, aliases, keys, "## Base separator"
        )
        self.assertTrue(combined.endswith(base))
        self.assertIn(
            "回想部屋 (Recollection Room)", combined.split("## Base separator")[0]
        )
        write_bytes(self.glossary, text.encode())
        self.plan["context_hashes"] = {
            "game/.dazedtl/glossary.txt": digest(text.encode())
        }
        fake = SimpleNamespace(
            parseVocabWithCategories=parse,
            split_vocab_source_aliases=aliases,
            speaker_source_lookup_keys=keys,
        )
        with patch.dict(
            "sys.modules",
            {
                "util.translation": fake,
                "util.vocab": SimpleNamespace(BASE_SEPARATOR="## Base separator"),
            },
        ):
            speaker_results.seed(self.root, self.plan, rows)
        self.assertEqual(self.glossary.read_text(), merged)
        self.assertEqual(
            self.plan["context_hashes"]["game/.dazedtl/glossary.txt"],
            digest(self.glossary.read_bytes()),
        )
        write_json(self.root / "plan.json", self.plan)
        self.job["plan_hash"] = digest((self.root / "plan.json").read_bytes())
        value = speaker_results.read(self.root, self.job)
        self.assertTrue(value["reused"])
        self.assertEqual(value["rows"][0]["translation"], "Recollection Room")
        # A seeded run is not a new paid source; it cannot churn estimate identity.
        self.assertEqual(speaker_results.reusable([(self.root, self.job)]), [])
