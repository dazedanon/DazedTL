"""Compare models (translation/compare.py, compatibility/compare.py): the
lines a comparison sends and shows, and its paid approval."""

import json
import threading
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.actions import stopped_note
from dazedtl.api import views
from dazedtl.compatibility import compare as compare_run
from dazedtl.compatibility import compare_units
from dazedtl.compatibility.compare import END, cut, glossary_text, rows, sources
from dazedtl.compatibility.compare_units import stage
from dazedtl.storage import write_json
from dazedtl.translation.compare import Compare, Game, view
from dazedtl.translation.project import MANUAL_UNITS
from desktop.backend.guidance import documents_save, read
from desktop.backend.workflow_worker import outcome
from util.paths import GLOSSARY_BASE_SEPARATOR


def command(code, parameters, **extra):
    return {"code": code, "indent": 0, "parameters": parameters, **extra}


def page(*commands):
    return {"pages": [{"list": [*commands, command(0, [])]}]}


class LinesTests(unittest.TestCase):
    def test_the_cut_keeps_whole_pages_and_translations_pair_by_their_source(self):
        # The engine joins a message's rows into one command, so a line's
        # place in the translated file moves; a model's line once landed
        # beside another line, or nowhere.
        original = {
            "displayName": "はじまりの村",
            "events": [
                None,
                page(
                    command(101, ["", 0, 0, 2, "村長"]),
                    command(401, ["おお、ミカよ。"]),
                    command(401, ["森の奥に杖が眠っている。"]),
                    command(101, ["", 0, 0, 2, "ミカ"]),
                    command(401, ["行ってきます！"]),
                ),
                page(
                    command(101, ["", 0, 0, 2, "少年"]),
                    command(401, ["また魔法の練習？"]),
                ),
            ],
        }
        value, kept = cut("Map001.json", original, "dialogue", 2)
        assert isinstance(value, dict)
        # The second line's page stays whole; the next page ends at once.
        self.assertEqual(value["events"][2]["pages"][0]["list"], [END])
        self.assertEqual(len(original["events"][2]["pages"][0]["list"]), 3)
        shown = sources(kept)
        self.assertEqual(
            [(row["speaker"], row["source"]) for row in shown],
            [
                ("村長", "おお、ミカよ。\n森の奥に杖が眠っている。"),
                ("ミカ", "行ってきます！"),
                ("", "はじまりの村"),
            ],
        )
        translated = {
            "displayName": "Starting Village",
            "events": [
                None,
                page(
                    command(101, ["", 0, 0, 2, "Village Chief"], _original="村長"),
                    command(
                        401,
                        ["Ah, Mika.\nA staff sleeps deep in the woods."],
                        _original="おお、ミカよ。\n森の奥に杖が眠っている。",
                    ),
                    command(101, ["", 0, 0, 2, "Mika"], _original="ミカ"),
                    command(401, ["I'm off!"], _original="行ってきます！"),
                ),
                value["events"][2],
            ],
        }
        found = rows("Map001.json", translated, "dialogue", kept)
        self.assertEqual(
            [found.get(row["id"]) for row in shown],
            [
                {
                    "speaker": "Village Chief",
                    "text": "Ah, Mika.\nA staff sleeps deep in the woods.",
                },
                {"speaker": "Mika", "text": "I'm off!"},
                {"speaker": "", "text": "Starting Village"},
            ],
        )

    def test_a_database_cut_keeps_the_entries_before_the_last_line(self):
        items = [None, {"name": "薬", "description": "体力を回復する"}, {"name": "剣"}]
        value, kept = cut("Items.json", items, "database", 2)
        self.assertEqual(value[2], None)
        self.assertEqual(len(kept), 2)


