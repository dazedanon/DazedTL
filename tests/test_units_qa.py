"""Text QA's review of an Assistant-led game on an engine it can't read
itself, from its units and exported translations: findings land as
correction receipts through Assistant-led's own writer."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dazedtl.api.contracts.guided import QaState, TextQaStatus
from dazedtl.api.contracts.validation import _close_contracts
from dazedtl.storage import write_json
from dazedtl.translation import qa_size, units_qa
from dazedtl.translation.operations import execute
from dazedtl.translation.project import WORK, review_focus
from dazedtl.translation.results import Results, exported_translations
from dazedtl.translation.text_qa import (
    LEFT_OUT_STEP,
    REVIEW_OFF,
    UNITS_APPLIED,
    TextQA,
)
from pydantic import TypeAdapter
from util import rpgmaker_qa
from util.qa import fitting
from util.qa.schema import QAResultError

from tests import test_workflow


class UnitsTextQATests(unittest.TestCase):
    """An Assistant-led game on an engine Text QA can't read, a TyranoScript
    one here, gets Text QA's reviewed task from its units, and its findings
    land as correction receipts."""

    prepared = test_workflow.WorkflowTests.prepared

    def setUp(self):
        test_workflow.WorkflowTests.setUp(self)
        (self.game / "tyrano").mkdir()
        self.projects.choose_method(self.identity, "len")
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        self.guided = SimpleNamespace(
            projects=self.projects,
            qa_focus=lambda _id: review_focus(self.project.read()["options"]),
            translation=self.service,
            path=lambda _id, name: self.root / f"guided-{name}.json",
            backend=SimpleNamespace(operations=SimpleNamespace(jobs={}, active="")),
        )
        self.qa = TextQA(self.guided)  # type: ignore[arg-type]

    def translate(self, units, english):
        """Organizes *units*, accepts *english* for every request through the
        helper's own accept, and returns the run."""
        path = WORK + "/work/source-units.json"
        write_json(self.game / path, {"version": 1, "units": units})
        run = self.prepared(self.service.organize(self.identity, path))["run"]["id"]
        for index in range(len(self.service.jobs.store.load(run)[1]["requests"])):
            request = self.service.request(self.identity, run, index)["request"]
            receipt = WORK + f"/work/receipt-{index}.json"
            write_json(
                self.game / receipt,
                {
                    "request_sha256": request["fingerprint"],
                    "translations": {key: english[key] for key in request["sources"]},
                },
            )
            self.service.accept(self.identity, run, request["id"], receipt)
        return run

    def step(self, step, **details):
        """One qa step, running the operation it starts as its worker would."""
        state = self.qa.run(self.identity, step, **details)
        operation = state.get("operation") or {}
        if operation.get("status") == "running":
            job, plan = self.service.jobs.store.load(operation["id"], self.identity)
            result = execute(self.engine, self.profile, job, plan, lambda: False)
            job.update(status="complete", result=result)
            self.service.jobs.store.save(job)
            state = self.qa.run(self.identity, "status")
        _close_contracts()
        TypeAdapter(TextQaStatus).validate_json(json.dumps(state), strict=True)
        return state

    def english(self):
        return {
            row["source_id"]: row["translation"]
            for row in exported_translations(self.game)
        }

    def test_a_game_text_qa_reads_by_its_units_is_reviewed_and_corrected(self):
        # Text QA refused every engine but RPG Maker, so qa --prepare gave
        # this game no reviewed task, only the text-only checks.
        units = [
            {
                "id": "a/1",
                "scene": "a",
                "source": "エルフの森へようこそ。",
                "kind": "dialogue",
                "speaker": "リリ",
            },
            {
                "id": "a/2",
                "scene": "a",
                "source": "宿代は百ゴールドだよ。",
                "kind": "dialogue",
            },
            {
                "id": "b/1",
                "scene": "b",
                "source": "おやすみなさい。",
                "kind": "dialogue",
                "speaker": "リリ",
            },
        ]
        english = {
            "a/1": "Welcome to the Elven Woods.",
            "a/2": "The inn is a hundred gold.",
            "b/1": "Good mornin.",
        }
        run = self.translate(units, english)
        self.assertEqual(
            self.qa.run(self.identity, "status")["next"], "Run qa --prepare."
        )
        state = self.step("prepare")
        self.assertEqual(state["stage"], "screen")
        task = Path(state["task"])
        # Scenes in play order, each line with its speaker, both languages,
        # its unit and its number in the scene.
        bundles = [
            json.loads(Path(row["path"]).read_text(encoding="utf-8"))
            for row in rpgmaker_qa.read_task(task)[2]["screen"]["bundles"]
        ]
        scenes = {
            item["scene_id"]: item["lines"]
            for bundle in bundles
            for item in bundle["items"]
            if item["kind"] == "scene"
        }
        fields = ("unit", "command", "speaker", "source", "translation")
        self.assertEqual(
            [{key: line.get(key) for key in fields} for line in scenes["a"]],
            [
                {
                    "unit": "a/1",
                    "command": 0,
                    "speaker": "リリ",
                    "source": units[0]["source"],
                    "translation": english["a/1"],
                },
                {
                    "unit": "a/2",
                    "command": 1,
                    "speaker": None,
                    "source": units[1]["source"],
                    "translation": english["a/2"],
                },
            ],
        )
        # The reviewers report b/1, deep review corrects it and the editor
        # accepts the correction.
        review(task, {"Good mornin.": "Good night."})
        state = self.step("status")
        self.assertEqual((state["stage"], state["findings"]), ("complete", 1))
        self.assertEqual(state["next"], "Run qa --apply.")
        shown = self.service.state(self.identity)["textQa"]
        self.assertEqual(shown["findings"][0]["correction"], "Good night.")
        # Apply saves it as a correction receipt of the request b/1 is in.
        state = self.step("apply")
        self.assertEqual((state["applied"], state["next"]), (True, UNITS_APPLIED))
        self.assertEqual(self.english()["b/1"], "Good night.")
        _job, plan = self.service.jobs.store.load(run)
        (request,) = [row for row in plan["requests"] if "b/1" in row["sources"]]
        receipt = Results(self.game).get(request)
        self.assertEqual(receipt["translations"]["b/1"], "Good night.")
        self.assertEqual(
            (receipt["provenance"]["correction"], receipt["provenance"]["text_qa"]),
            (True, task.name),
        )
        # Progress reads the task and its applied finding, still current.
        shown = self.service.state(self.identity)["textQa"]
        TypeAdapter(QaState).validate_json(json.dumps(shown), strict=True)
        finding = shown["findings"][0]["id"]
        self.assertEqual(
            (shown["current"], shown["findings"][0]["state"]), (True, "applied")
        )
        # Undo puts the line back as another receipt, and apply again redoes it.
        self.step("undo", findings=[finding])
        self.assertEqual(self.english()["b/1"], "Good mornin.")
        shown = self.service.state(self.identity)["textQa"]
        self.assertEqual(
            (shown["current"], shown["findings"][0]["state"]), (True, "undone")
        )
        self.step("reapply", findings=[finding])
        self.assertEqual(self.english()["b/1"], "Good night.")
        # Once the line changed otherwise, undo refuses and says why.
        value = Results(self.game).get(request)
        write_json(
            self.game / WORK / "work/correction.json",
            {
                "request_sha256": request["fingerprint"],
                "replaces_sha256": value["result_sha256"],
                "translations": {**value["translations"], "b/1": "Sleep well."},
            },
        )
        self.service.accept(
            self.identity, run, request["id"], WORK + "/work/correction.json"
        )
        with self.assertRaisesRegex(ValueError, "changed since QA corrected it"):
            self.qa.run(self.identity, "undo", findings=[finding])
        self.assertEqual(self.english()["b/1"], "Sleep well.")
        self.assertFalse(self.service.state(self.identity)["textQa"]["current"])
        # Organized again, the run keeps every line from the requests that
        # translated them, and a new review's correction goes back through
        # the request it keeps the line from.
        self.prepared(
            self.service.organize(self.identity, WORK + "/work/source-units.json")
        )
        with self.assertRaisesRegex(ValueError, "--since reads earlier text"):
            self.qa.run(self.identity, "prepare", since="1.0")
        task = Path(self.step("prepare")["task"])
        review(task, {"Sleep well.": "Good night."})
        self.assertTrue(self.step("apply")["applied"])
        self.assertEqual(self.english()["b/1"], "Good night.")
        self.assertEqual(
            Results(self.game).get(request)["translations"]["b/1"], "Good night."
        )
        # Starting QA over sets the task aside, so QA reads as not started.
        self.assertEqual(self.qa.start_over(self.identity)["next"], "Run qa --prepare.")
        self.assertNotIn("task", self.service.state(self.identity)["textQa"])
        # The text-only checks still run there, with or without the review,
        # and the usage note counts the units.
        self.assertEqual(self.qa.check(self.identity)["lines"], 3)
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "text_qa": "checks"},
        )
        with self.assertRaises(ValueError) as off:
            self.qa.run(self.identity, "prepare")
        self.assertEqual(str(off.exception), REVIEW_OFF)
        self.assertEqual(self.qa.check(self.identity)["lines"], 3)
        lines = units_qa.lines(self.service.jobs.store, self.identity, self.game)
        self.assertEqual(
            qa_size.of_units(lines)["focuses"]["release"], {"lines": 3, "scenes": 2}
        )

    def test_apply_leaves_out_a_correction_the_receipt_check_refuses(self):
        # A task saved with one correction the receipt check refuses, such
        # as a line collapsed to ".", failed its whole apply, so none of its
        # good corrections reached the game, and apply again was refused
        # before a first apply.
        self.translate(
            [
                {"id": "a/1", "scene": "a", "source": "宿代は百ゴールドだよ。"},
                {"id": "b/1", "scene": "b", "source": "おやすみなさい。"},
            ],
            {"a/1": "The inn is a hundred gold, yeah.", "b/1": "Good mornin."},
        )
        task = Path(self.step("prepare")["task"])
        review(
            task,
            {
                "The inn is a hundred gold, yeah.": "The inn is a hundred gold.",
                "Good mornin.": "Good night.",
            },
        )
        # QA accepted it before it checked corrections by the receipt rule.
        saved = json.loads((task / "findings.json").read_text(encoding="utf-8"))
        (short,) = [
            row
            for row in saved["findings"]
            if row["current"] == "The inn is a hundred gold, yeah."
        ]
        short["correction"] = "."
        write_json(task / "findings.json", saved)
        state = self.step("apply")
        self.assertEqual(
            (state["applied"], state["next"]),
            (True, LEFT_OUT_STEP + " " + UNITS_APPLIED),
        )
        self.assertEqual(
            self.english(),
            {"a/1": "The inn is a hundred gold, yeah.", "b/1": "Good night."},
        )
        (left,) = state["left_out"]
        self.assertEqual(left["id"], short["id"])
        self.assertIn("a/1: Translation unusually short ('.')", left["reason"])
        # The page reads it as left out, with why, and the task as applied.
        shown = self.service.state(self.identity)["textQa"]
        TypeAdapter(QaState).validate_json(json.dumps(shown), strict=True)
        rows = {row["id"]: row for row in shown["findings"]}
        self.assertEqual(rows[short["id"]]["state"], "left-out")
        self.assertIn("unusually short", rows[short["id"]]["reason"])
        (good,) = [key for key, row in rows.items() if row["state"] == "applied"]
        self.assertTrue(shown["applied"] and shown["current"])
        with self.assertRaisesRegex(ValueError, "already applied"):
            self.qa.run(self.identity, "apply")
        # Undo and apply again keep working, and applying the left-out one
        # again leaves it out again rather than failing.
        self.step("undo", findings=[good])
        self.assertEqual(self.english()["b/1"], "Good mornin.")
        self.step("reapply", findings=[good])
        self.assertEqual(self.english()["b/1"], "Good night.")
        state = self.step("reapply", findings=[short["id"]])
        self.assertEqual([row["id"] for row in state["left_out"]], [short["id"]])
        self.assertTrue(state["applied"])
        self.assertEqual(self.english()["a/1"], "The inn is a hundred gold, yeah.")

    def test_qa_refuses_a_correction_the_receipt_check_refuses(self):
        # QA accepted a correction that accept refuses in a receipt, so the
        # task's apply failed on it.
        self.translate(
            [{"id": "b/1", "scene": "b", "source": "おやすみなさい。"}],
            {"b/1": "Good mornin."},
        )
        task = Path(self.step("prepare")["task"])
        refused = (
            r"would block apply: translation unusually short \('\.'\).* "
            "give this line English of its own"
        )
        with self.assertRaisesRegex(QAResultError, refused):
            review(task, {"Good mornin.": "."})
        # Deep review took it before QA checked so; its editor can't accept it.
        with (
            mock.patch.object(fitting, "_content_problems", return_value=[]),
            self.assertRaisesRegex(QAResultError, refused + ".*Revise it"),
        ):
            review(task, {"Good mornin.": "."})

    def test_a_correction_reads_and_undoes_as_the_game_gets_it(self):
        # The export writes a reviewer's curly apostrophe and dash in its own
        # form, so undo read the line as changed and refused, and the tab
        # showed text the game never got.
        self.translate(
            [{"id": "b/1", "scene": "b", "source": "おやすみなさい。"}],
            {"b/1": "Good mornin."},
        )
        task = Path(self.step("prepare")["task"])
        review(task, {"Good mornin.": "It’s late—good night."})
        self.assertTrue(self.step("apply")["applied"])
        written = self.english()["b/1"]
        self.assertNotEqual(written, "It’s late—good night.")
        (finding,) = self.service.state(self.identity)["textQa"]["findings"]
        self.assertEqual(finding["correction"], written)
        # Preparing again goes on with the applied task, whose undo stays.
        self.assertEqual(self.step("prepare")["task"], str(task))
        self.step("undo", findings=[finding["id"]])
        self.assertEqual(self.english()["b/1"], "Good mornin.")


