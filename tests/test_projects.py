"""Project identity and selection must survive navigation and failed saves."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dazedtl.projects.store import Projects, SCHEMA_VERSION


class ProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.projects = Projects(self.root)

    def game(self, name):
        path = self.root / name
        path.mkdir(exist_ok=True)
        return {"source": str(path), "engine": "MVMZ"}

    def test_reopening_and_switching_preserve_job_ownership(self):
        detected = self.game("first")
        identity = "1" * 32
        original = {
            "version": 1,
            "current_id": identity,
            "screen": "guided",
            "projects": [
                {
                    "id": identity,
                    "name": "first",
                    "source": detected["source"],
                    "engine": "MVMZ",
                    "method": "guided",
                    "backend_id": "saved-job-owner",
                    "phase": "dialogue",
                }
            ],
        }
        self.projects.path.write_text(json.dumps(original))
        original_bytes = self.projects.path.read_bytes()
        self.projects = Projects(self.root)
        self.assertEqual(self.projects.data["screen"], "translation")
        self.assertEqual(
            next((self.root / "backups").iterdir()).read_bytes(), original_bytes
        )
        reopened = self.projects.open(
            {**detected, "source": detected["source"] + "/."}, "len"
        )
        self.assertEqual(reopened["id"], identity)
        self.assertEqual(reopened["method"], "guided")
        self.projects.navigate("translation")
        self.projects.navigate("guided")
        self.projects.navigate("manual")
        self.projects.navigate("settings")
        second = self.projects.open(self.game("second"), "len")
        self.assertNotEqual(second["id"], identity)
        self.projects.select(identity)
        restored = Projects(self.root)
        self.assertEqual(restored.data["version"], SCHEMA_VERSION)
        self.assertEqual(len(restored.data["projects"]), 2)
        self.assertEqual(restored.current["id"], identity)
        self.assertEqual(restored.current["backend_id"], "saved-job-owner")
        self.assertEqual(restored.current["phase"], "dialogue")

    def test_invalid_navigation_cannot_switch_or_modify_projects(self):
        self.projects.open(self.game("first"), "len")
        before = deepcopy(self.projects.data)
        saved = self.projects.path.read_bytes()
        for action in (
            lambda: self.projects.select("missing"),
            lambda: self.projects.navigate("missing"),
        ):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    action()
                self.assertEqual(self.projects.data, before)
                self.assertEqual(self.projects.path.read_bytes(), saved)

    def test_failed_selection_or_creation_keeps_current_project(self):
        first = self.projects.open(self.game("first"), "guided")
        self.projects.open(self.game("second"), "len")
        third = self.game("third")
        for action in (
            lambda: self.projects.select(first["id"]),
            lambda: self.projects.open(third, "guided"),
            lambda: self.projects.navigate("settings"),
        ):
            with self.subTest(action=action):
                before = deepcopy(self.projects.data)
                saved = self.projects.path.read_bytes()
                with patch(
                    "dazedtl.projects.store.write_json", side_effect=OSError("No space")
                ):
                    with self.assertRaises(OSError):
                        action()
                self.assertEqual(self.projects.path.read_bytes(), saved)
                self.assertEqual(self.projects.data, before)