class GlossaryTests(unittest.TestCase):
    def test_a_test_glossary_replaces_a_legacy_one_and_keeps_the_base_once(self):
        # Tune starts from the glossary the Context editor shows; sending the
        # whole file back appended the shipped base a second time, and a
        # legacy root glossary.txt moved back over the test's.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            (game / "glossary.txt").write_text(
                "村長 (Village Chief)\n\n" + GLOSSARY_BASE_SEPARATOR + "魔法 (Magic)\n",
                encoding="utf-8",
            )
            staged = stage(
                game, root / "staged", {"glossary": "村長 (Village Chief)\nミカ (Mika)"}
            )
            self.assertFalse((staged / "glossary.txt").exists())
            text = (staged / ".dazedtl/glossary.txt").read_text(encoding="utf-8")
            self.assertEqual(text.count(GLOSSARY_BASE_SEPARATOR), 1)
            self.assertEqual(
                text.split(GLOSSARY_BASE_SEPARATOR)[0].rstrip(),
                "村長 (Village Chief)\nミカ (Mika)",
            )


class RunTests(unittest.TestCase):
    def test_a_guided_comparison_reads_the_original_from_the_games_records(self):
        # The engine's folder was passed as the workspace, so a game whose
        # original is kept only as an older backup record never compared.
        with TemporaryDirectory() as temporary:
            app = Path(temporary)
            folder = app / "engine/projects/n1"
            folder.mkdir(parents=True)
            plan = {
                "action": compare_run.TRANSLATE,
                "folder": str(folder),
                "project": {"source": str(app / "game")},
                "options": {
                    "method": "guided",
                    "workspace": str(app / "workspace"),
                    "projectId": "p1",
                    "file": "Map001.json",
                    "phase": "dialogue",
                    "relative": "data/Map001.json",
                    "lines": 0,
                    "candidates": [],
                },
            }
            log = Mock(stopped=lambda: False)
            with (
                patch("desktop.backend.workflow_actions.validate_plan"),
                patch.object(
                    compare_run, "stage", side_effect=ValueError("staged")
                ) as staged,
                self.assertRaisesRegex(ValueError, "staged"),
            ):
                compare_run.run(plan, log)
            self.assertEqual(staged.call_args.args[1:3], (app / "workspace", "p1"))