def review(task, fixes):
    """Plays Text QA's reviewers through the engine: screening reports each
    line whose English *fixes* corrects, deep review corrects it, and the
    editor accepts every finding."""

    def accept(row, result):
        path = Path(task).parent / f"{row['id']}.result.json"
        path.write_text(
            json.dumps(
                {"bundle_id": row["id"], "bundle_sha256": row["sha256"], **result},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        rpgmaker_qa.accept_result(task, path)

    def items(row):
        return json.loads(Path(row["path"]).read_text(encoding="utf-8"))["items"]

    clean = {
        "disposition": "clean",
        "severity": None,
        "category": "",
        "family_key": "",
        "motif_ids": [],
        "evidence": "Checked against the source.",
        "correction": None,
        "apply_identities": [],
    }
    for name in ("screen-a", "screen-b", "deep-a", "editor-a"):
        while row := rpgmaker_qa.next_bundle(task, name):
            if row["id"].startswith("screen"):
                exceptions = [
                    {
                        "id": line["id"],
                        "verdict": "suspect",
                        "categories": ["meaning"],
                        "note": "Wrong time of day.",
                    }
                    for item in items(row)
                    for line in item.get("lines") or [item]
                    if "id" in line and line.get("translation") in fixes
                ]
                accept(
                    row,
                    {
                        "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
                        "reviewed_all": True,
                        "exceptions": exceptions,
                        "motif_reviews": [],
                        "lint_reviews": [
                            {"id": item["id"], "rejected": [], "note": ""}
                            for item in items(row)
                            if item["kind"] == "lint-family"
                        ],
                        "declined": [],
                    },
                )
            elif row["id"].startswith("deep"):
                reviews = [
                    {
                        **clean,
                        "id": item["id"],
                        "disposition": "actionable",
                        "severity": "high",
                        "category": "meaning",
                        "summary": "It wishes a good morning at bedtime.",
                        "evidence": "おやすみなさい is good night.",
                        "correction": fixes[item["translation"]],
                    }
                    if item["translation"] in fixes
                    else {**clean, "id": item["id"]}
                    for item in items(row)
                ]
                accept(
                    row, {"schema": rpgmaker_qa.DEEP_RESULT_SCHEMA, "reviews": reviews}
                )
            elif row["id"].startswith("sweep"):
                accept(
                    row,
                    {
                        "schema": rpgmaker_qa.SWEEP_RESULT_SCHEMA,
                        "reviews": [
                            {"id": item["id"], "rejected": [], "note": ""}
                            for item in items(row)
                        ],
                        "declined": [],
                    },
                )
            else:
                accept(
                    row,
                    {
                        "schema": rpgmaker_qa.EDITORIAL_RESULT_SCHEMA,
                        "reviews": [
                            {"id": item["id"], "verdict": "accept", "note": ""}
                            for item in items(row)
                        ],
                    },
                )