class StopTests(unittest.TestCase):
    def guided_plan(self, folder, models):
        return {
            "action": compare_run.TRANSLATE,
            "folder": str(folder),
            "project": {"source": str(folder / "game")},
            "options": {
                "method": "guided",
                "workspace": str(folder),
                "projectId": "p1",
                "file": "Map001.json",
                "phase": "dialogue",
                "relative": "data/Map001.json",
                "lines": 0,
                "workflow": {},
                "pair": {},
                "candidates": [
                    {"index": index, "label": model, "model": model, "policy": {}}
                    for index, model in enumerate(models)
                ],
            },
        }

    def test_a_stopped_translation_keeps_what_each_model_finished_and_spent(self):
        # A stop dropped every model's lines and the cost of what was sent,
        # while translating again was refused.
        stopped = threading.Event()

        def translate(directory, _env, label, log, index):
            if label == "b":
                stopped.set()
                raise InterruptedError("stop")

        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            log = Mock(stopped=stopped.is_set)
            finished = {"lines": {"/1": {"speaker": "", "text": "Hi"}}, "cost": 0.5}
            with (
                patch("desktop.backend.workflow_actions.validate_plan"),
                patch("desktop.backend.manual.worker_environment"),
                patch.object(compare_run, "stage", return_value=({}, [])),
                patch.object(compare_run, "stage_run", return_value=(None, {})),
                patch.object(compare_run, "engine_configuration"),
                patch.object(compare_run, "translate", side_effect=translate),
                patch.object(compare_run, "result", return_value=finished),
                patch.object(compare_run, "_spent", return_value={"cost": 0.2}),
            ):
                value = compare_run.run(self.guided_plan(folder, ["a", "b"]), log)
        self.assertTrue(value["stopped"])
        self.assertEqual(value["message"], stopped_note(compare_run.TRANSLATE))
        self.assertEqual(value["models"][0], {"index": 0, **finished})
        self.assertEqual(
            value["models"][1],
            {"index": 1, "error": compare_run.STOPPED, "cost": 0.2},
        )
        self.assertEqual(outcome(value), "stopped")
        # The page shows the stopped model's cost beside its error.
        options = {"kind": "versus", "file": "", "lines": 0, "candidates": []}
        options["candidates"] = [
            {"index": index, "connection": "C", "connection_id": "c1", "model": model}
            for index, model in enumerate(["a", "b"])
        ]
        shown = view(
            {"id": "e", "created": "1", "status": "complete", "result": {}},
            options,
            {"id": "t", "status": "stopped", "result": value},
            {},
        )
        self.assertEqual(shown["candidates"][1]["cost"], 0.2)

    def test_a_model_that_fails_sending_keeps_what_it_spent(self):
        # An Assistant-led model that failed after sending showed no cost.
        identities = [f"r{index}" for index in range(25)]
        record = {
            "usage": {"input_tokens": 10},
            "request_usage": {},
            "states": {identity: {"state": "pending"} for identity in identities},
        }
        store = Mock(
            create=Mock(return_value={"id": "j1"}), record=Mock(return_value=record)
        )

        class Runner:
            def __init__(self, *_args):
                pass

            def step(self, recover):
                raise RuntimeError("connection lost")

            def response_path(self, identity):
                return Path("/missing") / identity

        requests = [
            {"id": identity, "sources": [], "params": {}} for identity in identities
        ]
        options = {
            "selected": {},
            "inputPath": "units.json",
            "quotes": True,
            "projectId": "p1",
        }
        with (
            patch.object(compare_units, "run_store", return_value=store),
            patch("dazedtl.translation.runner.Runner", Runner),
            patch("dazedtl.translation.results.Results"),
            patch("dazedtl.settings.execution.worker_secret"),
            patch("dazedtl.translation.repricing.route_of"),
            patch("dazedtl.compatibility.translation.TranslationProvider"),
            patch("dazedtl.compatibility.estimate_prices.usage_cost", return_value=0.3),
        ):
            value = compare_units.translate(
                None,
                Path("/workspace"),
                options,
                {"configuration": {}},
                requests,
                {},
                Path("/game"),
                Path("/runs"),
                lambda: False,
            )
        self.assertEqual((value["error"], value["cost"]), ("RuntimeError", 0.3))
        # It keeps the first requests for Show request, as a Guided model's
        # result does, and says how many it holds.
        self.assertEqual(len(value["requests"]), compare_run.KEPT_REQUESTS)
        options = {
            "kind": "single",
            "file": "",
            "lines": 0,
            "candidates": [
                {"index": 0, "connection": "C", "connection_id": "c1", "model": "a"}
            ],
        }
        shown = view(
            {"id": "e", "created": "1", "status": "complete", "result": {}},
            options,
            {
                "id": "t",
                "status": "complete",
                "result": {"models": [{"index": 0, **value}]},
            },
            {},
        )["candidates"][0]
        self.assertEqual((shown["requests"], shown["keptRequests"]), (25, 20))


class ViewTests(unittest.TestCase):
    def test_a_running_translation_shows_the_lines_its_estimate_read(self):
        # A translation has no result until it ends, so its page showed no
        # lines while the models worked.
        options = {
            "kind": "single",
            "file": "Map001",
            "lines": 0,
            "candidates": [
                {"index": 0, "connection": "C", "connection_id": "c1", "model": "a"}
            ],
        }
        line = {"id": "/1", "speaker": "", "source": "村長、ようこそ。"}
        estimate = {
            "id": "e",
            "created": "1",
            "status": "complete",
            "result": {"lines": [line], "models": []},
        }
        running = {"id": "t", "status": "running", "result": None}
        shown = view(estimate, options, running, {})
        self.assertEqual(
            shown["rows"], [{**line, "translations": [None], "problems": [[]]}]
        )

    def test_a_failed_models_error_reads_as_written_and_only_a_finished_model_is_usable(
        self,
    ):
        # Hiding names by replacing them in errors garbled other models' names,
        # and a model that failed or was stopped was offered for use.
        options = {
            "kind": "versus",
            "file": "Map001",
            "lines": 0,
            "candidates": [
                {
                    "index": index,
                    "connection": "C",
                    "connection_id": "c1",
                    "model": name,
                }
                for index, name in enumerate(("gpt-4o", "gpt-4o-mini", "c"))
            ],
        }
        estimate = {"id": "e", "created": "1", "status": "complete", "result": {}}
        error = "Model gpt-4o-mini-2024 not found"
        translated = {
            "id": "t",
            "status": "stopped",
            "result": {
                "lines": [],
                "models": [
                    {"index": 0, "cost": 0.01},
                    {"index": 1, "cost": 0.002, "error": error},
                    {"index": 2, "cost": 0.001, "error": "Stopped before it finished."},
                ],
            },
        }
        shown = view(estimate, options, translated, {})
        self.assertEqual(shown["candidates"][1]["error"], error)
        self.assertEqual(
            [model.get("finished", False) for model in shown["candidates"]],
            [True, False, False],
        )
        running = {**translated, "status": "running"}
        self.assertNotIn(
            "finished", view(estimate, options, running, {})["candidates"][0]
        )


class SnapshotTests(unittest.TestCase):
    def test_snapshots_carry_comparisons_without_their_results(self):
        # Every snapshot sent the lines and requests of up to 40 comparisons,
        # and a Guided game's History sent them again.
        job = {
            "id": "t",
            "action": compare_run.TRANSLATE,
            "label": "Compare models",
            "status": "running",
            "message": "a · translating",
            "stopping": True,
            "log": ["a · translating"],
            "result": {"models": [{"index": 0, "requests": [{"exact": "x" * 9}]}]},
        }
        self.assertEqual(
            views.compare_operation(job),
            {
                "id": "t",
                "action": compare_run.TRANSLATE,
                "label": "Compare models",
                "status": "running",
                "message": "a · translating",
                "stopping": True,
            },
        )
        self.assertNotIn("result", views.operation(job))
        self.assertIn("result", views.operation({**job, "action": "apply"}))


class Operations:
    """The app's operation runner, recording the plans it starts."""

    def __init__(self, root):
        self.root = root
        self.jobs = {}

    def start(self, plan):
        identity = uuid.uuid4().hex
        write_json(self.root / identity / "plan.json", plan)
        self.jobs[identity] = {
            "id": identity,
            "action": plan["action"],
            "project_id": plan["project_id"],
            "status": "running",
            "created": str(len(self.jobs)),
            "message": "",
        }
        return self.jobs[identity]


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.game = root / "game"
        self.write_units("村長、ようこそ。")
        connection = {"id": "c1", "name": "Stand-in"}
        self.operations = Operations(root / "operations")
        self.compare = Compare(
            SimpleNamespace(
                idle=lambda **_: None,
                projects=SimpleNamespace(
                    get=lambda _id: {
                        "id": "p1",
                        "method": "manual",
                        "source": str(self.game),
                    }
                ),
                # Saves guidance as both methods' own saves end, without Git.
                save_guidance=lambda native, changes: documents_save(
                    native["source"], changes
                ),
                translation=SimpleNamespace(
                    workspace=root / "workspace",
                    engine=SimpleNamespace(documents_save=documents_save),
                    api_configuration=lambda mode, _root, choice: (
                        {"mode": mode, "model": choice.model, "rates": {}},
                        None,
                    ),
                    project=lambda _id: (
                        {},
                        SimpleNamespace(read=lambda: {"options": {"mode": "agent"}}),
                    ),
                ),
                settings=SimpleNamespace(
                    describe=lambda: {
                        "draft": None,
                        "activeConnectionId": "c1",
                        "revision": 1,
                        "modelOptions": {},
                        "values": {"language": "English", "model": "old"},
                    },
                    use_model=Mock(),
                    _read=dict,
                    _connection=lambda _state, _id: connection,
                    _configured=lambda _connection: True,
                    convert_quotes=lambda: True,
                    source_language=lambda: "Japanese",
                    language=lambda: "English",
                ),
                backend=SimpleNamespace(
                    manual=SimpleNamespace(allow_providers=False),
                    operations=self.operations,
                ),
            )
        )

    def write_units(self, source):
        write_json(
            self.game / MANUAL_UNITS,
            {
                "version": 1,
                "units": [
                    {"id": "u1", "scene": "s1", "group": "Map001", "source": source}
                ],
            },
        )

    def tuned(self, **change):
        """A finished Tune test of model "a" with *change*, a glossary edited
        from the game's as Tune read it."""
        if "glossary" in change:
            change.setdefault(
                "glossary_revision", read(self.game)["glossary"]["revision"]
            )
        job = self.compare.estimate(
            "p1", "tune", "Map001", 0, [{"connection_id": "c1", "model": "a", **change}]
        )
        job.update(
            status="complete",
            result={"models": [{"index": 0, "estimate": {"live_cost": 0.01}}]},
        )
        return self.finished(job["id"])

    def finished(self, estimate):
        """*estimate*, its model's translation of every line finished."""
        job = self.operations.start({"action": "compare_translate", "project_id": "p1"})
        job.update(status="complete", result={"models": [{"index": 0, "cost": 0.01}]})
        record = self.compare._read("p1")
        record["used"][estimate] = job["id"]
        self.compare._write("p1", record)
        return estimate

    def as_guided(self, estimate):
        """The same test, filed under the game's Guided record."""
        plan = json.loads(
            (self.operations.root / estimate / "plan.json").read_text(encoding="utf-8")
        )
        native = {"id": "n1", "source": str(self.game)}
        self.compare.game = lambda _id: Game(
            "guided", "p1", "n1", str(self.game), native
        )
        return self.finished(self.operations.start({**plan, "project_id": "n1"})["id"])

    def estimated(self):
        job = self.compare.estimate(
            "p1",
            "versus",
            "Map001",
            0,
            [
                {"connection_id": "c1", "model": "a"},
                {"connection_id": "c1", "model": "b"},
            ],
        )
        job.update(
            status="complete",
            result={"models": [{"index": 0, "estimate": {"live_cost": 0.01}}]},
        )
        return job["id"]

    def test_a_price_is_approved_once_and_only_while_its_lines_are_the_same(self):
        estimate = self.estimated()
        started = self.compare.translate("p1", estimate)
        plan = json.loads(
            (self.operations.root / started["id"] / "plan.json").read_text(
                encoding="utf-8"
            )
        )
        # Only the model the estimate priced is sent.
        self.assertEqual([row["model"] for row in plan["options"]["candidates"]], ["a"])
        # A second click, or a retry, sends nothing again.
        with self.assertRaisesRegex(ValueError, "already translated"):
            self.compare.translate("p1", estimate)
        estimate = self.estimated()
        self.write_units("村長、よく来たな。")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.compare.translate("p1", estimate)
        self.assertEqual(
            sum(
                job["action"] == "compare_translate"
                for job in self.operations.jobs.values()
            ),
            1,
        )

    def test_a_model_is_used_only_while_no_translation_runs(self):
        # Use this model switched Settings' model under a running
        # translation, which Settings' own saves refuse.
        estimate = self.estimated()

        def busy(**_):
            raise ValueError("Finish or stop the current run first.")

        self.compare.guided.idle = busy
        self.compare.guided.settings.describe = Mock(
            side_effect=AssertionError("Settings changed under a run.")
        )
        with self.assertRaisesRegex(ValueError, "Finish or stop"):
            self.compare.use("p1", estimate, 0)

    def test_tune_starts_from_a_legacy_or_utf16_glossary_as_context_shows_it(self):
        # Tune read only .dazedtl/glossary.txt as UTF-8, so these games showed
        # an empty glossary, which Use these settings then saved over theirs.
        held = "村長 (Village Chief)\n\n" + GLOSSARY_BASE_SEPARATOR + "魔法 (Magic)\n"
        (self.game / "glossary.txt").write_text(held, encoding="utf-8")
        self.assertEqual(self.compare.state("p1")["glossary"], "村長 (Village Chief)")
        (self.game / "glossary.txt").unlink()
        (self.game / ".dazedtl/glossary.txt").write_bytes(held.encode("utf-16"))
        self.assertEqual(self.compare.state("p1")["glossary"], "村長 (Village Chief)")
        # A model's checks read its glossary hints from the same file.
        self.assertEqual(glossary_text(self.game), held)

    def test_use_these_settings_saves_the_tested_guidance_on_both_methods(self):
        # On a Guided game Use these settings switched the model, then failed
        # reading the guidance, which it never saved.
        for guided in (False, True):
            with self.subTest(guided=guided):
                documents_save(
                    self.game,
                    {
                        name: {"revision": document["revision"], "text": ""}
                        for name, document in read(self.game).items()
                        if name in {"glossary", "game"}
                    },
                )
                estimate = self.tuned(
                    glossary="ミカ (Mika)", instruction="Use British spelling."
                )
                if guided:
                    estimate = self.as_guided(estimate)
                self.compare.use("p1", estimate, 0)
                documents = read(self.game)
                self.assertEqual(documents["glossary"]["text"], "ミカ (Mika)")
                self.assertEqual(documents["game"]["text"], "Use British spelling.\n")
                switch = self.compare.guided.settings.use_model
                self.assertEqual(switch.call_args.args[1:3], ("c1", "a"))
                self.assertEqual(
                    [call.kwargs for call in switch.call_args_list[-2:]],
                    [{"check": True}, {}],
                )

    def test_use_these_settings_refuses_guidance_edited_since_the_test(self):
        # It saved the glossary the test froze over an edit made in Context
        # after the test ran.
        for guided in (False, True):
            with self.subTest(guided=guided):
                estimate = self.tuned(glossary="ミカ (Mika)")
                if guided:
                    estimate = self.as_guided(estimate)
                glossary = read(self.game)["glossary"]
                edited = f"村長 (Elder {guided})"
                documents_save(
                    self.game,
                    {"glossary": {"revision": glossary["revision"], "text": edited}},
                )
                self.compare.guided.settings.use_model.reset_mock()
                with self.assertRaisesRegex(ValueError, "changed since this test"):
                    self.compare.use("p1", estimate, 0)
                self.assertEqual(read(self.game)["glossary"]["text"], edited)
                self.compare.guided.settings.use_model.assert_not_called()

    def test_a_test_glossary_edited_before_a_context_save_is_refused(self):
        # Tune's glossary began from the text the page read; a save in
        # Context before the estimate froze the new revision, so Use wrote
        # the old text's edit over it.
        base = read(self.game)["glossary"]["revision"]
        documents_save(
            self.game, {"glossary": {"revision": base, "text": "村長 (Elder)"}}
        )
        with self.assertRaisesRegex(ValueError, "changed in Context"):
            self.tuned(glossary="ミカ (Mika)", glossary_revision=base)
        self.assertEqual(
            self.compare.state("p1")["glossaryRevision"],
            read(self.game)["glossary"]["revision"],
        )

    def test_use_these_settings_saves_nothing_when_the_model_switch_is_refused(self):
        # It saved the glossary and instruction, then Settings refused the
        # model, leaving the guidance changed and the model as it was.
        estimate = self.tuned(glossary="ミカ (Mika)", instruction="Be terse.")
        before = read(self.game)
        self.compare.guided.settings.use_model = Mock(
            side_effect=ValueError("Save the base OpenRouter model ID")
        )
        with self.assertRaisesRegex(ValueError, "base OpenRouter"):
            self.compare.use("p1", estimate, 0)
        self.assertEqual(read(self.game), before)
        self.assertEqual(
            self.compare.guided.settings.use_model.call_args.kwargs, {"check": True}
        )

    def test_a_model_that_did_not_translate_every_line_is_not_used(self):
        # Model vs model offered to use a model that failed or was stopped.
        estimate = self.estimated()
        translation = self.compare.translate("p1", estimate)
        translation.update(
            status="stopped",
            result={"models": [{"index": 0, "cost": 0.01, "error": "Stopped."}]},
        )
        with self.assertRaisesRegex(ValueError, "every line"):
            self.compare.use("p1", estimate, 0)
        self.compare.guided.settings.use_model.assert_not_called()
        translation.update(
            status="complete", result={"models": [{"index": 0, "cost": 0.01}]}
        )
        self.compare.use("p1", estimate, 0)

    def test_use_these_settings_adds_its_instruction_once(self):
        # A second click added the same instruction to the game's again.
        estimate = self.tuned(instruction="Use British spelling.")
        self.compare.use("p1", estimate, 0)
        self.compare.use("p1", estimate, 0)
        self.assertEqual(read(self.game)["game"]["text"], "Use British spelling.\n")

    def test_every_row_of_a_long_comparison_takes_a_pick(self):
        # All lines, or a cut keeping whole command lists, gives more than
        # 400 rows, past a fixed cap on picks that refused every save.
        estimate = self.estimated()
        lines = [{"id": f"/{row}", "speaker": "", "source": "村"} for row in range(450)]
        self.operations.jobs[estimate]["result"]["lines"] = lines
        translation = self.compare.translate("p1", estimate)["id"]
        picks = {line["id"]: 0 for line in lines}
        self.compare.marks("p1", translation, picks, True, False)
        for wrong in ({"/450": 0}, {"/0": 1}):
            with self.assertRaisesRegex(ValueError, "Pick one"):
                self.compare.marks("p1", translation, wrong, True, False)

    def test_a_comparison_stops_in_any_method(self):
        # Assistant-led and Manual comparisons had no stop, as guided_stop
        # reads a Guided record, while they held every other operation.
        estimate = self.estimated()
        started = self.compare.translate("p1", estimate)
        other = self.operations.start(
            {"action": "compare_translate", "project_id": "p2"}
        )
        self.assertEqual(
            [job["id"] for job in self.compare.operations("p1")],
            [started["id"], estimate],
        )
        self.operations.stop = Mock(return_value=started)
        self.compare.stop("p1", started["id"])
        self.operations.stop.assert_called_once_with(started["id"])
        with self.assertRaisesRegex(ValueError, "no longer running"):
            self.compare.stop("p1", other["id"])


class WaitTests(unittest.TestCase):
    def test_work_that_waits_for_a_comparison_says_so(self):
        # Saves, compile and accept on other pages asked to finish a phased
        # run while a comparison held their queue.
        from dazedtl.translation.guided import Guided
        from dazedtl.translation.service import Translation

        jobs = {"o": {"status": "running", "action": "compare_translate"}}
        operations = SimpleNamespace(jobs=jobs, running=lambda: True)
        service = SimpleNamespace(
            jobs=SimpleNamespace(running=lambda *_: False),
            settings=SimpleNamespace(
                adapter=SimpleNamespace(running=lambda: True, operations=operations)
            ),
        )
        guided = SimpleNamespace(
            backend=SimpleNamespace(operations=operations, running=lambda: True),
            translation=SimpleNamespace(jobs=SimpleNamespace(running=lambda: False)),
        )
        for wait in (
            lambda: Translation.idle(service, "p1"),
            lambda: Guided.idle(guided),
        ):
            with self.assertRaisesRegex(ValueError, "Compare models"):
                wait()
        jobs["o"]["action"] = "tool_run"
        with self.assertRaisesRegex(ValueError, "phased run"):
            Translation.idle(service, "p1")
