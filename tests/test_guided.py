"""Guided approvals must retain scope, ownership and one-use submission intent."""

import json
import os
import shutil
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.compatibility import original_files
from dazedtl.compatibility.game_write import write_game
from dazedtl.projects.store import Projects
from dazedtl.storage import write_json
from dazedtl.translation import (
    comment_text,
    context_setup,
    event_text,
    header_review,
    preparation,
    speaker_setup,
)
from dazedtl.translation.files import digest, evidence, read_json
from dazedtl.translation.guided import Guided, retained_position
from dazedtl.translation.guided_inputs import GuidedInputs
from dazedtl.translation.release import packing_state

from tests.engine import engine_module, replaced_modules
from tests.game_writes import game_write

custom_patterns = engine_module("util/custom_patterns.py")


class RetainedPositionTests(unittest.TestCase):
    def test_positions_from_earlier_stage_layouts_open_the_task_holding_their_work(
        self,
    ):
        value = retained_position(
            {
                "step": "apply",
                "task": "qa",
                "positions": {
                    "prepare": "baseline",
                    "translate": "dialogue",
                    "plugins": "plugins",
                    "apply": "tools",
                    "review": "package",
                },
            }
        )
        self.assertEqual((value["step"], value["task"]), ("check", "qa"))
        # The translate stage keeps its own task over one moved in from Plugin text.
        self.assertEqual(
            value["positions"],
            {
                "setup": "setup",
                "translate": "dialogue",
                "check": "qa",
                "release": "package",
            },
        )
        value = retained_position({"step": "images", "task": "image-manager"})
        self.assertEqual((value["step"], value["task"]), ("translate", "images"))
        # The removed Pending changes and Line width check tasks open Text QA.
        for task in ("apply", "fitting"):
            value = retained_position({"step": "check", "task": task})
            self.assertEqual((value["step"], value["task"]), ("check", "qa"))
        self.assertNotIn("step", retained_position({"positions": {}}))


class HeaderReviewTests(unittest.TestCase):
    def test_review_fixes_only_reviewed_headers_and_records_every_decision(self):
        def header(name, text, face=""):
            return [
                {"code": 101, "indent": 0, "parameters": [face, 0, 0, 2, name]},
                {"code": 401, "indent": 0, "parameters": [text]},
            ]

        def flag(index, name, text, face=""):
            return {
                "kind": "self-address",
                "file": "Map001.json",
                "pointer": f"/events/1/pages/0/list/{index}",
                "face_name": face,
                "face_index": 0,
                "name": name,
                "text": text,
                "evidence": "Why it was flagged.",
                "lines": [f"/events/1/pages/0/list/{index + 1}"],
            }

        with TemporaryDirectory() as folder:
            game = Path(folder)
            data = game / "data"
            commands = [
                *header("アリナ", "アリナちゃん、いらっしゃい！", "arina"),
                *header("アリナ", "アリナちゃんの歌♪", "arina"),
            ]
            document = {"events": [None, {"pages": [{"list": commands}]}]}
            path = data / "Map001.json"
            path.parent.mkdir()
            # RPG Maker MV's own layout: one entry per line, no indentation,
            # as a game has it before Set up formats its data.
            event = json.dumps(
                document["events"][1], ensure_ascii=False, separators=(",", ":")
            )
            original = f'{{\n"events":[\nnull,\n{event}\n]\n}}'
            path.write_text(original, encoding="utf-8")
            headers = {
                "total": 2,
                "flags": [
                    flag(0, "アリナ", "アリナちゃん、いらっしゃい！", "arina"),
                    flag(2, "アリナ", "アリナちゃんの歌♪", "arina"),
                ],
            }
            fix = {
                "file": "Map001.json",
                "pointer": "/events/1/pages/0/list/0",
                "decision": "fix",
                "face_name": "",
                "face_index": 0,
                "name": "店主",
                "reason": "The owner greets her.",
            }
            keep = {
                "file": "Map001.json",
                "pointer": "/events/1/pages/0/list/2",
                "decision": "keep",
                "reason": "She sings her own name.",
            }
            report = game / header_review.REPORT

            def fix_headers():
                with write_game(game) as written:
                    header_review.apply(game, data, headers, written)

            # Every flag needs a decision, a fix a face the game shows, and
            # nothing is written until the whole review holds.
            for reviews in (
                [fix],
                [{**fix, "face_name": "nobody"}, keep],
            ):
                write_json(report, {"version": 1, "reviews": reviews})
                with self.assertRaises(ValueError):
                    fix_headers()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), document)
            write_json(report, {"version": 1, "reviews": [fix, keep]})
            fix_headers()
            commands[0]["parameters"][0] = ""
            commands[0]["parameters"][4] = "店主"
            # Only the fixed header's values changed; the layout stays.
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                original.replace('"arina",0,0,2,"アリナ"', '"",0,0,2,"店主"', 1),
            )
            # A later scan no longer flags the fix; the sheet still lists it
            # beside the kept flag, in the game's order.
            rows = header_review.view(
                {"total": 1, "flags": headers["flags"][1:]},
                header_review.recorded(game),
            )
            self.assertEqual(
                [
                    (row["name"], row["decision"], row["reason"])
                    for row in rows["flags"]
                ],
                [
                    ("アリナ", "fixed", "The owner greets her."),
                    ("アリナ", "kept", "She sings her own name."),
                ],
            )
            self.assertEqual(rows["flags"][0]["fixedTo"]["name"], "店主")
            # A header that changed since the scan is not overwritten.
            write_json(report, {"version": 1, "reviews": [fix, keep]})
            with self.assertRaisesRegex(ValueError, "changed"):
                fix_headers()


class GuidedTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "game"
        write_json(self.source / "Items.json", [{"name": "薬"}])
        self.projects = Projects(self.root / "profile")
        self.record = self.projects.open({"source": str(self.source), "engine": "MVMZ"})
        self.identity = self.record["id"]
        self.record["backend_id"] = "native"
        self.projects.save()
        self.native = {
            "id": "native",
            "source": str(self.source),
            "engine": "MVMZ",
            "revision": 0,
            "selected": ["Items.json"],
            "imported": ["Items.json"],
            "mode": "batch",
            "engine_options": {},
            "widths": {"width": 50, "faceWidth": 40, "listWidth": 50, "noteWidth": 50},
            "phase1_comments": False,
            "data": str(self.source),
        }
        self.started = []
        self.pending = None
        self.folder = self.root / "work"
        self.folder.mkdir()

        def update(_identity, revision, values):
            if revision != self.native["revision"]:
                raise ValueError("Changed")
            self.native.update(values)
            self.native["revision"] += 1
            return {"project": self.native}

        def apply_settings(_identity, revision, options, key, receipt):
            if revision != self.native["revision"]:
                raise ValueError("Changed")
            self.native["engine_options"] = {
                **self.native["engine_options"],
                **options,
            }
            self.native.update({key: receipt, "revision": revision + 1})
            return self.native

        workflows = SimpleNamespace(
            projects={"native": self.native},
            folder=lambda _: self.folder,
            state=lambda _: {"project": self.native, "manual_job": self.pending},
            documents=lambda _: {},
            update=update,
            apply_investigation_settings=apply_settings,
            save=Mock(),
            phase=lambda owner, phase, sync: (
                self.started.append((owner, phase, sync)) or {"id": "paid-run"}
            ),
        )
        self.backend = SimpleNamespace(
            workflows=workflows,
            allow_providers=False,
            running=lambda: False,
            guided_text_state=lambda *_: {"publications": [], "qa": {}},
            guided_text_publication=lambda *_: {},
            phase_files=lambda _native, _phase: ["Items.json"],
            guided_guard=lambda _native, _folder: evidence(self.source, ["Items.json"]),
            guided_guard_context=lambda native, _observed: self.backend.guided_guard(
                native, None
            ),
            guided_runtime_files=lambda _source: ["Items.json"],
            guided_ace_packing=packing_state,
            game_write=game_write,
        )
        choices = {
            "CODE357": ["TextPicture", "QuestSystem"],
            "CODE355655": ["var text", "gameVariables.setValue"],
        }
        self.catalog = {
            "fingerprint": "fixture-definitions",
            "source": "fixture-parser.py",
            "controls": [
                {
                    "key": key,
                    "label": key,
                    "coverage": "Installed fixture coverage.",
                    "selector": event_text.SELECTORS.get(key),
                    "choices": [
                        {"id": name, "group": "Fixture entries", "details": name}
                        for name in choices.get(key, [])
                    ],
                    "builtins": ["BuiltinPlugin"]
                    if key == "CODE357"
                    else ["AddCmnt("]
                    if key == "CODE355655"
                    else ["D_TEXT ", "CommonPopup"]
                    if key == "CODE356"
                    else [],
                }
                for key in event_text.CODES
            ],
        }
        self.backend.guided_event_text_catalog = lambda: deepcopy(self.catalog)

        def validate_event_options(values):
            if set(values) - set(event_text.FIELDS):
                raise ValueError("Unknown setting")
            for key, value in values.items():
                if key in event_text.CODES and type(value) is not bool:
                    raise ValueError("Invalid boolean")
                if key == "CODE122_VAR_RANGES" and not isinstance(value, str):
                    raise ValueError("Invalid ranges")
                for code, selector in event_text.SELECTORS.items():
                    if key == selector and (
                        not isinstance(value, list)
                        or any(item not in choices[code] for item in value)
                    ):
                        raise ValueError("Unknown registry identifier")
            return {
                key: custom_patterns.normalize(key, value)
                if key in event_text.CUSTOM.values()
                else deepcopy(value)
                for key, value in values.items()
            }

        self.backend.guided_event_text_options = validate_event_options
        self.backend.guided_event_text_custom = custom_patterns.problems
        self.backend.operations = SimpleNamespace(
            jobs={}, start=Mock(), running=lambda: False
        )
        self.backend.describe = lambda _: dict(self.native)
        self.backend.guided_phase = lambda owner, phase, files: (
            self.backend.workflows.phase(owner, phase, True)
        )
        self.settings_revision = 1
        self.configuration = {
            "model": "fixture-model",
            "provider": "custom",
            "protocol": "openai",
            "endpoint": "https://provider.invalid/v1",
            "rates": {"input": 1, "output": 2},
            "language": "English",
        }
        # Whether each configuration read could only use cached prices.
        self.priced = []
        self.uncached = False

        def guided_configuration(mode, cached_only=False, unpriced=False, pair=None):
            self.priced.append(cached_only)
            configuration = {
                **deepcopy(self.configuration),
                "mode": mode,
                "revision": self.settings_revision,
            }
            if cached_only and self.uncached:
                if not unpriced:
                    raise ValueError("Model pricing is unknown.")
                configuration["rates"] = {"input": None, "output": None}
            return configuration

        self.settings = SimpleNamespace(
            prepare_engine=lambda **_kwargs: None,
            describe=lambda: {"revision": self.settings_revision},
            guided_configuration=guided_configuration,
            language=lambda: self.configuration["language"],
            connection_summary=lambda: {"name": "Fixture connection"},
        )
        self.backend.manual = SimpleNamespace(
            jobs={}, folder=lambda identity: self.root / "runs" / identity
        )
        self.backend.saved_run_configuration = lambda identity: {
            "workflow": {
                "id": "native",
                "phase": self.guided.runs.records(self.identity)[identity]["phase"],
            }
        }
        self.backend.guided_run_context = lambda: {"system.md": "fixture-context"}
        self.translation = SimpleNamespace(
            workspace=self.root / "profile",
            jobs=SimpleNamespace(running=lambda: False),
            engine=SimpleNamespace(
                source_bindings=lambda _source, _paths: {},
                original_bytes=lambda *_args: b"",
                original_blobs=lambda _source, blobs: ((blob, b"") for blob in blobs),
            ),
            clean_drafts=lambda _: None,
            ready=Mock(),
            operation=Mock(return_value={"id": "operation"}),
            game_update=SimpleNamespace(
                sync=lambda _: None, require_ready=lambda _: None
            ),
        )
        self.git_configured = False
        self.translation.project = lambda _: (
            self.record,
            SimpleNamespace(root=self.source, read=lambda: {"options": {}}),
        )
        self.translation.engine.git_status = lambda *_: {
            "configured": self.git_configured
        }
        self.guided = Guided(
            self.backend, self.projects, self.settings, self.translation
        )

    def test_file_preview_uses_actual_files_without_selection_or_request_receipts(self):
        # A saved translation without request provenance must remain readable;
        # previewing an unchecked file must never prepare, select or mutate it.
        self.native["selected"] = []
        before = {
            path: path.read_bytes() for path in self.source.rglob("*") if path.is_file()
        }
        page = self.guided.file_preview(self.identity, "Items.json")
        self.assertEqual((page["origin"], page["rows"][0]["text"]), ("game", "薬"))
        self.assertEqual(self.native["selected"], [])
        self.assertEqual(
            before,
            {
                path: path.read_bytes()
                for path in self.source.rglob("*")
                if path.is_file()
            },
        )
        self.assertFalse((self.folder / "source-inputs.json").exists())
        write_json(
            self.folder / "files/Items.json", [{"name": "薬", "description": "説明"}]
        )
        self.assertEqual(
            self.guided.file_preview(self.identity, "Items.json")["origin"], "working"
        )
        output = [
            {
                "name": "Potion",
                "description": "",
                "_original": {"name": "薬", "description": "説明"},
            }
        ]
        write_json(self.folder / "translated/Items.json", output)
        page = self.guided.file_preview(self.identity, "Items.json")
        self.assertEqual(page["origin"], "translated")
        self.assertEqual(
            [(row["location"], row["source"], row["text"]) for row in page["rows"]],
            [("/0/name", "薬", "Potion"), ("/0/description", "説明", "")],
        )
        self.assertFalse(any("_original" in row["location"] for row in page["rows"]))
        # Plain unchanged notes should not look like missing translations.
        note = "ステート1番はHP0のときに付加されます。"
        write_json(
            self.folder / "files/Items.json",
            [{"name": "薬", "description": "説明", "note": note}],
        )
        write_json(
            self.folder / "translated/Items.json",
            [{**output[0], "note": note, "unmatched": "New text"}],
        )
        page = self.guided.file_preview(self.identity, "Items.json")
        self.assertEqual(
            [row["location"] for row in page["rows"]],
            ["/0/name", "/0/description", "/0/unmatched"],
        )
        self.assertEqual(
            self.guided.file_preview(self.identity, "Items.json", query=note)["total"],
            0,
        )
        # Pagination and text search stay bounded, with no dropped text between pages.
        write_json(
            self.folder / "translated/Items.json",
            [
                {
                    "name": f"Item {index}",
                    "note": "long" * 3000 if index == 5 else "Note",
                }
                for index in range(180)
            ],
        )
        offset, locations = 0, []
        while offset is not None:
            part = self.guided.file_preview(self.identity, "Items.json", offset)
            self.assertLessEqual(len(part["rows"]), 80)
            self.assertTrue(all(len(row["text"]) <= 8000 for row in part["rows"]))
            locations.extend(row["location"] for row in part["rows"])
            offset = part["nextOffset"]
        self.assertEqual(len(locations), 360)
        self.assertEqual(len(set(locations)), 360)
        match = self.guided.file_preview(self.identity, "Items.json", query="Item 179")
        self.assertEqual(
            (match["total"], match["rows"][0]["location"]), (1, "/179/name")
        )
        for kwargs in (
            {"name": "../secret.json"},
            {"name": "Foreign.json"},
            {"name": "Items.json", "offset": -1},
            {"name": "Items.json", "offset": True},
        ):
            with self.assertRaises(ValueError):
                self.guided.file_preview(self.identity, **kwargs)
        with self.assertRaises(ValueError):
            self.guided.file_preview("foreign-project", "Items.json")
        (self.folder / "translated/Items.json").unlink()
        (self.folder / "translated/Items.json").symlink_to(self.source / "Items.json")
        with self.assertRaises(ValueError):
            self.guided.file_preview(self.identity, "Items.json")

    def test_matching_estimates_survive_reopening_and_reject_each_changed_input(self):
        with self.assertRaisesRegex(ValueError, "current estimate"):
            self.guided.preview(self.identity, "start", options={"mode": "batch"})
        identity = self.seed_estimate()
        reopened = Guided(self.backend, self.projects, self.settings, self.translation)
        quote, _ = reopened.runs.quote(self.identity, self.native, "database", "batch")
        self.assertTrue(quote["current"])
        preview = reopened.preview(self.identity, "start", options={"mode": "batch"})
        self.assertEqual(preview["estimate"]["jobId"], identity)
        self.assertEqual(
            preview["estimate"]["value"], self.backend.manual.jobs[identity]["estimate"]
        )
        originals = deepcopy(self.native), deepcopy(self.configuration)
        changes = [
            lambda: self.native["widths"].update(width=51),
            lambda: self.native["engine_options"].update(NAMES=True),
            lambda: self.native.update(phase1_comments=True),
            lambda: self.configuration.update(endpoint="https://changed.invalid/v1"),
            lambda: self.configuration.update(language="French"),
            lambda: self.configuration.update(
                generationParameters="provider-defaults-v1"
            ),
        ]
        for change in changes:
            change()
            with self.subTest(change=change):
                self.assertFalse(
                    reopened.runs.quote(
                        self.identity, self.native, "database", "batch"
                    )[0]["current"]
                )
                with self.assertRaises(ValueError):
                    reopened.preview(self.identity, "start", options={"mode": "batch"})
            self.native.clear()
            self.native.update(deepcopy(originals[0]))
            self.configuration.clear()
            self.configuration.update(deepcopy(originals[1]))
        # Another model of the connection keeps the requests, which its
        # rates then price; reviewing it shows that price.
        self.configuration.update(model="changed-model")
        self.configuration["rates"].update(input=0.5)
        quote, _ = reopened.runs.quote(self.identity, self.native, "database", "batch")
        self.assertTrue(quote["current"])
        self.assertEqual(quote["job"]["estimate"]["model"], "changed-model")
        self.assertAlmostEqual(quote["job"]["estimate"]["live_cost"], 0.008)
        preview = reopened.preview(self.identity, "start", options={"mode": "batch"})
        self.assertEqual(preview["estimate"]["value"], quote["job"]["estimate"])
        self.configuration.clear()
        self.configuration.update(deepcopy(originals[1]))
        self.assertFalse(
            reopened.runs.quote(self.identity, self.native, "database", "translate")[0][
                "current"
            ]
        )
        self.backend.guided_run_context = lambda: {"system.md": "changed-context"}
        self.assertFalse(
            reopened.runs.quote(self.identity, self.native, "database", "batch")[0][
                "current"
            ]
        )
        self.backend.guided_run_context = lambda: {"system.md": "fixture-context"}
        self.backend.guided_guard = lambda *_: {"glossary": "changed-guidance"}
        self.assertFalse(
            reopened.runs.quote(self.identity, self.native, "database", "batch")[0][
                "current"
            ]
        )
        self.backend.guided_guard = lambda *_: evidence(self.source, ["Items.json"])
        write_json(self.source / "Items.json", [{"name": "別"}])
        self.assertFalse(
            reopened.runs.quote(self.identity, self.native, "database", "batch")[0][
                "current"
            ]
        )
        self.assertEqual(self.started, [])

    def test_translate_reopens_an_unchanged_estimate_until_its_work_is_approved(self):
        # Each Translate click estimated the whole selection again, minutes on
        # a large game, though declining its review changed nothing. Reopening
        # must end with the inputs, a Claude count it still owes, or paid work
        # approved from it.
        manual = self.backend.manual
        manual.allow_providers = True
        manual.discard_preparation = manual.jobs.pop
        estimate = self.seed_estimate()
        manual.jobs[estimate]["dazedtl_preapproval"] = True

        def translate(mode="estimate"):
            review = self.guided.preview(self.identity, "start", options={"mode": mode})
            return self.guided.execute(self.identity, review["token"])["id"]

        self.assertEqual(translate(), estimate)
        # So does another model that only prices the same requests.
        self.configuration.update(model="changed-model")
        self.assertEqual(translate(), estimate)
        self.configuration.update(model="fixture-model")
        # A Batch preparation keeps its estimate until it is approved, and
        # the next Translate replaces the preparation.
        self.assertEqual(translate("batch"), "paid-run")
        manual.jobs["paid-run"] = {"id": "paid-run", "dazedtl_preapproval": True}
        self.assertEqual(translate(), estimate)
        self.assertNotIn("paid-run", manual.jobs)
        self.assertEqual(len(self.started), 1)
        inputs = self.guided.runs.inputs(
            self.identity, self.native, "database", "batch"
        )

        def unchanged():
            return self.guided.actions.unchanged_estimate(
                self.identity, self.native, "database", inputs
            )

        manual.jobs[estimate]["estimate"].update(
            provider="anthropic", approximate_input=True
        )
        self.assertIsNone(unchanged())
        configuration = self.backend.saved_run_configuration
        self.backend.saved_run_configuration = lambda identity: {
            **configuration(identity),
            "dazedtl_claude_count": False,
        }
        self.assertEqual(unchanged(), estimate)
        manual.jobs["paid-run"] = {"id": "paid-run", "dazedtl_approved": True}
        self.guided.runs.remember(
            self.identity, manual.jobs["paid-run"], inputs, {"jobId": estimate}
        )
        self.assertIsNone(unchanged())
        manual.jobs.pop("paid-run")
        self.native["widths"]["width"] = 51
        self.assertNotEqual(translate(), estimate)
        self.assertNotIn(estimate, manual.jobs)

    def test_whole_game_estimate_stays_current_across_selection_and_mode(self):
        # Context's Cost estimate prices every file of each Translate task at
        # both Batch and Live prices. It must read current as soon as it
        # finishes, through a new file selection or a Batch/Live switch, and
        # outdated once its sources change.
        self.git_configured = True
        self.settings.translation_defaults = lambda: {
            "model": "fixture-model",
            "batch_supported": True,
        }
        self.backend.workflows.phase_workflow = lambda _owner, phase: {"phase": phase}
        self.backend.manual.request_policy = {"model": "fixture-model"}
        self.backend.manual.allow_providers = False
        plans = []
        self.backend.operations.start.side_effect = lambda plan: (
            plans.append(plan) or {"id": "estimate"}
        )
        self.guided.full_estimate.start(self.identity)
        options = plans[0]["options"]
        self.assertEqual(
            [(task["phase"], task["noSources"]) for task in options["tasks"]],
            [("database", False), ("dialogue", False), ("advanced", True)],
        )
        # A launch with providers disabled never reaches Anthropic's count.
        self.assertIs(options["claudeCount"], False)
        self.backend.operations.jobs["estimate"] = {
            "id": "estimate",
            "action": "full_estimate",
            "project_id": "native",
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "status": "complete",
            "result": {
                "fingerprint": options["fingerprint"],
                "shape": options["shape"],
                "configuration": options["configuration"],
                "tasks": [{"phase": "dialogue", "inputTokens": 4000, "liveCost": 0.01}],
                "measured": {
                    "dialogue": {
                        "provider": "custom",
                        "input_tokens": 4000,
                        "output_tokens": 3000,
                    }
                },
            },
        }

        def status():
            with self.guided.observations.read():
                found = self.guided.event_text.status(self.identity, self.native)
                return self.guided.full_estimate.status(
                    self.identity, self.native, found
                )

        def current():
            return status()["current"]

        self.assertTrue(current())
        self.native.update(selected=[], mode="translate")
        self.assertTrue(current())
        # Another model of the connection prices the same requests.
        self.configuration.update(model="changed-model")
        self.configuration["rates"].update(input=0.5)
        repriced = status()
        self.assertTrue(repriced["current"])
        self.assertEqual(repriced["result"]["model"], "changed-model")
        self.assertAlmostEqual(repriced["result"]["tasks"][0]["liveCost"], 0.008)
        self.configuration.update(model="fixture-model")
        self.configuration["rates"].update(input=1)
        # An estimate a listed release saved reads as made under version 1,
        # current until the version is raised.
        from dazedtl.translation import full_estimate

        with patch.object(full_estimate, "ESTIMATE_VERSION", 1):
            estimate = self.guided.full_estimate
            with self.guided.observations.read():
                tasks = estimate.scope(
                    self.identity,
                    self.native,
                    self.guided.event_text.status(self.identity, self.native),
                    guard=self.guided.runs.poll_guard(self.native),
                    cached_only=True,
                )
            self.backend.operations.jobs["estimate"]["result"].update(
                {
                    key: estimate.fingerprint(tasks, key, "2.24.0")
                    for key in ("fingerprint", "shape")
                }
            )
            self.assertTrue(current())
            # Raising the version outdates it; pricing it again does not help.
            with patch.object(full_estimate, "ESTIMATE_VERSION", 2):
                self.assertFalse(current())
            # Estimating again would only repeat it, unless Claude's count failed.
            with self.assertRaisesRegex(ValueError, "Nothing changed"):
                self.guided.full_estimate.start(self.identity)
            self.backend.operations.jobs["estimate"]["result"]["tasks"] = [
                {"approximateInput": True}
            ]
            self.guided.full_estimate.start(self.identity)
            # Raising the estimate version outdates every saved estimate.
            with patch.object(full_estimate, "ESTIMATE_VERSION", 2):
                self.assertFalse(current())
        self.native["engine_options"]["CODE356"] = True
        self.assertFalse(current())

    def test_warm_polls_neither_reread_nor_resolve_a_long_historys_outputs(self):
        # Every poll checks every saved run's outputs. A 2.14.0 user's polls
        # took 30 s on Windows once a history outgrew the digest caches, which
        # then parsed every output again, and each output's path was resolved
        # on every poll; every click and page switch waited behind them.
        import io
        import time

        from dazedtl.compatibility import checkpoints

        names = [f"Map{index:03}.json" for index in range(30)]
        still = time.time_ns() - 3600 * 10**9
        for name in names:
            write_json(self.source / name, {"text": "原文"})
            os.utime(self.source / name, ns=(still, still))
        self.native["data"] = str(self.source)
        outputs = []
        for run in range(3):
            identity = f"history-{run}"
            root = self.backend.manual.folder(identity)
            plan = {
                "mode": "translate",
                "workflow": {"id": "native", "phase": "maps"},
                "files": [{"name": name, "sha256": "0" * 64} for name in names],
            }
            write_json(root / "plan.json", plan)
            receipts = {}
            for name in names:
                write_json(root / "translated" / name, {"text": f"Run {run}"})
                os.utime(root / "translated" / name, ns=(still, still))
                receipts[name] = digest((root / "translated" / name).read_bytes())
                outputs.append(os.fspath(root / "translated" / name))
            write_json(
                root / checkpoints.INDEX,
                {
                    "version": 1,
                    "plan_hash": digest((root / "plan.json").read_bytes()),
                    "files": receipts,
                },
            )
            self.backend.manual.jobs[identity] = {
                "id": identity,
                "mode": "translate",
                "status": "complete",
                "phase": "done",
                "files": names,
                "completed": names,
                "created": f"2026-01-0{run + 1}",
                "plan_hash": digest((root / "plan.json").read_bytes()),
            }
            self.native.setdefault("collected", []).append(identity)
        self.backend.saved_run_configuration = lambda identity: read_json(
            self.backend.manual.folder(identity) / "plan.json"
        )

        def poll():
            with self.guided.observations.read():
                self.guided.runs.snapshot(
                    self.identity, self.native, {"changed": [], "retired": []}
                )
                return [
                    self.guided.run_view(f"history-{run}", compact=True)
                    for run in range(3)
                ]

        opened, resolved = [], []
        native_open, native_resolve = io.open, Path.resolve

        def counted_open(file, *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and os.fspath(file) in outputs:
                opened.append(file)
            return native_open(file, *args, **kwargs)

        def counted_resolve(path, *args, **kwargs):
            resolved.append(path)
            return native_resolve(path, *args, **kwargs)

        # A history far longer than the caches, scaled down.
        with (
            patch.object(self.guided.observations.digests, "limit", 10),
            patch.object(checkpoints._DIGESTS, "limit", 10),
        ):
            poll()
            with (
                patch("builtins.open", counted_open),
                patch("io.open", counted_open),
                patch.object(Path, "resolve", counted_resolve),
            ):
                views = poll()
        self.assertEqual(
            [sorted(view["availableOutputs"]) for view in views], [names] * 3
        )
        self.assertEqual(opened, [])
        self.assertLess(len(resolved), len(outputs))

    def test_snapshots_match_estimates_on_cached_prices_without_a_lookup(self):
        # A price lookup runs a worker that a slow catalog download held past
        # its 12 s limit; snapshots waited on it once per phase, so every poll
        # took about 50 seconds.
        self.seed_estimate()
        self.priced.clear()
        snapshot = self.guided.runs.snapshot(
            self.identity, self.native, {"changed": [], "retired": []}
        )
        self.assertEqual(set(self.priced), {True})
        self.assertTrue(snapshot["estimates"]["database"]["current"])
        # Prices not looked up since DazedTL started, as after a restart,
        # leave an estimate of the same settings current; another model's
        # unknown prices can't price it, while preparing a review looks them up.
        self.uncached = True

        def current():
            return self.guided.runs.snapshot(
                self.identity, self.native, {"changed": [], "retired": []}
            )["estimates"]["database"]["current"]

        self.assertTrue(current())
        self.configuration.update(model="changed-model")
        self.assertFalse(current())
        self.priced.clear()
        self.guided.preview(self.identity, "start", options={"mode": "batch"})
        self.assertEqual(set(self.priced), {False})

    def test_a_quote_cannot_start_after_pricing_or_runtime_context_changes_in_review(
        self,
    ):
        preview = self.preview()
        self.configuration["rates"]["input"] = 3
        with self.assertRaisesRegex(ValueError, "estimate inputs changed"):
            self.guided.execute(self.identity, preview["token"])
        preview = self.preview()
        self.backend.guided_run_context = lambda: {"system.md": "new-system-prompt"}
        with self.assertRaisesRegex(ValueError, "estimate inputs changed"):
            self.guided.execute(self.identity, preview["token"])
        self.assertEqual(self.started, [])

    def declined_names_run(self):
        """A map Batch declined after its names were translated and saved."""
        identity = "paid-names"
        root = self.backend.manual.folder(identity)
        plan = {
            "mode": "batch",
            "workflow": {"id": "native"},
            "settings": {"language": "English"},
        }
        write_json(root / "plan.json", plan)
        glossary = root / "game/.dazedtl/glossary.txt"
        glossary.parent.mkdir(parents=True)
        glossary.write_text(
            "# Speakers\n回想部屋 (Recollection Room)\n", encoding="utf-8"
        )
        job = {
            "id": identity,
            "mode": "batch",
            "status": "canceled",
            "phase": "canceled",
            "created": "2026-01-01",
            "files": ["Items.json"],
            "dazedtl_preapproval": True,
            "dazedtl_approved": True,
            # Approving the names records it, though no Batch was approved.
            "dazedtl_submission_intent": True,
            "estimate": {"speakers": ["回想部屋"]},
            "log": ["Speaker translations saved to the game glossary."],
            "plan_hash": digest((root / "plan.json").read_bytes()),
        }
        self.backend.manual.jobs[identity] = job
        self.native.setdefault("collected", []).append(identity)
        self.backend.saved_run_configuration = lambda run: read_json(
            self.backend.manual.folder(run) / "plan.json"
        )
        return identity, root, plan

    def test_canceled_batch_keeps_paid_names_in_quotes_without_crossing_ownership(self):
        # Protect paying for the same names again after declining the map Batch,
        # while keeping unrelated projects, languages and source passes isolated.
        identity, root, plan = self.declined_names_run()
        english = {"source": "Japanese", "target": "English"}
        reused = self.guided.runs.name_reuse(self.native, english)
        self.assertEqual(
            reused,
            [
                {
                    "source": "回想部屋",
                    "translation": "Recollection Room",
                    "runId": identity,
                }
            ],
        )
        self.assertEqual(
            self.guided.name_results(self.identity, identity)["rows"][0]["translation"],
            "Recollection Room",
        )
        self.assertEqual(
            self.guided.run_view(identity, compact=True)["nameTranslation"]["state"],
            "saved",
        )
        before = self.guided.runs.inputs(
            self.identity, self.native, "database", "batch"
        )
        self.assertEqual(before["reused_names"], reused)
        self.backend.guided_phase = lambda *_: {
            "id": "next",
            "seed": self.backend.manual.reused_names,
        }
        self.assertEqual(
            self.guided.actions._start(
                self.identity, "estimate", "database", ["Items.json"], before
            )["seed"],
            reused,
        )
        self.assertIsNone(self.backend.manual.reused_names)
        self.assertEqual(
            self.guided.runs.name_reuse(self.native, {**english, "target": "French"}),
            [],
        )
        # Names from an English game's run never answer for a Japanese one's.
        self.assertEqual(
            self.guided.runs.name_reuse(
                self.native, {"source": "English", "target": "Japanese"}
            ),
            [],
        )
        with self.assertRaises(ValueError):
            self.guided.name_results(self.identity, "foreign")
        plan["workflow"]["id"] = "foreign"
        write_json(root / "plan.json", plan)
        self.assertEqual(self.guided.runs.name_reuse(self.native, english), [])
        plan["workflow"]["id"] = "native"
        write_json(root / "plan.json", plan)
        write_json(
            self.folder / "source-inputs.json",
            {"version": 1, "inputs": {}, "retired_runs": [identity]},
        )
        self.assertEqual(self.guided.runs.name_reuse(self.native, english), [])

    def test_declined_batch_adds_its_paid_names_to_the_game_glossary_once(self):
        # Paid names stayed in the declined run's own glossary, so the game's
        # never showed them. Collecting a completed run copies its glossary
        # over the game's, so a Batch that may still complete is left to that.
        # Every snapshot runs this, so it must not need prices, which are
        # uncached after a restart: that read "Project unavailable".
        identity, _root, _plan = self.declined_names_run()
        self.native["manual_job"] = identity
        self.uncached = True
        glossary = {"text": "# Game Characters\nミカ (Mika)", "revision": "r1"}
        saved = []

        def save(_owner, changes):
            self.assertEqual(list(changes), ["glossary"])
            self.assertEqual(changes["glossary"]["revision"], glossary["revision"])
            saved.append(changes["glossary"]["text"])
            glossary.update(
                text=changes["glossary"]["text"], revision=f"r{len(saved) + 1}"
            )

        drafts = {"glossary": {"text": "", "revision": "r1"}}
        self.backend.workflows.documents = lambda _: {"glossary": dict(glossary)}
        self.backend.workflows.documents_save = save
        self.backend.workflows.state = lambda _: {
            "project": self.native,
            "draft": {"documents": drafts},
        }
        fake = SimpleNamespace(
            parseVocabWithCategories=lambda text: [
                ((source.strip(), target), line, "")
                for line in text.splitlines()
                if " (" in line
                for source, target in [line.removesuffix(")").split(" (", 1)]
            ],
            split_vocab_source_aliases=lambda source: [source],
            speaker_source_lookup_keys=lambda source: [source],
        )
        job = self.backend.manual.jobs[identity]
        # A game update's merge stopped on conflicts: a glossary written then
        # left Versions unable to cancel the update. The names wait for Git.
        git = {
            "configured": True,
            "pending_operations": ["MERGE_HEAD"],
            "current_branch": "main",
            "translation_branch": "main",
        }
        self.translation.engine.git_status = lambda *_: git
        with replaced_modules({"util.translation": fake}):
            self.guided.runs.publish_names(self.identity, self.native)
            drafts.clear()
            job["dazedtl_batch_approval"] = {"requests": 1}
            self.guided.runs.publish_names(self.identity, self.native)
            self.assertEqual(saved, [])
            del job["dazedtl_batch_approval"]
            self.guided.runs.publish_names(self.identity, self.native)
            self.assertEqual(saved, [])
            git["pending_operations"] = []
            self.guided.runs.publish_names(self.identity, self.native)
            self.assertEqual(
                saved,
                [
                    "# Game Characters\nミカ (Mika)\n\n"
                    + "# Speakers\n回想部屋 (Recollection Room) - Unverified nameplate, "
                    + "reused from an earlier run.\n\n"
                ],
            )
            # Removing them from the game glossary is the user's choice.
            glossary["text"] = "# Game Characters\nミカ (Mika)"
            self.guided.runs.publish_names(self.identity, self.native)
        self.assertEqual(len(saved), 1)

    def test_translation_preparation_survives_reopen_and_cancel_targets_its_estimate(
        self,
    ):
        # Protect navigation/reload losing the local preparation handoff, and
        # Cancel clearing only renderer state while the estimate keeps running.
        identity = self.seed_estimate()
        job = self.backend.manual.jobs[identity]
        inputs = self.guided.runs.inputs(
            self.identity, self.native, "database", "batch"
        )
        self.guided.runs.remember(self.identity, job, inputs, preparation_mode="batch")
        job["status"] = "running"
        reopened = Guided(self.backend, self.projects, self.settings, self.translation)
        self.assertEqual(
            reopened.runs.quote(self.identity, self.native, "database", "batch")[0][
                "job"
            ]["preparationMode"],
            "batch",
        )
        self.assertEqual(
            reopened.actions._start(
                self.identity,
                "estimate",
                "database",
                ["Items.json"],
                inputs,
                preparation_mode="batch",
            )["id"],
            identity,
        )
        self.assertEqual(self.started, [])
        self.backend.manual.stop = Mock(return_value={**job, "status": "stopped"})
        reopened.stop(self.identity, identity)
        self.backend.manual.stop.assert_called_once_with(identity)
        self.assertIsNone(reopened.runs.preparation_mode(self.identity, identity))
        reopened.runs.remember(self.identity, job, inputs, preparation_mode="batch")
        reopened.runs.remember(
            self.identity, {"id": "next-run"}, inputs, {"jobId": identity}
        )
        self.assertIsNone(reopened.runs.preparation_mode(self.identity, identity))
        with self.assertRaises(ValueError):
            reopened.stop(self.identity, "foreign-run")

    def test_empty_estimate_settles_only_files_without_text_until_resync(self):
        # Protect resynced, already translated files from staying Not started
        # after an empty estimate, without completing files whose text was
        # only reused and still needs a run to write it. Live estimates count
        # no requests, so only finding no source text makes them empty.
        from dazedtl.compatibility.run_evidence import Evidence

        names = ["Items.json", "States.json"]
        checked = "2026-10-05T12:00:00+00:00"
        write_json(self.source / "States.json", [{"name": "毒"}])
        self.backend.phase_files = lambda _native, _phase: names
        self.native["selected"] = list(names)
        inputs = self.guided.inputs(self.native)
        inputs.prepare(names)
        folder = self.backend.manual.folder
        self.backend.manual.discard_preparation = lambda identity: shutil.rmtree(
            folder(identity)
        )

        def estimate(value, found=()):
            identity = self.seed_estimate()
            self.backend.manual.jobs[identity].update(estimate=value, created=checked)
            evidence = Evidence(folder(identity), "estimate")
            for name in found:
                evidence.found_text(name)
            return identity

        live = estimate({"live_cost": 0.01}, ["States.json"])
        self.assertFalse(self.guided.run_view(live)["nothingToTranslate"])
        with self.assertRaisesRegex(ValueError, "text to translate"):
            self.guided.settle_empty_estimate(self.identity, live)
        batch = estimate({"requests": 0}, ["States.json"])
        self.assertEqual(
            self.guided.settle_empty_estimate(self.identity, batch),
            {"files": ["Items.json"]},
        )
        self.assertFalse(folder(batch).exists())
        self.assertNotIn(batch, self.guided.runs.records(self.identity))
        self.assertEqual(inputs.no_requests(), {"database": {"Items.json": checked}})
        live = estimate({"live_cost": 0})
        self.assertTrue(self.guided.run_view(live)["nothingToTranslate"])
        self.assertEqual(
            self.guided.settle_empty_estimate(self.identity, live), {"files": names}
        )
        inputs.prepare(
            ["Items.json"],
            refresh=True,
            expected=inputs.sources(
                ["Items.json"], inputs.record()["inputs"], fresh=True
            ),
        )
        self.assertEqual(inputs.no_requests(), {"database": {"States.json": checked}})

    def test_independent_selection_and_refresh_do_not_reuse_a_retired_quote(self):
        write_json(self.source / "Map001.json", {"events": []})
        self.backend.phase_files = lambda _native, phase: (
            ["Items.json"] if phase == "database" else ["Map001.json"]
        )
        identity = self.seed_estimate()
        self.native["selected"].append("Map001.json")
        self.assertTrue(
            self.guided.runs.quote(self.identity, self.native, "database", "batch")[0][
                "current"
            ]
        )
        self.native["selected"].remove("Items.json")
        self.assertFalse(
            self.guided.runs.quote(self.identity, self.native, "database", "batch")[0][
                "current"
            ]
        )
        self.native["selected"].append("Items.json")
        write_json(
            self.folder / "source-inputs.json",
            {"version": 1, "inputs": {}, "retired_runs": [identity]},
        )
        self.assertFalse(
            self.guided.runs.quote(self.identity, self.native, "database", "batch")[0][
                "current"
            ]
        )

    def test_reload_does_not_reuse_results_from_an_earlier_working_copy(self):
        from dazedtl.compatibility.run_evidence import Evidence

        inputs = self.guided.inputs(self.native)
        inputs.prepare(["Items.json"])
        recorded = self.guided.runs.inputs(
            self.identity, self.native, "database", "translate"
        )
        job = {
            "id": "prior-working-copy",
            "mode": "translate",
            "status": "complete",
            "files": ["Items.json"],
            "log": [],
        }
        self.backend.manual.jobs[job["id"]] = job
        self.guided.runs.remember(self.identity, job, recorded)
        evidence = Evidence(self.backend.manual.folder(job["id"]), "translate")
        with evidence.connect() as connection:
            connection.execute(
                "INSERT INTO validated_items VALUES (?,?,?)",
                ("item", "薬", '"Prior wording"'),
            )
        self.assertEqual(
            self.guided.runs.continuation(self.identity, self.native, recorded)["item"][
                "response"
            ],
            "Prior wording",
        )
        # Adding files must retain item-level results, while a source reload
        # still invalidates only the affected file's reuse authority.
        expanded = {
            **recorded,
            "files": ["Items.json", "States.json"],
            "source": {**recorded["source"], "States.json": {"identity": "new-file"}},
        }
        self.assertEqual(
            self.guided.runs.continuation(self.identity, self.native, expanded)["item"][
                "response"
            ],
            "Prior wording",
        )
        inputs.prepare(
            ["Items.json"],
            refresh=True,
            expected=inputs.sources(
                ["Items.json"], inputs.record()["inputs"], fresh=True
            ),
        )
        current = self.guided.runs.inputs(
            self.identity, self.native, "database", "translate"
        )
        self.assertEqual(
            self.guided.runs.continuation(self.identity, self.native, current), {}
        )
        self.assertTrue(evidence.path.is_file())

    def test_completed_phase_and_apply_status_require_that_runs_verified_outputs(self):
        identity = "completed-database"
        output = [{"name": "Fixture term"}]
        write_json(
            self.backend.manual.folder(identity) / "translated/Items.json", output
        )
        expected = digest(
            (
                self.backend.manual.folder(identity) / "translated/Items.json"
            ).read_bytes()
        )
        job = {
            "id": identity,
            "mode": "batch",
            "status": "complete",
            "files": ["Items.json"],
            "outputs": {"Items.json": expected},
            "log": [],
        }
        self.backend.manual.jobs[identity] = job
        self.guided.runs.remember(
            self.identity,
            job,
            self.guided.runs.inputs(self.identity, self.native, "database", "batch"),
        )
        self.native["manual_job"] = identity
        plan = {
            "workflow": {"id": "native", "phase": "database"},
            "files": [
                {
                    "name": "Items.json",
                    "sha256": digest((self.source / "Items.json").read_bytes()),
                }
            ],
        }
        self.backend.saved_run_configuration = lambda _: plan
        self.assertEqual(
            self.guided.run_view(identity)["changedOutputs"], ["Items.json"]
        )
        plan["files"][0]["sha256"] = expected
        self.assertEqual(self.guided.run_view(identity)["changedOutputs"], [])
        status = self.guided.runs.snapshot(
            self.identity, self.native, {"changed": [], "retired": []}
        )
        self.assertTrue(status["phase_runs"]["database"]["scopeComplete"])
        self.assertEqual(
            status["phase_runs"]["database"]["availableOutputs"], ["Items.json"]
        )
        self.assertNotIn("dialogue", status["phase_runs"])
        self.assertEqual(status["phase_runs"]["database"]["appliedOutputs"], [])
        write_json(self.source / "Items.json", output)
        self.assertEqual(
            self.guided.run_view(identity)["appliedOutputs"], ["Items.json"]
        )
        # Hand fixes, Line widths and QA fixes in the game keep the last Apply.
        write_json(
            self.folder / "applied-outputs.json", {"files": {"Items.json": expected}}
        )
        write_json(self.source / "Items.json", [{"name": "Manual game edit"}])
        self.assertEqual(
            self.guided.run_view(identity)["appliedOutputs"], ["Items.json"]
        )
        # A later phase's output built from this one carries it into the game.
        later = "completed-event-codes"
        write_json(
            self.backend.manual.folder(later) / "translated/Items.json",
            [{"name": "Fixture term", "note": "Event codes"}],
        )
        later_output = digest(
            (self.backend.manual.folder(later) / "translated/Items.json").read_bytes()
        )
        self.backend.manual.jobs[later] = {
            **job,
            "id": later,
            "mode": "translate",
            "outputs": {"Items.json": later_output},
        }
        plans = {
            identity: plan,
            later: {
                "workflow": {"id": "native", "phase": "advanced"},
                "files": [{"name": "Items.json", "sha256": expected}],
            },
        }
        self.backend.saved_run_configuration = lambda run: plans[run]
        write_json(
            self.folder / "applied-outputs.json",
            {"files": {"Items.json": later_output}},
        )
        self.assertEqual(
            self.guided.run_view(identity)["appliedOutputs"], ["Items.json"]
        )
        # A VX Ace game reading only the archive beside Game.exe holds none of
        # it, whatever its data files hold.
        native = {**self.native, "files": [{"name": "Items.json"}]}
        write_json(
            self.folder / "translated/Items.json", [{"name": "Manual game edit"}]
        )
        self.assertEqual(self.guided.applied_outputs(native)[1], ["Items.json"])
        self.native["engine"] = native["engine"] = "ACE"
        self.backend.guided_ace_blocked = lambda _source: "Reads Game.rgss3a."
        self.assertEqual(self.guided.run_view(identity)["appliedOutputs"], [])
        self.assertEqual(self.guided.applied_outputs(native)[1], [])
        self.native["engine"] = "MVMZ"
        # Another output applied over it does replace it.
        write_json(
            self.folder / "applied-outputs.json",
            {"files": {"Items.json": digest(b"another output")}},
        )
        self.assertEqual(self.guided.run_view(identity)["appliedOutputs"], [])
        self.backend.saved_run_configuration = lambda _: plan
        write_json(
            self.backend.manual.folder(identity) / "translated/Items.json",
            [{"name": "Changed output"}],
        )
        self.assertFalse(
            self.guided.runs.snapshot(self.identity, self.native, {"changed": []})[
                "phase_runs"
            ]["database"]["scopeComplete"]
        )
        self.assertEqual(self.guided.run_view(identity)["availableOutputs"], [])

    def test_legacy_history_preserves_ownership_receipts_and_never_revives_old_work(
        self,
    ):
        # Protect stale native pointers, updated timestamps and exact-scope
        # fallback from promoting old failures. Legacy dismissal preferences
        # must not hide saved ownership or settle overlapping paid requests.
        from dazedtl.translation.guided_runs import GuidedRuns

        inputs = self.guided.runs.inputs(
            self.identity, self.native, "database", "batch"
        )
        old = {
            "id": "old",
            "created": "2020-01-01",
            "updated": "2030-01-01",
            "mode": "batch",
            "status": "interrupted",
            "files": ["Items.json"],
            "log": [],
            "dazedtl_submission_intent": True,
        }
        new = {
            **old,
            "id": "new",
            "created": "2026-01-01",
            "mode": "estimate",
            "status": "complete",
        }
        for job in (old, new):
            self.backend.manual.jobs[job["id"]] = job
            self.guided.runs.remember(self.identity, job, inputs)
            write_json(
                self.backend.manual.folder(job["id"])
                / (
                    "log/estimate_requests.json"
                    if job["mode"] == "estimate"
                    else "log/batch_requests.json"
                ),
                {
                    "request": {
                        "payload": '{"Line1":"薬"}',
                        "params": {},
                        "provider": "openai",
                    }
                },
            )
        self.native["manual_job"] = "old"
        self.assertEqual(self.guided.owned_runs(self.native)[:2], ["new", "old"])
        self.assertNotIn(
            "database",
            self.guided.runs.snapshot(self.identity, self.native, {"changed": []})[
                "phase_runs"
            ],
        )
        roots = [self.backend.manual.folder(identity) for identity in ("old", "new")]
        before = {
            path: path.read_bytes()
            for root in roots
            for path in root.rglob("*")
            if path.is_file()
        }
        self.native["kept_failed_runs"] = {"old": {"dismissed": True}}
        native = self.backend.workflows.projects["native"]
        self.assertIn("old", self.guided.owned_runs(native))
        overlaps = self.guided.submission_overlap(native, {"jobId": "new"})
        self.assertEqual(overlaps[0]["files"], ["Items.json"])
        self.assertEqual(overlaps[0]["run"], "old")
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        old["status"] = "running"
        views = [self.guided.run_view(identity) for identity in ("new", "old")]
        self.assertEqual(GuidedRuns.current(views, "database")["id"], "old")
        old["status"] = "failed"
        new.update(mode="batch", files=["Actors.json"])
        self.assertNotIn(
            "database",
            self.guided.runs.snapshot(self.identity, native, {"changed": []})[
                "phase_runs"
            ],
        )
        self.assertEqual(
            GuidedRuns.current([self.guided.run_view("old")], "database")["id"], "old"
        )
        # Legacy history keys still discover runs after old pointers disappear.
        self.guided.path(self.identity, "runs").unlink()
        native["manual_job"] = None
        self.assertIn("old", self.guided.owned_runs(native))
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_comparisons_require_exact_usable_mappings_for_the_selected_event_scope(
        self,
    ):
        self.backend.phase_files = lambda _native, phase: (
            ["Items.json"] if phase == "database" else ["Map001.json", "Map002.json"]
        )
        self.native["selected"] = ["Items.json", "Map001.json"]
        self.native["engine_options"] = {"IGNORETLTEXT": True}
        self.projects.get(self.identity)["phase"] = "variables"
        write_json(
            self.source / "Map001.json",
            {
                "list": [
                    {
                        "code": 111,
                        "parameters": [12, '$gameVariables.value(1) === "日本語"'],
                    }
                ]
            },
        )
        write_json(
            self.source / "Map002.json",
            {
                "list": [
                    {
                        "code": 111,
                        "parameters": [12, '$gameVariables.value(1) === "別の語"'],
                    }
                ]
            },
        )
        for mapping in ({}, {"日本語": "日本語"}, {"別の語": "Other fixture"}):
            write_json(self.folder / "log/var_translation_map.json", mapping)
            self.assertEqual(self.guided.runs.comparisons(self.native)["matches"], 0)
            with self.assertRaisesRegex(ValueError, "audited assignments"):
                self.guided.preview(
                    self.identity, "start", options={"mode": "estimate"}
                )
        write_json(
            self.folder / "log/var_translation_map.json", {"日本語": "Fixture English"}
        )
        comparisons = self.guided.runs.comparisons(self.native)
        self.assertEqual(comparisons["files"], ["Map001.json"])
        self.assertEqual(comparisons["status"], "review_needed")
        self.assertEqual(comparisons["rows"][0]["variables"], ["1"])
        with self.assertRaisesRegex(ValueError, "Review every matched"):
            self.guided.preview(self.identity, "start", options={"mode": "estimate"})
        self.guided.comparisons_review(self.identity, comparisons["fingerprint"], True)
        self.assertEqual(self.guided.runs.comparisons(self.native)["status"], "ready")
        self.seed_estimate("variables")
        preview = self.guided.preview(self.identity, "start", options={"mode": "batch"})
        write_json(
            self.folder / "log/var_translation_map.json", {"日本語": "Changed fixture"}
        )
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview["token"])
        self.assertEqual(self.started, [])
        write_json(self.folder / "log/var_translation_map.json", {"日本語": 7})
        self.assertEqual(
            self.guided.runs.comparisons(self.native)["status"], "recovery_needed"
        )
        write_json(self.folder / "log/var_translation_map.json", {})
        self.assertEqual(
            self.guided.runs.comparisons(self.native)["status"], "not_needed"
        )

        # Warm observations must follow changed working copies, selection and
        # skip-translated settings, even when parsed literals have been reused.
        write_json(
            self.folder / "log/var_translation_map.json",
            {
                "日本語": "Fixture English",
                "別の語": "Other fixture",
                "English": "Replacement",
            },
        )
        write_json(
            self.folder / "files/Map001.json",
            {
                "list": [
                    {
                        "code": 111,
                        "parameters": [12, '$gameVariables.value(2) === "別の語"'],
                    }
                ]
            },
        )
        changed = self.guided.runs.comparisons(self.native)
        self.assertNotEqual(changed["fingerprint"], comparisons["fingerprint"])
        self.assertEqual(changed["rows"][0]["variables"], ["2"])
        self.assertEqual(changed["rows"][0]["translation"], "Other fixture")
        write_json(
            self.folder / "files/Map001.json",
            {
                "list": [
                    {
                        "code": 111,
                        "parameters": [12, '$gameVariables.value(3) === "English"'],
                    }
                ]
            },
        )
        self.assertEqual(self.guided.runs.comparisons(self.native)["matches"], 0)
        self.native["engine_options"]["IGNORETLTEXT"] = False
        self.assertEqual(
            self.guided.runs.comparisons(self.native)["rows"][0]["variables"], ["3"]
        )
        self.native["selected"] = ["Map002.json"]
        self.assertEqual(
            self.guided.runs.comparisons(self.native)["files"], ["Map002.json"]
        )

    def test_apply_review_accepts_partial_output_despite_batches_and_keeps_its_selected_scope(
        self,
    ):
        write_json(self.source / "System.json", {"gameTitle": "Fixture"})
        self.native["selected"] = ["Items.json", "System.json"]
        self.backend.phase_files = lambda *_: ["Items.json", "System.json"]
        write_json(
            self.folder / "translated/Items.json",
            [{"name": "Fixture output", "description": "未翻訳"}],
        )
        write_json(
            self.folder / "translated/System.json", {"gameTitle": "Other output"}
        )
        self.backend.workflows.previews = {}
        self.backend.workflows.preview = lambda *_: {
            "token": "apply-preview",
            "confirmation": True,
            "options": {},
        }
        self.backend.guided_export_preview = Mock(
            side_effect=lambda _owner, paths: self.backend.workflows.preview()
        )
        # Pending or unresolved Batch receipts must not veto saved partial
        # output; Apply must leave their execution protections intact.
        old = {
            "id": "failed-batch",
            "mode": "batch",
            "status": "failed",
            "files": ["Items.json"],
            "log": [],
        }
        self.backend.manual.jobs[old["id"]] = old
        self.guided.runs.remember(
            self.identity,
            old,
            self.guided.runs.inputs(self.identity, self.native, "database", "batch"),
        )
        root = self.backend.manual.folder(old["id"])
        batch = {
            "id": "provider-batch",
            "status": "error",
            "api_status": "failed",
            "custom_ids": {"one": "key"},
            "request_counts": {
                "processing": 0,
                "succeeded": 0,
                "errored": 0,
                "canceled": 0,
                "expired": 0,
            },
        }
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        write_json(
            root / "log/batch_state.json", {"status": "submitted", "batches": [batch]}
        )
        write_json(
            root / "log/batch_requests.json",
            {"key": {"payload": '{"Line1":"薬"}', "params": {}}},
        )
        self.assertTrue(self.guided.run_view(old["id"])["process"]["retryBlocked"])
        retained = {
            path: path.read_bytes() for path in root.rglob("*") if path.is_file()
        }
        self.assertEqual(
            self.guided.preview(self.identity, "refresh_sources", files=["Items.json"])[
                "paths"
            ],
            ["Items.json"],
        )
        for status, counts in [
            ("in_progress", {"succeeded": 0}),
            ("failed", {}),
            ("failed", {"succeeded": 1}),
        ]:
            write_json(
                root / "log/batch_history.json",
                {
                    "batches": [
                        {**batch, "api_status": status, "request_counts": counts}
                    ]
                },
            )
            self.assertEqual(
                self.guided.preview(
                    self.identity, "export_selected", files=["Items.json"]
                )["paths"],
                ["Items.json"],
            )
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        self.guided.batch_monitor.busy.add(old["id"])
        old["status"] = "running"
        self.backend.running = lambda: True
        self.backend.guided_export_preview.reset_mock()
        preview = self.guided.preview(
            self.identity, "export_selected", files=["Items.json"]
        )
        self.assertEqual(preview["paths"], ["Items.json"])
        self.backend.guided_export_preview.assert_called_once_with(
            "native", ["Items.json"]
        )
        self.assertEqual(read_json(self.source / "Items.json"), [{"name": "薬"}])
        self.assertEqual(self.native["selected"], ["Items.json", "System.json"])
        # The active translation and collector cannot veto confirmation either.
        self.backend.workflows.execute = Mock(return_value={"id": "apply-operation"})
        self.assertEqual(
            self.guided.execute(self.identity, preview["token"]),
            {"id": "apply-operation"},
        )
        old["status"] = "failed"
        self.guided.batch_monitor.busy.clear()
        self.backend.running = lambda: False
        self.assertEqual({path: path.read_bytes() for path in retained}, retained)
        self.assertTrue(self.guided.run_view(old["id"])["process"]["retryBlocked"])
        with self.assertRaisesRegex(ValueError, "new preview"):
            self.guided.execute(self.identity, preview["token"])
        self.backend.workflows.execute.assert_called_once_with("apply-preview")
        # A runtime writer still blocks preview and consumes a failed confirmation.
        preview = self.guided.preview(
            self.identity, "export_selected", files=["Items.json"]
        )
        self.backend.operations.running = lambda: True
        with self.assertRaisesRegex(ValueError, "Finish or stop"):
            self.guided.preview(self.identity, "export_selected", files=["Items.json"])
        with self.assertRaisesRegex(ValueError, "Finish or stop"):
            self.guided.execute(self.identity, preview["token"])
        self.backend.operations.running = lambda: False
        with self.assertRaisesRegex(ValueError, "new preview"):
            self.guided.execute(self.identity, preview["token"])
        self.assertEqual(
            self.guided.preview(self.identity, "refresh_sources", files=["Items.json"])[
                "paths"
            ],
            ["Items.json"],
        )
        with self.assertRaises(ValueError):
            self.guided.preview(
                self.identity, "export_selected", files=["Foreign.json"]
            )
        # A file the game changed since its working copy, as after an update,
        # still holds the old release's text: Apply refuses it until a reload,
        # in its review and again when confirmed.
        preview = self.guided.preview(
            self.identity, "export_selected", files=["Items.json"]
        )
        with patch.object(
            GuidedInputs, "status", return_value={"changed": ["Items.json"]}
        ):
            for apply in (
                lambda: self.guided.preview(
                    self.identity, "export_selected", files=["Items.json"]
                ),
                lambda: self.guided.execute(self.identity, preview["token"]),
            ):
                with self.assertRaisesRegex(
                    ValueError, "Items.json changed in the game. Reload it"
                ):
                    apply()
        self.native["files"] = [{"name": "Items.json"}, {"name": "System.json"}]
        state = {"jobs": []}
        self.assertEqual(
            self.guided.readiness(self.identity, self.native, state)["unapplied"],
            ["Items.json", "System.json"],
        )
        with self.assertRaisesRegex(ValueError, "Apply the selected saved outputs"):
            self.guided.release_ready(self.identity, self.native, state)
        write_json(
            self.folder / "applied-outputs.json",
            {
                "files": {
                    "Items.json": digest(
                        (self.folder / "translated/Items.json").read_bytes()
                    )
                }
            },
        )
        self.native["selected"] = ["Items.json"]
        self.assertEqual(
            self.guided.readiness(self.identity, self.native, state)["unapplied"], []
        )
        self.assertIs(
            self.guided.release_ready(self.identity, self.native, state),
            self.translation.ready.return_value,
        )
        write_json(
            self.folder / "translated/Items.json", [{"name": "Newer saved output"}]
        )
        self.assertEqual(
            self.guided.readiness(self.identity, self.native, state)["unapplied"],
            ["Items.json"],
        )
        with self.assertRaisesRegex(ValueError, "Apply the selected saved outputs"):
            self.guided.release_ready(self.identity, self.native, state)

    def test_reapply_run_freezes_owned_history_outputs_without_using_current_selection(
        self,
    ):
        from types import ModuleType

        from dazedtl.compatibility.dazedmtl import ExistingBackend
        from dazedtl.compatibility.text import prepare_publication, run_publication
        from dazedtl.translation import publication

        # Reapplying must never substitute the newest working copy for a chosen
        # historical run, or publish files belonging to another project.
        identity = "old-batch"
        root = self.backend.manual.folder(identity)
        write_json(root / "translated/Items.json", [{"name": "Older wording"}])
        expected = digest((root / "translated/Items.json").read_bytes())
        job = {
            "id": identity,
            "mode": "batch",
            "status": "complete",
            "files": ["Items.json"],
            "outputs": {"Items.json": expected},
            "log": [],
        }
        self.backend.manual.jobs[identity] = job
        self.guided.runs.remember(
            self.identity,
            job,
            self.guided.runs.inputs(self.identity, self.native, "database", "batch"),
        )
        write_json(self.folder / "translated/Items.json", [{"name": "Newer wording"}])
        self.native["selected"] = []
        self.backend.workflows.previews = {}

        def preview(*_):
            token = "historical-preview"
            self.backend.workflows.previews[token] = {
                "project_id": "native",
                "project": self.native,
                "folder": str(self.folder),
                "action": "export_selected",
                "options": {},
                "guard": {"data": self.backend.guided_guard(self.native, self.folder)},
            }
            return {"token": token, "confirmation": True, "options": {}}

        self.backend.workflows.preview = preview
        self.backend.phase_files = lambda _native, phase: (
            ["Items.json"] if phase == "database" else ["Map001.json"]
        )
        self.backend.guided_export_preview = lambda *args, **kw: (
            ExistingBackend.guided_export_preview(self.backend, *args, **kw)
        )
        self.backend.guided_text_publication = lambda token: prepare_publication(
            self.backend.workflows.previews[token]
        )
        self.backend.workflows.execute = lambda token: run_publication(
            self.backend.workflows.previews.pop(token), lambda _: None
        )
        actions = ModuleType("desktop.backend.workflow_actions")
        actions.validate_plan = lambda _: None
        actions.action_guard = lambda *_: {
            "data": self.backend.guided_guard(self.native, self.folder)
        }
        with replaced_modules({"desktop.backend.workflow_actions": actions}):
            review = self.guided.preview(
                self.identity, "export_selected", options={"run_id": identity}
            )
            self.assertEqual(review["paths"], ["Items.json"])
            self.assertEqual(review["options"]["run_id"], identity)
            # History listed a run's first Apply as a reapply.
            self.assertEqual(review["label"], "Apply Database files")
            self.assertEqual(read_json(self.source / "Items.json"), [{"name": "薬"}])
            write_json(self.source / "Items.json", [{"name": "Edit after review"}])
            edited = (self.source / "Items.json").read_bytes()
            # Runtime edits are accepted by explicit overwrite, whose receipt
            # names the bytes it replaced.
            result = self.guided.execute(self.identity, review["token"])
            self.assertEqual(
                read_json(self.source / "Items.json"), [{"name": "Older wording"}]
            )
            self.assertEqual(
                read_json(self.folder / "translated/Items.json"),
                [{"name": "Newer wording"}],
            )
            [applied] = [
                row
                for row in publication.records(self.folder)
                if row["id"] == result["publication"]
            ]
            self.assertEqual(
                [row["before"] for row in applied["files"]],
                [publication.digest(edited)],
            )
            self.assertEqual(self.native["selected"], [])
            # Translate's Apply then publishes the newest copy, the one its
            # rows read, not the older run, and its review names the task
            # whose run saved that copy over this one's.
            newer = {
                "id": "event-text-run",
                "mode": "translate",
                "status": "complete",
                "files": ["Items.json"],
                "outputs": {
                    "Items.json": digest(
                        (self.folder / "translated/Items.json").read_bytes()
                    )
                },
                "log": [],
            }
            self.backend.manual.jobs[newer["id"]] = newer
            self.guided.runs.remember(self.identity, newer, {"phase": "advanced"})
            self.native["selected"] = ["Items.json"]
            latest = self.guided.preview(
                self.identity, "export_selected", files=["Items.json"]
            )
            self.assertEqual(
                [row.get("task") for row in latest["publication"]], ["advanced"]
            )
            self.guided.execute(self.identity, latest["token"])
            self.assertEqual(
                read_json(self.source / "Items.json"), [{"name": "Newer wording"}]
            )
            self.native["selected"] = []
            with self.assertRaises(ValueError):
                self.guided.execute(self.identity, review["token"])
            # That Apply published the newer run's output, so History's
            # Reapply of the run applies it again.
            write_json(
                self.backend.manual.folder(newer["id"]) / "translated/Items.json",
                [{"name": "Newer wording"}],
            )
            self.assertEqual(
                self.guided.preview(
                    self.identity, "export_selected", options={"run_id": newer["id"]}
                )["label"],
                "Reapply Database files",
            )
            # A later run that saved the copy unchanged added none of its text.
            unchanged = {**newer, "id": "unchanged-run", "created": "later"}
            self.backend.manual.jobs[unchanged["id"]] = unchanged
            self.guided.runs.remember(self.identity, unchanged, {"phase": "dialogue"})
            self.native["selected"] = ["Items.json"]
            self.assertEqual(
                self.guided.preview(
                    self.identity, "export_selected", files=["Items.json"]
                )["publication"][0].get("task"),
                "advanced",
            )
            self.native["selected"] = []
            for state in ("running", "failed", "stopped"):
                job["status"] = state
                with self.assertRaises(ValueError):
                    self.guided.preview(
                        self.identity, "export_selected", options={"run_id": identity}
                    )
            job["status"] = "complete"
            # A complete Live run's saved output reapplies like a Batch's.
            job["mode"] = "translate"
            again = self.guided.preview(
                self.identity, "export_selected", options={"run_id": identity}
            )
            self.assertEqual(
                (again["paths"], again["label"]),
                (["Items.json"], "Reapply Database files"),
            )
            job["mode"] = "batch"
            for files in (
                [],
                ["Foreign.json"],
                ["Items.json", "Items.json"],
                ["../Items.json"],
            ):
                with self.assertRaises(ValueError):
                    self.guided.preview(
                        self.identity,
                        "export_selected",
                        files=files,
                        options={"run_id": identity},
                    )
            with self.assertRaises(ValueError):
                self.guided.preview(
                    self.identity, "export_selected", options={"run_id": "foreign"}
                )
            self.backend.saved_run_configuration = lambda _: {
                "workflow": {"id": "foreign"}
            }
            with self.assertRaises(ValueError):
                self.guided.preview(
                    self.identity, "export_selected", options={"run_id": identity}
                )
            self.backend.saved_run_configuration = lambda _: {
                "workflow": {"id": "native"}
            }
            descriptor, _ = self.guided.saved_output(self.native, identity, None)
            write_json(
                root / "translated/Items.json", [{"name": "Tampered saved output"}]
            )
            # Recheck bytes at freeze, even if the observed availability was old.
            preview()
            self.backend.workflows.previews["historical-preview"].update(
                options={"files": ["Items.json"]}, run_output=descriptor
            )
            with self.assertRaisesRegex(ValueError, "changed"):
                prepare_publication(
                    self.backend.workflows.previews["historical-preview"]
                )
            with self.assertRaises(ValueError):
                self.guided.preview(
                    self.identity, "export_selected", options={"run_id": identity}
                )
            (root / "translated/Items.json").unlink()
            with self.assertRaises(ValueError):
                self.guided.preview(
                    self.identity, "export_selected", options={"run_id": identity}
                )
            # Ordinary Apply can publish mixed translated/untranslated JSON
            # while its Batch is running, without accepting malformed output.
            self.native["selected"] = ["Items.json"]
            job["status"] = "running"
            self.backend.running = lambda: True
            partial = [
                {
                    "name": "Medicine",
                    "description": "未翻訳",
                    "_original": {"name": "薬"},
                }
            ]
            write_json(self.folder / "translated/Items.json", partial)
            review = self.guided.preview(
                self.identity, "export_selected", files=["Items.json"]
            )
            self.guided.execute(self.identity, review["token"])
            self.assertEqual(read_json(self.source / "Items.json"), partial)
            self.assertEqual(job["status"], "running")
            (self.folder / "translated/Items.json").write_text(
                "{broken", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                self.guided.preview(
                    self.identity, "export_selected", files=["Items.json"]
                )
            self.assertEqual(read_json(self.source / "Items.json"), partial)

    def test_guidance_save_replaces_external_edits_and_retains_other_drafts(self):
        path = self.source / "glossary.txt"
        path.write_text("Changed outside the editor", encoding="utf-8")
        pending = {
            "documents": {
                "glossary": {"text": "My draft", "revision": "older"},
                "game": {"text": "Keep this draft", "revision": "other"},
            }
        }
        documents = lambda _: {
            "glossary": {
                "text": path.read_text(encoding="utf-8"),
                "revision": digest(path.read_bytes()),
                "path": str(path),
            },
            "quirks": {
                "text": quirks.read_text(encoding="utf-8") if quirks.exists() else "",
                "revision": "",
                "path": str(quirks),
            },
        }
        quirks = self.source / "quirks.md"
        self.backend.workflows.documents = documents
        self.backend.workflows.state = lambda _: {"draft": pending}
        self.backend.workflows.draft = Mock()
        summaries = []

        def write(source, native=None, **options):
            summaries.append(options["summary"])
            return game_write(source, native, **options)

        def save(owner, changes):
            self.assertEqual(owner, "native")
            self.assertEqual(changes["glossary"]["revision"], digest(path.read_bytes()))
            path.write_text(changes["glossary"]["text"], encoding="utf-8")
            if "quirks" in changes:
                quirks.write_text(changes["quirks"]["text"], encoding="utf-8")
            return documents(owner)

        # Save guidance sends every tab.
        def draft(text):
            return {
                "glossary": {"text": text, "revision": "older"},
                "quirks": {"text": "", "revision": ""},
            }

        self.backend.game_write = write
        self.backend.workflows.documents_save = save
        self.guided.save_documents(self.identity, draft("My draft"))
        self.assertEqual(path.read_text(encoding="utf-8"), "My draft")
        # A core tab the game has no file for is created, empty, so Guidance
        # is complete, but its checkpoint names only what was edited: it read
        # "Save Glossary, Style & quirks".
        self.assertEqual(quirks.read_text(encoding="utf-8"), "")
        self.assertEqual(summaries, ["Save Glossary"])
        self.assertEqual(set(pending["documents"]), {"game"})
        # A document whose file already holds its text writes nothing, so a
        # Save of untouched tabs makes no checkpoint.
        self.backend.workflows.documents_save = Mock()
        self.guided.save_documents(self.identity, draft("My draft"))
        self.backend.workflows.documents_save.assert_not_called()
        self.backend.workflows.documents_save = save
        self.guided.save_documents(self.identity, draft(""))
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_text(encoding="utf-8"), "")
        pending["documents"]["glossary"] = {
            "text": "Keep after failure",
            "revision": "older",
        }
        self.backend.workflows.documents_save = Mock(side_effect=OSError("No space"))
        with self.assertRaises(OSError):
            self.guided.save_documents(self.identity, draft("Keep after failure"))
        self.assertEqual(pending["documents"]["glossary"]["text"], "Keep after failure")
        self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_measured_layout_applies_once_and_preserves_active_work_and_width_edits(
        self,
    ):
        self.backend.workflows.documents = lambda _: {}
        request_path = self.guided.path(self.identity, "context-request")
        request = context_setup.request(
            request_path,
            self.identity,
            {"request_id": "speaker-task"},
            self.native["widths"],
        )
        source = self.source / "windows.js"
        source.write_text("Measured message window", encoding="utf-8")
        report = {
            "version": 1,
            "request_id": request["request_id"],
            "project_id": self.identity,
            "layout": {
                "widths": {
                    "width": 55,
                    "faceWidth": 40,
                    "listWidth": 80,
                    "noteWidth": 70,
                },
                "reason": "Measured fixture window.",
                "evidence": [
                    {
                        "file": "windows.js",
                        "sha256": digest(source.read_bytes()),
                        "location": "message width",
                    }
                ],
            },
        }

        def apply(identity, revision, receipt):
            self.assertEqual(identity, "native")
            before = deepcopy(self.native["widths"])
            next_revision = revision + int(before != receipt["widths"])
            self.native.update(
                widths=dict(receipt["widths"]),
                revision=next_revision,
                guided_layout={
                    **receipt,
                    "beforeWidths": before,
                    "beforeRevision": revision,
                    "revision": next_revision,
                },
            )
            return self.native

        self.backend.workflows.apply_layout_settings = Mock(side_effect=apply)
        write_json(
            self.source / context_setup.REPORT, {**report, "project_id": "another-game"}
        )
        self.assertIsNone(self.guided.context_status(self.identity)["layout"])
        self.backend.workflows.apply_layout_settings.assert_not_called()
        # A report that could not measure the windows finishes the task and
        # keeps the widths; another game's report says nothing.
        unmeasured = {**report, "layout": None}
        write_json(
            self.source / context_setup.REPORT,
            {**unmeasured, "project_id": "another-game"},
        )
        self.assertFalse(self.guided.context_status(self.identity)["layoutUnmeasured"])
        write_json(self.source / context_setup.REPORT, unmeasured)
        self.assertTrue(self.guided.context_status(self.identity)["layoutUnmeasured"])

        # A report the app cannot use says why, so the task is not left
        # waiting; an earlier request's report still says nothing.
        def rejected(value):
            write_json(self.source / context_setup.REPORT, value)
            return self.guided.context_status(self.identity)["layoutRejected"]

        self.assertIn(
            "reason", rejected({**report, "layout": {**report["layout"], "reason": ""}})
        )
        stale = deepcopy(report)
        stale["layout"]["evidence"][0]["sha256"] = "0" * 64
        self.assertIn("windows.js", rejected(stale))
        self.assertIn("request_id", rejected({**report, "request_id": "older-task"}))
        earlier = request_path.stat().st_mtime - 10
        os.utime(self.source / context_setup.REPORT, (earlier, earlier))
        self.assertEqual(
            self.guided.context_status(self.identity)["layoutRejected"], ""
        )
        self.backend.workflows.apply_layout_settings.assert_not_called()
        write_json(self.source / context_setup.REPORT, report)
        self.backend.running = lambda: True
        self.assertEqual(
            self.guided.context_status(self.identity)["layoutApplication"], "pending"
        )
        self.backend.running = lambda: False
        pending = self.edited(self.guided.preferences(self.native))
        self.guided.options_draft(self.identity, pending)
        self.assertEqual(
            self.guided.context_status(self.identity)["layoutApplication"], "pending"
        )
        self.backend.workflows.apply_layout_settings.assert_not_called()
        self.guided.options_draft(self.identity, None)
        self.backend.workflows.apply_layout_settings.side_effect = OSError(
            "Read-only fixture settings"
        )
        self.assertTrue(self.guided.context_status(self.identity)["layoutMessage"])
        self.assertNotIn("guided_layout", self.native)
        failed_calls = self.backend.workflows.apply_layout_settings.call_count
        self.assertTrue(self.guided.context_status(self.identity)["layoutMessage"])
        self.assertEqual(
            self.backend.workflows.apply_layout_settings.call_count, failed_calls
        )
        self.backend.workflows.apply_layout_settings.side_effect = apply
        self.assertEqual(
            self.guided.context_status(self.identity, retry_layout=True)[
                "layoutApplication"
            ],
            "applied",
        )
        self.assertEqual(self.native["widths"], report["layout"]["widths"])
        calls = self.backend.workflows.apply_layout_settings.call_count
        self.guided.context_status(self.identity)
        self.assertEqual(self.backend.workflows.apply_layout_settings.call_count, calls)
        # A delayed recovery write from before application adopts measured
        # widths, but a real width edit wins over the automatic update.
        pending["values"]["selected"] = []
        self.guided.options_draft(self.identity, pending)
        recovered = read_json(self.guided.path(self.identity, "draft"))
        self.assertEqual(recovered["values"]["widths"], report["layout"]["widths"])
        self.assertEqual(recovered["values"]["selected"], [])
        self.assertEqual(recovered["revision"], self.native["revision"])
        pending["values"]["widths"]["width"] = 90
        self.guided.options_draft(self.identity, pending)
        recovered = read_json(self.guided.path(self.identity, "draft"))
        self.assertEqual(recovered["values"]["widths"]["width"], 90)
        self.guided.options_draft(self.identity, None)
        self.native["widths"]["width"] = 90
        self.native["revision"] += 1
        report["layout"]["widths"]["width"] = 60
        write_json(self.source / context_setup.REPORT, report)
        self.assertEqual(
            self.guided.context_status(self.identity)["layoutApplication"], "manual"
        )
        self.assertEqual(self.native["widths"]["width"], 90)
        # Explicitly requesting a new measurement establishes a new baseline.
        renewed = context_setup.request(
            request_path,
            self.identity,
            {"request_id": "speaker-task"},
            self.native["widths"],
        )
        report["request_id"] = renewed["request_id"]
        write_json(self.source / context_setup.REPORT, report)
        self.assertEqual(
            self.guided.context_status(self.identity)["layoutApplication"], "applied"
        )
        self.assertEqual(self.native["widths"]["width"], 60)
        source.write_text("Later game change", encoding="utf-8")
        self.assertEqual(
            self.guided.context_status(self.identity)["layoutApplication"], "applied"
        )

    def test_reference_folders_need_no_game_format_and_stay_project_owned(self):
        import json

        from dazedtl.translation import reference_folders

        # The task text escapes the path: its quote here, or a Windows path's
        # backslashes, since Windows forbids quotes in names.
        folder = self.root / (
            "Earlier game with an unfamiliar format"
            if os.name == "nt"
            else 'Earlier "game" with an unfamiliar format'
        )
        folder.mkdir()
        (folder / "old-terms.txt").write_text("薬: Potion", encoding="utf-8")
        before = evidence(folder, ["old-terms.txt"])
        rows = self.guided.reference_add(self.identity, str(folder))
        self.assertTrue(rows[0]["available"])
        self.assertEqual(
            self.guided.reference_add(self.identity, str(folder / ".")), rows
        )
        reopened = Guided(self.backend, self.projects, self.settings, self.translation)
        self.assertEqual(
            reference_folders.describe(
                reopened.path(self.identity, "reference-folders")
            ),
            rows,
        )
        self.speaker_report()
        prompt = reopened.skill(self.identity, "setup")["text"]
        self.assertIn(json.dumps(str(folder)), prompt)
        self.assertNotIn("three passes", prompt)
        # The Thorough investigation choice reaches the copied task.
        reopened.form(
            self.identity,
            {**reopened.saved_form(self.identity), "thorough_investigation": True},
        )
        self.assertIn("three passes", reopened.skill(self.identity, "setup")["text"])
        self.assertEqual(evidence(folder, ["old-terms.txt"]), before)
        other_source = self.root / "other-game"
        other_source.mkdir()
        other = self.projects.open({"source": str(other_source), "engine": "MVMZ"})
        other["backend_id"] = "other-native"
        self.projects.save()
        self.backend.workflows.projects["other-native"] = {
            **self.native,
            "id": "other-native",
            "source": str(other_source),
        }
        with self.assertRaises(ValueError):
            reopened.reference_remove(other["id"], rows[0]["id"])
        self.assertEqual(
            reference_folders.describe(
                reopened.path(self.identity, "reference-folders")
            ),
            rows,
        )
        (folder / "old-terms.txt").unlink()
        folder.rmdir()
        self.assertFalse(
            reference_folders.describe(
                reopened.path(self.identity, "reference-folders")
            )[0]["available"]
        )
        self.assertIn(
            json.dumps(str(folder)), reopened.skill(self.identity, "setup")["text"]
        )
        self.assertEqual(reopened.reference_remove(self.identity, rows[0]["id"]), [])
        with self.assertRaises(ValueError):
            reopened.reference_add(self.identity, str(folder))
        with self.assertRaises(ValueError):
            reopened.reference_add(self.identity, str(self.source / "Items.json"))

    def test_document_selection_migrates_review_positions_and_stays_with_its_project(
        self,
    ):
        self.backend.workflows.documents = lambda _: {
            "glossary": {},
            "quirks": {},
            "game": {},
        }
        position = self.guided.path(self.identity, "position")
        selected = self.guided.path(self.identity, "context-document")
        write_json(position, {"step": "context", "task": "guidance"})
        self.guided.position(self.identity, "context", "guidance")
        self.assertEqual(read_json(selected), {"name": "quirks"})
        self.guided.position(self.identity, "context", "guidance", "game")
        self.guided.position(self.identity, "context", "speakers")
        self.assertEqual(read_json(selected), {"name": "game"})
        with self.assertRaises(ValueError):
            self.guided.position(
                self.identity, "context", "guidance", "foreign-document"
            )
        selected.unlink()
        write_json(position, {"step": "context", "task": "glossary"})
        self.guided.position(self.identity, "context", "guidance")
        self.assertEqual(read_json(selected), {"name": "glossary"})
        self.backend.workflows.state = lambda _: {
            "draft": {
                "documents": {
                    "custom:notes": {"text": "Retained draft", "revision": "previous"}
                }
            }
        }
        self.guided.position(self.identity, "context", "guidance", "custom:notes")
        self.assertEqual(read_json(selected), {"name": "custom:notes"})
        recovered = context_setup.retained_documents(
            self.source, {}, {"custom:notes": {}}
        )
        self.assertEqual(recovered["custom:notes"]["revision"], digest(b""))
        self.assertEqual(recovered["custom:notes"]["text"], "")
        other = self.projects.open(
            {"source": str(self.root / "other-game"), "engine": "MVMZ"}
        )
        self.assertFalse(self.guided.path(other["id"], "context-document").exists())

    def seed_estimate(self, phase=None, mode="batch"):
        phase = phase or self.projects.get(self.identity)["phase"]
        identity = "estimate-" + str(len(self.guided.runs.records(self.identity)))
        job = {
            "id": identity,
            "mode": "estimate",
            "status": "complete",
            "model": "fixture-model",
            "log": [],
            "files": self.guided.runs.files(self.native, phase),
            "estimate": {
                "requests": 1,
                "provider": "custom",
                "input_tokens": 4000,
                "output_tokens": 3000,
                "live_cost": 0.01,
                "batch_cost": 0.005,
            },
            "outputs": {},
        }
        self.backend.manual.jobs[identity] = job
        self.native.setdefault("collected", []).append(identity)
        self.guided.runs.remember(
            self.identity,
            job,
            self.guided.runs.inputs(self.identity, self.native, phase, mode),
        )
        return identity

    def preview(self):
        self.seed_estimate()
        return self.guided.preview(self.identity, "start", options={"mode": "batch"})

    @staticmethod
    def edited(preferences):
        """An options draft with an unsaved edit."""
        values = preferences["values"]
        return {
            **preferences,
            "values": {**values, "phase1_comments": not values["phase1_comments"]},
        }

    def speaker_report(self):
        schema = [
            {"key": key, "label": key, "type": "boolean"}
            for key in speaker_setup.KEYS[1:5]
        ]
        self.backend.workflows.state = lambda _: {
            "project": self.native,
            "manual_job": self.pending,
            "engine_schema": schema,
        }
        self.backend.workflows.skill = lambda *_, thorough: (
            "Investigate this game in three passes."
            if thorough
            else "Investigate this game."
        )

        def apply(_identity, revision, options, key, receipt):
            self.assertEqual(
                (revision, key), (self.native["revision"], "guided_speakers")
            )
            self.native.update(
                engine_options=options, guided_speakers=receipt, revision=revision + 1
            )
            return self.native

        self.backend.workflows.apply_investigation_settings = Mock(side_effect=apply)
        self.guided.skill(self.identity, "setup")
        request = read_json(self.guided.path(self.identity, "speaker-request"))
        report = {
            key: request[key]
            for key in ("version", "request_id", "project_id", "engine")
        }
        report["rules"] = {
            field["key"]: {
                "decision": "skip",
                "confidence": "high",
                "reason": "No supported pattern in the inspected corpus.",
                "evidence": [
                    {
                        "file": "Items.json",
                        "sha256": evidence(self.source, ["Items.json"])["Items.json"],
                        "location": "item 0, name",
                    }
                ],
            }
            for field in schema
        }
        return report

    def test_speaker_findings_require_current_complete_evidence_and_never_start_paid_work(
        self,
    ):
        report = self.speaker_report()
        path = self.source / speaker_setup.REPORT
        self.assertEqual(
            self.guided.speaker_findings(self.identity)["status"], "waiting"
        )
        self.guided.skill(self.identity, "setup")
        self.assertEqual(
            read_json(self.guided.path(self.identity, "speaker-request"))["request_id"],
            report["request_id"],
        )
        with self.assertRaises(ValueError):
            self.guided.speakers(self.identity, scan=True)
        for change, status in (
            ("owner", "waiting"),
            ("request", "waiting"),
            ("missing", "invalid"),
            ("unknown", "invalid"),
            ("evidence", "invalid"),
            ("stale", "stale"),
            ("escape", "invalid"),
        ):
            value = deepcopy(report)
            rule = value["rules"]["INLINE401SPEAKERS"]
            if change == "owner":
                value["project_id"] = "other-game"
            if change == "request":
                value["request_id"] = "older-task"
            if change == "missing":
                value["rules"].pop("FACENAME101")
            if change == "unknown":
                value["rules"]["CODE122"] = deepcopy(rule)
            if change == "evidence":
                rule["evidence"] = []
            if change == "stale":
                rule["evidence"][0]["sha256"] = "0" * 64
            if change == "escape":
                rule["evidence"][0]["file"] = "../Items.json"
            write_json(path, value)
            with self.subTest(change=change):
                self.assertEqual(
                    self.guided.speaker_findings(self.identity)["status"], status
                )
                with self.assertRaises(ValueError):
                    self.guided.apply_speakers(
                        self.identity, self.native["revision"], digest(value)
                    )
        self.backend.workflows.apply_investigation_settings.assert_not_called()
        report["rules"]["INLINE401SPEAKERS"].update(
            decision="enable", confidence="high"
        )
        report["rules"]["FIRSTLINESPEAKERS"].update(
            decision="enable", confidence="medium"
        )
        write_json(path, report)
        draft = self.edited(self.guided.preferences(self.native))
        self.guided.options_draft(self.identity, draft)
        with self.assertRaises(ValueError):
            self.guided.apply_speakers(self.identity, 0, digest(report))
        self.guided.options_draft(self.identity, None)
        self.backend.running = lambda: True
        with self.assertRaises(ValueError):
            self.guided.apply_speakers(self.identity, 0, digest(report))
        self.backend.running = lambda: False
        saved = self.guided.apply_speakers(self.identity, 0, digest(report))
        self.assertTrue(saved["values"]["engine_options"]["INLINE401SPEAKERS"])
        self.assertFalse(saved["values"]["engine_options"]["FIRSTLINESPEAKERS"])
        self.assertEqual(
            self.guided.speaker_findings(self.identity)["status"], "applied"
        )
        self.guided.skill(self.identity, "setup")
        self.assertEqual(
            self.guided.speaker_findings(self.identity)["status"], "applied"
        )
        report["request_id"] = read_json(
            self.guided.path(self.identity, "speaker-request")
        )["request_id"]
        self.assertEqual(self.started, [])
        self.assertTrue(
            self.guided.preview(self.identity, "start", options={"mode": "speakers"})[
                "confirmation"
            ]
        )
        # An amended finding can turn off an earlier automatic recommendation;
        # its earlier application must not be misidentified as a manual edit.
        report["rules"]["INLINE401SPEAKERS"]["decision"] = "skip"
        write_json(path, report)
        self.guided.apply_speakers(self.identity, 1, digest(report))
        self.assertFalse(self.native["engine_options"]["INLINE401SPEAKERS"])
        self.assertEqual(self.guided.speaker_findings(self.identity)["overrides"], [])

    def test_local_speaker_scan_keeps_project_ownership_and_reuses_only_current_results(
        self,
    ):
        report = self.speaker_report()
        write_json(self.source / speaker_setup.REPORT, report)
        # A dormant API run must neither block this local task nor be resumed,
        # canceled, or detached by applying rules and scanning new names.
        self.pending = {
            "id": "saved-api-run",
            "mode": "batch",
            "status": "interrupted",
            "provider_job": "retained-provider-job",
            "approval": {"token": "retained-approval"},
        }
        self.native["manual_job"] = self.pending["id"]
        preserved = deepcopy(self.pending)

        def start(plan):
            self.assertEqual(plan["project_id"], "native")
            self.assertEqual(plan["options"]["files"], ["Items.json"])
            result = {
                "names": ["リーナ", "\\N[1]"],
                "files": 1,
                "source_inputs": evidence(self.source, ["Items.json"]),
                "configuration": plan["options"]["configuration"],
                "reportId": plan["options"]["reportId"],
            }
            artifact = self.source / ".dazedtl/guided/speakers.json"
            write_json(artifact, result)
            result["artifact_sha256"] = digest(artifact.read_bytes())
            self.backend.operations.jobs["scan"] = {
                "id": "scan",
                "action": "speaker_scan",
                "project_id": "native",
                "created": "2026-01-01",
                "status": "complete",
                "result": result,
                "message": "Scanned",
                "log": [],
            }

        self.backend.operations.start.side_effect = start
        self.backend.running = lambda: True
        with self.assertRaises(ValueError):
            self.guided.speakers(self.identity, scan=True)
        self.backend.operations.start.assert_not_called()
        self.backend.running = lambda: False
        value = self.guided.speakers(self.identity, scan=True)
        self.assertTrue(value["current"])
        self.assertTrue(value["available"])
        self.assertEqual(value["names"], ["リーナ", "\\N[1]"])
        # A scan saved before the header check has nothing to review.
        with self.assertRaisesRegex(ValueError, "did not check headers"):
            self.guided.speakers(self.identity, fix_headers=True)
        self.guided.speakers(self.identity, scan=True)
        self.assertEqual(self.backend.operations.start.call_count, 1)
        self.assertEqual(self.started, [])
        self.assertEqual(self.pending, preserved)
        self.assertEqual(self.native["manual_job"], preserved["id"])
        self.assertTrue(self.preview()["confirmation"])
        other = self.projects.open({"source": str(self.root), "engine": "MVMZ"})
        with self.assertRaises(ValueError):
            self.guided.speakers(other["id"], scan=True)
        self.native["engine_options"]["FIRSTLINESPEAKERS"] = True
        saved = self.guided.speakers(self.identity)
        self.assertFalse(saved["current"])
        self.assertTrue(saved["available"])
        self.assertEqual(saved["names"], value["names"])
        self.native["engine_options"]["FIRSTLINESPEAKERS"] = False
        attempt = {
            "id": "new-scan",
            "action": "speaker_scan",
            "project_id": "native",
            "created": "2026-01-02",
            "status": "running",
        }
        self.backend.operations.jobs["new-scan"] = attempt
        for status in ("running", "failed"):
            attempt["status"] = status
            saved = self.guided.speakers(self.identity)
            self.assertTrue(saved["available"])
            self.assertFalse(saved["current"])
            self.assertEqual(saved["names"], value["names"])
            self.assertEqual(saved["job"]["id"], "new-scan")
        del self.backend.operations.jobs["new-scan"]
        artifact = self.source / ".dazedtl/guided/speakers.json"
        artifact.unlink()
        missing = self.guided.speakers(self.identity)
        self.assertFalse(missing["current"])
        self.assertFalse(missing["available"])
        self.assertEqual(missing["names"], [])
        self.assertTrue(missing["issue"])
        self.guided.speakers(self.identity, scan=True)
        write_json(self.source / "NewPluginData.JSON", {"events": []})
        self.assertFalse(self.guided.speakers(self.identity)["current"])
        (self.source / "NewPluginData.JSON").unlink()
        write_json(self.source / "Items.json", [{"name": "changed"}])
        stale = self.guided.speakers(self.identity)
        self.assertFalse(stale["current"])
        # The setup task rewrote valid findings when it could not see why a
        # scan went stale; the status names the changed file instead.
        self.assertIn("Items.json", stale["issue"])

    def test_speaker_application_preserves_overrides_and_recovered_preferences_across_new_findings(
        self,
    ):
        report = self.speaker_report()
        report["rules"]["INLINE401SPEAKERS"].update(
            decision="enable", confidence="high"
        )
        write_json(self.source / speaker_setup.REPORT, report)
        # An edit made after copying setup belongs to the user, including an enable.
        self.native["engine_options"]["FACENAME101"] = True
        self.guided.apply_speakers(self.identity, 0, digest(report))
        self.assertTrue(self.native["engine_options"]["FACENAME101"])
        self.native["engine_options"]["INLINE401SPEAKERS"] = False
        # Repeated observation/application cannot reset a subsequent manual edit.
        self.guided.apply_speakers(self.identity, 1, digest(report))
        self.assertFalse(self.native["engine_options"]["INLINE401SPEAKERS"])
        self.assertEqual(
            self.backend.workflows.apply_investigation_settings.call_count, 1
        )
        report = self.speaker_report()
        report["rules"]["INLINE401SPEAKERS"].update(
            decision="enable", confidence="high"
        )
        write_json(self.source / speaker_setup.REPORT, report)
        self.guided.apply_speakers(self.identity, 1, digest(report))
        self.assertFalse(self.native["engine_options"]["INLINE401SPEAKERS"])
        self.assertTrue(self.native["engine_options"]["FACENAME101"])
        self.guided.apply_speakers(self.identity, 2, digest(report), reset=True)
        self.assertTrue(self.native["engine_options"]["INLINE401SPEAKERS"])
        self.assertFalse(self.native["engine_options"]["FACENAME101"])
        # Translation can subsequently alter runtime files without erasing the finding.
        write_json(self.source / "Items.json", [{"name": "Medicine"}])
        self.assertEqual(
            self.guided.speaker_findings(self.identity)["status"], "applied"
        )
        self.assertEqual(self.started, [])

    def test_existing_forms_gain_release_defaults_without_rewriting_user_values(self):
        previous = {
            "version": "1.00",
            "original": "/original",
            "untranslated": False,
        }
        path = self.guided.path(self.identity, "form")
        # A form from before fitting became automatic still holds the line
        # width check's settings, which load without them.
        write_json(
            path,
            {
                **previous,
                "only_overflow": False,
                "text": {
                    "view": "fitting",
                    "categories": ["dialogue"],
                    "codes": "401",
                    "max_rows": 4,
                    "protect_rows": True,
                    "focus": "release",
                    "findings": [],
                },
            },
        )
        raw = path.read_bytes()
        value = self.guided.saved_form(self.identity)
        self.assertEqual({key: value[key] for key in previous}, previous)
        self.assertNotIn("only_overflow", value)
        self.assertNotIn("categories", value["text"])
        self.assertEqual(value["release"]["kind"], "game")
        self.assertEqual(path.read_bytes(), raw)
        value["release"]["tools"]["forgeHotkey"] = "F8"
        self.guided.form(self.identity, value)
        self.assertEqual(self.guided.saved_form(self.identity), value)
        write_json(path, {**value, "release": None})
        invalid = path.read_bytes()
        with self.assertRaises(ValueError):
            self.guided.saved_form(self.identity)
        self.assertEqual(path.read_bytes(), invalid)

    def test_submission_preview_rejects_other_owner_changed_inputs_and_repeated_use(
        self,
    ):
        preview = self.preview()
        self.assertTrue(preview["confirmation"])
        other = self.projects.open({"source": str(self.root), "engine": "MVMZ"})
        with self.assertRaises(ValueError):
            self.guided.execute(other["id"], preview["token"])
        self.assertEqual(self.started, [])
        # Switching the visible project never retargets an existing approval.
        result = self.guided.execute(self.identity, preview["token"])
        self.assertEqual(result["id"], "paid-run")
        self.assertEqual(self.started, [("native", "database", True)])
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview["token"])
        for mutate in (
            lambda: write_json(self.source / "Items.json", [{"name": "別"}]),
            lambda: setattr(self, "settings_revision", 2),
            lambda: self.native.update(revision=self.native["revision"] + 1),
            lambda: self.projects.get(self.identity).update(phase="dialogue"),
        ):
            with self.subTest(mutate=mutate):
                preview = self.preview()
                mutate()
                with self.assertRaises(ValueError):
                    self.guided.execute(self.identity, preview["token"])
                write_json(self.source / "Items.json", [{"name": "薬"}])
        self.assertEqual(len(self.started), 1)
        self.native["manual_job"] = "paid-run"
        self.backend.manual = SimpleNamespace(
            export=Mock(return_value={"path": "saved-output"})
        )
        self.backend.saved_run_configuration = lambda _: {"workflow": {"id": "native"}}
        with self.assertRaises(ValueError):
            self.guided.export(self.identity, "other-project-run")
        self.backend.manual.export.assert_not_called()
        self.guided.export(self.identity, "paid-run")
        self.backend.manual.export.assert_called_once_with("paid-run")
        self.backend.saved_run_configuration = lambda _: {
            "workflow": {"id": "other-project"}
        }
        with self.assertRaises(ValueError):
            self.guided.export(self.identity, "paid-run")
        self.assertEqual(self.backend.manual.export.call_count, 1)

    def test_agent_modes_and_unsaved_drafts_cannot_start(self):
        for mode in ("agent", "offline", "live", "unknown"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.guided.preview(self.identity, "start", options={"mode": mode})
        with self.assertRaises(ValueError):
            self.guided.preview(self.identity, "import", files=["Unsupported.json"])
        preferences = self.guided.preferences(self.native)
        # Choosing the method already saved leaves no edit to hold work up.
        self.guided.options_draft(self.identity, preferences)
        self.assertIsNotNone(self.preview()["token"])
        self.guided.options_draft(self.identity, self.edited(preferences))
        with self.assertRaises(ValueError):
            self.preview()
        self.guided.save_options(
            self.identity, preferences["revision"], preferences["values"]
        )
        self.assertIsNotNone(self.preview()["token"])
        self.assertEqual(self.started, [])

    def test_temporary_preparation_rechecks_inputs_and_fresh_translate_discards_only_unapproved_work(
        self,
    ):
        # A file edit while the review is open must not send the stale payload;
        # a new Translate must replace preparation without touching paid runs.
        inputs = self.guided.runs.inputs(
            self.identity, self.native, "database", "batch"
        )
        pending = {
            "id": "temporary",
            "mode": "batch",
            "status": "waiting",
            "dazedtl_preapproval": True,
            "files": ["Items.json"],
            "approval": {"token": "pending", "kind": "batch", "detail": {}},
            "log": [],
        }
        self.backend.manual.jobs[pending["id"]] = pending
        self.guided.runs.remember(self.identity, pending, inputs)
        self.backend.manual.answer = Mock(return_value=pending)
        self.backend.manual.save = Mock()
        for invalid in ("true", 1, None):
            with self.assertRaises(ValueError):
                self.guided.answer(self.identity, "pending", invalid)
        self.assertNotIn("dazedtl_submission_intent", pending)
        write_json(self.folder / "files/Items.json", [{"name": "Changed working text"}])
        with self.assertRaisesRegex(ValueError, "fresh estimate"):
            self.guided.answer(self.identity, "pending", True)
        self.backend.manual.answer.assert_not_called()
        self.assertNotIn("dazedtl_submission_intent", pending)
        pending["status"] = "stopped"
        with self.assertRaisesRegex(ValueError, "cannot be resumed"):
            self.guided.resume(self.identity, pending["id"])
        pending["status"] = "waiting"
        self.assertEqual(self.guided.run_view(pending["id"])["availableOutputs"], [])
        paid = {
            **pending,
            "id": "approved",
            "status": "complete",
            "approval": None,
            "dazedtl_approved": True,
        }
        self.backend.manual.jobs[paid["id"]] = paid
        self.guided.runs.remember(self.identity, paid, inputs)
        # An update that changes what a run sends (RUN_VERSION) leaves approved
        # work alone: a stopped approved Live run resumes from its own frozen
        # plan, with no new approval.
        from dazedtl.translation import guided_runs

        resumable = {**paid, "id": "approved-live", "mode": "translate"}
        resumable["status"] = "stopped"
        self.backend.manual.jobs[resumable["id"]] = resumable
        self.guided.runs.remember(self.identity, resumable, inputs)
        self.backend.saved_run_configuration = Mock(
            return_value={"workflow": {"id": self.native["id"]}}
        )
        self.guided.settings.prepare_engine = Mock()
        self.backend.manual.resume = Mock(return_value=resumable)
        with patch.object(guided_runs, "RUN_VERSION", guided_runs.RUN_VERSION + 1):
            self.assertIs(self.guided.resume(self.identity, "approved-live"), resumable)
        self.backend.manual.resume.assert_called_once_with("approved-live")
        self.backend.manual.jobs.pop(resumable["id"])
        discarded = []

        def discard(identity):
            discarded.append(identity)
            self.backend.manual.jobs.pop(identity)

        self.backend.manual.discard_preparation = discard
        with self.assertRaises(ValueError):
            self.guided.discard_preparation(self.identity, "foreign-run")
        new = {
            "id": "new-estimate",
            "mode": "estimate",
            "status": "running",
            "dazedtl_preapproval": True,
            "log": [],
        }

        counted = []

        def start(*_args):
            self.assertTrue(self.backend.manual.temporary_preparation)
            counted.append(self.backend.manual.claude_count)
            self.backend.manual.jobs[new["id"]] = new
            return new

        self.backend.guided_phase = start
        fresh = self.guided.runs.inputs(self.identity, self.native, "database", "batch")
        self.assertNotEqual(inputs["fingerprint"], fresh["fingerprint"])
        self.guided.actions._start(
            self.identity, "estimate", "database", ["Items.json"], fresh
        )
        self.assertEqual(discarded, ["temporary"])
        self.assertIn("approved", self.backend.manual.jobs)
        self.assertFalse(self.backend.manual.temporary_preparation)
        self.assertEqual(
            self.guided.runs.records(self.identity)["new-estimate"]["fingerprint"],
            fresh["fingerprint"],
        )
        # A Live review shows its estimate's Claude count; a Batch preparation
        # counts the requests it submits, so its estimate leaves the count out.
        live = self.guided.runs.inputs(
            self.identity, self.native, "database", "translate"
        )
        self.guided.actions._start(
            self.identity, "estimate", "database", ["Items.json"], live
        )
        self.assertEqual(counted, [False, True])
        self.assertTrue(self.backend.manual.claude_count)

    def test_batch_observations_cannot_revive_terminal_receipts_or_replace_worker_activity(
        self,
    ):
        job = {
            "id": "paid-batch",
            "mode": "batch",
            "status": "stopped",
            "phase": "poll_status",
            "files": ["Items.json"],
            "log": [],
        }
        self.backend.manual.jobs[job["id"]] = job
        self.guided.runs.remember(
            self.identity,
            job,
            self.guided.runs.inputs(self.identity, self.native, "database", "batch"),
        )
        root = self.backend.manual.folder(job["id"])
        batch = {
            "id": "provider-batch",
            "provider": "openai",
            "custom_ids": {"one": "key"},
            "api_status": "in_progress",
            "request_counts": {"succeeded": 0, "processing": 1},
        }
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        self.guided.batch_monitor.views[job["id"]] = {
            "state": "monitoring",
            "phase": "poll_status",
            "message": "",
            "batches": [
                {
                    "id": batch["id"],
                    "status": "in_progress",
                    "counts": {"succeeded": 0, "processing": 1},
                }
            ],
        }
        with self.guided.observations.read():
            observed = self.guided.run_view(job["id"])
        self.assertEqual(observed["status"], "running")
        # The monitor's phase is the run's; its public view keeps the contract.
        from dazedtl.api.contracts.runs import BatchMonitoring

        self.assertLessEqual(
            set(observed["process"]["monitoring"]), set(BatchMonitoring.__annotations__)
        )
        # A newer saved receipt must survive an older monitor observation,
        # including its counts and the run's inactive state on every refresh.
        batch.update(
            api_status="completed", request_counts={"succeeded": 1, "processing": 0}
        )
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        for _ in range(2):
            with self.guided.observations.read():
                observed = self.guided.run_view(job["id"])
            self.assertEqual(observed["status"], "stopped")
            self.assertNotIn("monitoring", observed["process"])
            self.assertEqual(observed["process"]["batches"][0]["status"], "completed")
            self.assertEqual(
                observed["process"]["batches"][0]["counts"], batch["request_counts"]
            )
        # Real collection remains active, but a late monitor view cannot
        # replace a resumed worker's consume phase or a completed run.
        self.guided.batch_monitor.views[job["id"]]["state"] = "collecting"
        self.assertEqual(self.guided.run_view(job["id"])["status"], "running")
        for status in ("running", "waiting", "complete"):
            job.update(status=status, phase="consume")
            observed = self.guided.run_view(job["id"])
            self.assertEqual(
                (observed["status"], observed["phase"]), (status, "consume")
            )
            self.assertNotIn("monitoring", observed["process"])

    def test_batch_controls_bind_project_review_and_recover_only_through_fetched_state(
        self,
    ):
        from dazedtl.compatibility import batch_control

        job = {
            "id": "paid-batch",
            "mode": "batch",
            "status": "running",
            "files": ["Items.json"],
            "log": [],
        }
        self.backend.manual.jobs[job["id"]] = job
        self.guided.runs.remember(
            self.identity,
            job,
            self.guided.runs.inputs(self.identity, self.native, "database", "batch"),
        )
        self.backend.allow_providers = True
        self.backend.manual.save = Mock()
        self.backend.manual.controller = Mock(
            return_value=SimpleNamespace(running=lambda: False)
        )
        self.settings.batch_connection = Mock(
            return_value={
                "secret": "fixture",
                "endpoint": "https://fixture.invalid",
                "organization": "",
            }
        )
        root = self.backend.manual.folder(job["id"])
        batch = {
            "id": "provider-batch",
            "provider": "openai",
            "custom_ids": {"one": "key"},
        }
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        write_json(
            root / "log/batch_state.json", {"status": "submitted", "batches": [batch]}
        )
        write_json(
            root / "log/batch_requests.json",
            {"key": {"payload": '{"Line1":"薬"}', "params": {}}},
        )
        job["status"], job["phase"] = "stopped", "poll_status"
        # The app's restored monitor is current activity even though the saved
        # native worker remains stopped and cannot be resumed to send work.
        self.guided.batch_monitor.views[job["id"]] = {
            "state": "monitoring",
            "message": "",
        }
        from dazedtl.api.views import job as public_job

        observed = public_job(self.guided.run_view(job["id"]))
        self.assertEqual(observed["status"], "running")
        self.assertEqual(observed["workerStatus"], "stopped")
        self.assertEqual(job["status"], "stopped")
        self.guided.batch_monitor.views.clear()
        # Reload is repeatable even while a saved Batch is running, collecting,
        # or awaiting reconciliation. It never mutates that run's receipts.
        retained = {
            path: path.read_bytes() for path in root.rglob("*") if path.is_file()
        }
        self.backend.guided_refresh = lambda native, files, sources: self.guided.inputs(
            native
        ).prepare(files, refresh=True, expected=sources)
        self.backend.running = lambda: True
        self.guided.batch_monitor.busy.add(job["id"])
        self.pending = job
        archives = set()
        for status in ["stopped", "failed", "running", "waiting", "complete"]:
            job["status"] = status
            review = self.guided.preview(
                self.identity, "refresh_sources", files=["Items.json"]
            )
            self.assertEqual(review["paths"], ["Items.json"])
            self.assertTrue(review["confirmation"])
            result = self.guided.execute(self.identity, review["token"])
            archives.add(result["archive"])
            self.assertEqual(
                (self.folder / "files/Items.json").read_bytes(),
                (self.source / "Items.json").read_bytes(),
            )
            with self.assertRaisesRegex(ValueError, "new preview"):
                self.guided.execute(self.identity, review["token"])
        self.assertEqual(len(archives), 5)
        self.assertEqual({path: path.read_bytes() for path in retained}, retained)
        # Only writers block the action; a failed confirmation is still one-use.
        review = self.guided.preview(
            self.identity, "refresh_sources", files=["Items.json"]
        )
        self.backend.operations.running = lambda: True
        with self.assertRaisesRegex(ValueError, "Finish or stop"):
            self.guided.preview(self.identity, "refresh_sources", files=["Items.json"])
        with self.assertRaisesRegex(ValueError, "Finish or stop"):
            self.guided.execute(self.identity, review["token"])
        self.backend.operations.running = lambda: False
        with self.assertRaisesRegex(ValueError, "new preview"):
            self.guided.execute(self.identity, review["token"])
        self.backend.operations.jobs["reload"] = {
            "project_id": "native",
            "action": "refresh_sources",
            "status": "running",
        }
        with self.assertRaisesRegex(ValueError, "finish resyncing"):
            self.guided.actions._start(
                self.identity, "estimate", "database", ["Items.json"]
            )
        self.backend.operations.jobs.clear()
        self.backend.running = lambda: False
        self.pending = None
        self.guided.batch_monitor.busy.clear()
        with self.assertRaisesRegex(ValueError, "outputs are no longer available"):
            self.guided.preview(self.identity, "export_selected", files=["Items.json"])
        job["status"] = "running"
        provider = Mock()
        provider.status.return_value = {"api_status": "in_progress"}
        # A successful provider cancellation used to crash before saving its
        # acknowledgement: the native helper returns api_status, not status.
        # Exercise the real adapter instead of mocking away that contract.
        provider.provider = "openai"
        native = ModuleType("util.batch_providers")
        native.cancel_batch = Mock(
            return_value={
                "id": batch["id"],
                "api_status": "cancelling",
                "raw": object(),
            }
        )
        adapter = batch_control.TranslationProvider
        provider.cancel.side_effect = lambda identity: adapter.cancel(
            provider, identity
        )
        with (
            patch.object(batch_control, "TranslationProvider", return_value=provider),
            replaced_modules({"util.batch_providers": native}),
        ):
            review = self.guided.batch_cancel_preview(
                self.identity, job["id"], batch["id"]
            )
            other = self.projects.open(
                {"source": str(self.root / "other-batch-project"), "engine": "MVMZ"}
            )
            with self.assertRaises(ValueError):
                self.guided.batch_cancel(other["id"], review["token"])
            provider.cancel.assert_not_called()
            configuration = self.backend.saved_run_configuration
            self.backend.saved_run_configuration = lambda _: {
                "workflow": {"id": "other-owner"}
            }
            with self.assertRaises(ValueError):
                self.guided.batch_cancel(self.identity, review["token"])
            provider.cancel.assert_not_called()
            self.backend.saved_run_configuration = configuration
            review = self.guided.batch_cancel_preview(
                self.identity, job["id"], batch["id"]
            )
            self.guided.batch_cancel(self.identity, review["token"])
            with self.assertRaises(ValueError):
                self.guided.batch_cancel(self.identity, review["token"])
            provider.cancel.assert_called_once_with(batch["id"])
            native.cancel_batch.assert_called_once_with(
                "openai", batch["id"], client=provider.client
            )
            self.assertEqual(
                job["dazedtl_batch_cancellations"][batch["id"]]["status"], "cancelling"
            )
            self.backend.manual.save.assert_called_with(job)
            # A stale worker poll cannot replace the just-acknowledged status.
            job["phase"], job["batch_detail"] = (
                "poll_status",
                [{"id": batch["id"], "api_status": "in_progress"}],
            )
            self.assertEqual(
                self.guided.run_view(job["id"])["process"]["batches"][0]["status"],
                "cancelling",
            )
            with self.assertRaises(ValueError):
                self.guided.batch_collect(self.identity, job["id"])
            job["status"] = "stopped"
            provider.status.return_value = {
                "api_status": "cancelled",
                "counts": {"succeeded": 1, "processing": 0, "canceled": 0},
            }
            provider.collect_terminal.return_value = (
                {"key": {"text": "Saved response"}},
                [],
                {},
            )

            def resume(identity):
                self.assertEqual(identity, job["id"])
                self.assertEqual(
                    read_json(root / "log/batch_state.json")["status"], "fetched"
                )
                job["status"] = "running"
                return job

            self.backend.manual.consume_batch = Mock(side_effect=resume)
            self.guided.batch_collect(self.identity, job["id"])
            with self.assertRaises(ValueError):
                self.guided.batch_collect(self.identity, job["id"])
            self.backend.manual.consume_batch.assert_called_once()
        provider.submit.assert_not_called()
        provider.live.assert_not_called()

    def complete_preparation(self):
        return preparation.run(
            {
                "action": "prepare_game",
                "project": self.native,
                "folder": str(self.folder),
            },
            lambda _: None,
            lambda *_: {"files": 1},
            lambda *_: {},
        )

    def test_baseline_needs_current_preparation_but_reuses_existing_baselines(self):
        options = {"version": "1.0", "untranslated": True}
        with self.assertRaisesRegex(ValueError, "Prepare the game files before"):
            self.guided.preview(self.identity, "git_setup", options=options)
        self.complete_preparation()
        preview = self.guided.preview(self.identity, "git_setup", options=options)
        # Receipt loss after review also blocks execution.
        (self.folder / "preparation.json").unlink()
        with self.assertRaisesRegex(ValueError, "Prepare the game files before"):
            self.guided.execute(self.identity, preview["token"])
        self.translation.operation.assert_not_called()
        self.git_configured = True
        self.assertFalse(
            self.guided.preview(self.identity, "git_setup", options=options)[
                "confirmation"
            ]
        )
        self.assertIsNone(self.guided.saved_form(self.identity)["untranslated"])
        with self.assertRaisesRegex(ValueError, "Choose whether"):
            self.guided.preview(self.identity, "git_setup", options={"version": "1.0"})

    def test_new_runtime_file_after_git_preview_cannot_enter_the_baseline_unreviewed(
        self,
    ):
        self.complete_preparation()
        self.backend.guided_runtime_files = lambda _: sorted(
            path.name for path in self.source.glob("*.json")
        )
        preview = self.guided.preview(
            self.identity, "git_setup", options={"version": "1.0", "untranslated": True}
        )
        self.assertFalse(preview["confirmation"])
        write_json(self.source / "NewFile.json", [{"name": "New scope"}])
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview["token"])
        self.translation.operation.assert_not_called()

    def test_immediate_preparation_keeps_one_use_execution_checks(self):
        self.backend.workflows.preview = lambda _owner, action, options: {
            "token": action + "-token",
            "options": options,
            "confirmation": True,
        }
        self.backend.workflows.execute = Mock(return_value={"id": "native-operation"})
        self.backend.guided_configure_tools = Mock()
        self.backend.guided_preparation_preview = self.backend.workflows.preview
        data = self.native["data"]
        self.native.update(engine="ACE", data=str(self.source / "ace_json"))
        for action in ("prepare_game", "format_data"):
            with self.assertRaisesRegex(ValueError, "Convert the native Ace data"):
                self.guided.preview(self.identity, action)
        self.native.update(engine="MVMZ", data=data)
        immediate = (
            "prepare_game",
            "format_data",
            "format_plugins",
            "gameupdate",
            "playtest_install",
            "inspector_install",
            "forge_install",
            "playtest_apply",
        )
        for action in immediate:
            with self.subTest(action=action):
                preview = self.guided.preview(self.identity, action)
                self.assertFalse(preview["confirmation"])
                self.assertEqual(
                    self.guided.execute(self.identity, preview["token"])["id"],
                    "native-operation",
                )
                self.backend.workflows.execute.assert_called_with(preview["token"])
                with self.assertRaises(ValueError):
                    self.guided.execute(self.identity, preview["token"])
        self.assertEqual(self.backend.workflows.execute.call_count, len(immediate))
        self.backend.guided_configure_tools.assert_called_with(
            "playtest_apply-token", self.guided.release_defaults(self.identity)["tools"]
        )
        preview = self.guided.preview(self.identity, "format_data")
        self.settings_revision += 1
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, preview["token"])
        self.assertEqual(self.backend.workflows.execute.call_count, len(immediate))
        self.assertTrue(
            self.guided.preview(self.identity, "inspector_remove")["confirmation"]
        )

    def test_new_paid_reviews_allow_overlap_and_retain_historical_receipts(self):
        # Reproduce old-format all-rejected history, then change a receipt to
        # unresolved success between cost review and execution. No provider calls.
        estimate_id = self.seed_estimate()
        estimate_root = self.backend.manual.folder(estimate_id)
        queued = {
            "one": {"provider": "openai", "params": {}, "payload": '{"Line1":"薬"}'}
        }
        write_json(estimate_root / "log/estimate_requests.json", queued)
        identity = "rejected-fixture"
        root = self.backend.manual.folder(identity)
        write_json(
            root / "plan.json",
            {"mode": "batch", "workflow": {"id": "native", "phase": "database"}},
        )
        job = {
            "id": identity,
            "mode": "batch",
            "status": "failed",
            "files": ["Items.json"],
            "log": [],
            "completed": [],
            "outputs": {},
            "plan_hash": digest((root / "plan.json").read_bytes()),
        }
        self.backend.manual.jobs[identity] = job
        self.native["manual_job"] = identity
        self.guided.runs.remember(
            self.identity,
            job,
            self.guided.runs.inputs(self.identity, self.native, "database", "batch"),
        )
        write_json(root / "log/batch_requests.json", queued)
        batch = {
            "id": "batch-fixture",
            "api_status": "completed",
            "custom_ids": {"req-1": "one"},
            "request_counts": {
                "processing": 0,
                "succeeded": 0,
                "errored": 1,
                "canceled": 0,
                "expired": 0,
            },
        }
        write_json(root / "log/batch_history.json", {"batches": [batch]})
        write_json(
            root / "log/batch_state.json",
            {
                "status": "submitted",
                "batches": [{"id": batch["id"], "custom_ids": batch["custom_ids"]}],
            },
        )
        # Each poll shows a run in full and compact (logless) views. Both must
        # reuse one summary, or a large run rereads every request on each poll.
        job["log"] = ["Items.json: prepared"]
        from dazedtl.compatibility import process_view

        with patch.object(
            process_view, "summary", wraps=process_view.summary
        ) as summarize:
            for _ in range(2):
                with self.guided.observations.read():
                    self.guided.run_view(identity)
                    self.guided.run_view(identity, compact=True)
        self.assertEqual(summarize.call_count, 1)
        frozen = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        self.assertFalse(
            self.guided.preview(self.identity, "start", options={"mode": "estimate"})[
                "confirmation"
            ]
        )
        review = self.guided.preview(self.identity, "start", options={"mode": "batch"})
        self.assertTrue(review["confirmation"])
        self.assertFalse(review["estimate"]["repeatSubmission"])
        changed = deepcopy(batch)
        changed["request_counts"].update(errored=0, succeeded=1)
        write_json(root / "log/batch_history.json", {"batches": [changed]})
        self.guided.execute(self.identity, review["token"])
        self.assertEqual(len(self.started), 1)
        with self.assertRaisesRegex(ValueError, "new preview"):
            self.guided.execute(self.identity, review["token"])
        # Already submitted work is advisory for both new modes. Its changing
        # status cannot revoke a fresh approval, and tokens remain one-use.
        for mode in ("batch", "translate"):
            estimate_id = self.seed_estimate(mode=mode)
            estimate_root = self.backend.manual.folder(estimate_id)
            write_json(estimate_root / "log/estimate_requests.json", queued)
            review = self.guided.preview(self.identity, "start", options={"mode": mode})
            self.assertTrue(review["estimate"]["repeatSubmission"])
            self.guided.execute(self.identity, review["token"])
            self.assertTrue(
                self.guided.runs.records(self.identity)["paid-run"]["estimate"][
                    "repeatSubmission"
                ]
            )
        self.assertEqual(len(self.started), 3)
        self.assertFalse(
            self.guided.preview(self.identity, "start", options={"mode": "estimate"})[
                "confirmation"
            ]
        )
        # Disjoint source text in the same file remains eligible.
        write_json(
            estimate_root / "log/estimate_requests.json",
            {"two": {**queued["one"], "payload": '{"Line1":"別の文章"}'}},
        )
        self.assertFalse(
            self.guided.preview(self.identity, "start", options={"mode": "translate"})[
                "estimate"
            ]["repeatSubmission"]
        )
        for path, raw in frozen.items():
            path.write_bytes(raw)
        self.guided.execute(
            self.identity,
            self.guided.preview(self.identity, "start", options={"mode": "estimate"})[
                "token"
            ],
        )
        reopened = Guided(self.backend, self.projects, self.settings, self.translation)
        self.assertIn(identity, reopened.owned_runs(self.native))
        self.assertEqual({path: path.read_bytes() for path in frozen}, frozen)
        # A later estimate cannot authorize a saved queue without its original
        # paid review; owned and bound approvals can continue without re-review.
        self.native["manual_job"] = estimate_id
        self.backend.manual.resume = Mock(return_value=job)
        self.settings.prepare_engine = Mock()
        with self.assertRaisesRegex(ValueError, "approved"):
            reopened.resume(self.identity, identity)
        with self.assertRaisesRegex(ValueError, "belonging"):
            reopened.resume(self.identity, "another-project-run")
        self.backend.manual.resume.assert_not_called()
        self.settings.prepare_engine.assert_not_called()

    def test_saving_run_blocks_new_preparation_of_its_files(self):
        # Preparing copies working translations into the new run's inputs; a
        # Live run that later saved its final output used to lose it unseen.
        job = {
            "id": "live-run",
            "mode": "translate",
            "status": "running",
            "files": ["Items.json"],
            "log": [],
        }
        self.backend.manual.jobs[job["id"]] = job
        self.guided.runs.remember(
            self.identity,
            job,
            self.guided.runs.inputs(
                self.identity, self.native, "database", "translate"
            ),
        )
        with self.assertRaisesRegex(ValueError, "Items.json is still translating"):
            self.guided.preview(self.identity, "start", options={"mode": "estimate"})
        # A Batch saves only while it consumes provider results.
        job.update(mode="batch", phase="poll")
        self.guided.preview(self.identity, "start", options={"mode": "estimate"})
        job.update(phase="consume")
        with self.assertRaisesRegex(ValueError, "still translating"):
            self.guided.preview(self.identity, "start", options={"mode": "estimate"})

    def test_stopped_live_submission_cannot_block_new_preparation_or_batch_approval(
        self,
    ):
        # A stopped Live call without a response used to strand the selected
        # file. Keep its uncertain receipt while allowing a separately approved run.
        from dazedtl.api import views
        from dazedtl.compatibility import process_view
        from dazedtl.compatibility.run_evidence import Evidence

        identity = "stopped-live"
        root = self.backend.manual.folder(identity)
        job = {
            "id": identity,
            "mode": "translate",
            "status": "stopped",
            "files": ["Items.json"],
            "log": [],
        }
        self.backend.manual.jobs[identity] = job
        self.guided.runs.remember(
            self.identity,
            job,
            self.guided.runs.inputs(
                self.identity, self.native, "database", "translate"
            ),
        )
        evidence = Evidence(root, "translate")
        evidence.local.filename = "Items.json"
        evidence.prepared(
            {"messages": [{"role": "user", "content": '{"Line1":"薬"}'}]}, "submitted"
        )
        before = evidence.path.read_bytes()
        for mode in ("translate", "batch"):
            estimate_id = self.seed_estimate(mode=mode)
            write_json(
                self.backend.manual.folder(estimate_id) / "log/estimate_requests.json",
                {
                    "one": {
                        "params": {},
                        "payload": '{"Line1":"薬"}',
                        "dazedtl_file": "Items.json",
                    }
                },
            )
            review = self.guided.preview(self.identity, "start", options={"mode": mode})
            self.assertTrue(views.preview(review)["estimate"]["repeatSubmission"])
            self.guided.execute(self.identity, review["token"])
        pending = {
            "id": "paid-run",
            "mode": "batch",
            "status": "waiting",
            "files": ["Items.json"],
            "log": [],
            "approval": {"token": "batch-approval", "kind": "batch"},
            "dazedtl_preapproval": True,
        }
        self.backend.manual.jobs[pending["id"]] = pending
        self.assertTrue(
            views.job(self.guided.run_view(pending["id"]))["repeatSubmission"]
        )
        self.backend.manual.save = Mock()

        def answer(run, token, approved):
            self.assertTrue(pending["dazedtl_submission_intent"])
            pending.pop("approval")
            return pending

        self.backend.manual.answer = Mock(side_effect=answer)
        self.guided.answer(self.identity, "batch-approval", True)
        with self.assertRaisesRegex(ValueError, "no longer pending"):
            self.guided.answer(self.identity, "batch-approval", True)
        self.backend.manual.answer.assert_called_once_with(
            pending["id"], "batch-approval", True
        )
        self.assertEqual(evidence.path.read_bytes(), before)
        self.assertEqual(process_view.ledger_records(root)[0]["state"], "submitted")
        # Historical read errors also stay advisory instead of blocking review.
        self.seed_estimate(mode="translate")
        with patch.object(
            self.guided.actions,
            "submission_overlap",
            side_effect=ValueError("Unreadable saved evidence"),
        ):
            self.assertTrue(
                self.guided.preview(
                    self.identity, "start", options={"mode": "translate"}
                )["estimate"]["repeatSubmission"]
            )

    def test_advanced_runs_require_a_source_and_explicit_variable_ids(self):
        # An empty selection wastes paid work; a blank 122 range silently uses
        # the engine's legacy min/max IDs, which may belong to another game.
        self.projects.get(self.identity)["phase"] = "advanced"
        for options in (
            {},
            {"CODE122": True},
            {"CODE122": True, "CODE122_VAR_RANGES": " "},
        ):
            self.native["engine_options"] = options
            for mode in ("batch", "translate", "estimate"):
                with (
                    self.subTest(options=options, mode=mode),
                    self.assertRaises(ValueError),
                ):
                    self.guided.preview(self.identity, "start", options={"mode": mode})
        self.assertEqual(self.started, [])
        for options in (
            {"CODE122": True, "CODE122_VAR_RANGES": "5,10-18,42"},
            {"CODE357": True, "ENABLED_PLUGINS_357": ["TextPicture"]},
        ):
            self.native["engine_options"] = options
            preview = self.preview()
            self.guided.execute(self.identity, preview["token"])
        self.assertEqual(self.started, [("native", "advanced", True)] * 2)

    def event_report(self, commands=()):
        write_json(
            self.source / "Map001.json",
            {
                "list": [
                    {
                        "code": 357,
                        "parameters": ["TextPicture", "show", "", {"text": "表示"}],
                    },
                    *commands,
                ]
            },
        )
        self.backend.phase_files = lambda _native, phase: (
            ["Items.json"] if phase == "database" else ["Map001.json"]
        )
        self.native["selected"] = ["Items.json", "Map001.json"]
        request = self.guided.event_text.request(self.identity, self.native)
        report = {
            key: request[key]
            for key in ("version", "request_id", "project_id", "engine", "fingerprint")
        }
        ref = {
            "file": "Map001.json",
            "sha256": request["dependencies"]["Map001.json"],
            "location": "event 1, page 1, command 1",
        }
        report["sources"] = {
            key: {
                "decision": "skip",
                "confidence": "high",
                "coverage": "none",
                "reason": "Fixture inspected; no safe display use.",
                "targets": "" if key == "CODE122" else [],
                "observations": [],
                "exclusions": [],
                "evidence": [ref],
                **({"spacing": {}, "keep": []} if key in event_text.WORDED else {}),
                **({"custom": []} if key in event_text.CUSTOM else {}),
            }
            # As an earlier release saved them, with the name, nickname and
            # profile changes Maps & events now translates.
            for key in (*event_text.CODES, *sorted(event_text.RETIRED))
        }
        report["sources"]["CODE357"].update(
            decision="enable",
            coverage="safe",
            targets=["TextPicture"],
            observations=["TextPicture show: text is displayed."],
        )
        write_json(self.source / event_text.REPORT, report)
        return request, report

    def test_event_findings_apply_exact_selectors_once_and_bind_runs_to_sources_and_definitions(
        self,
    ):
        # Saved findings configure only through the assistant's apply, which
        # waits for pending option edits and rejects a report for another
        # request; selector swaps and old reports must not configure a run.
        request, _report = self.event_report()
        self.assertEqual(
            self.guided.event_text.request(self.identity, self.native)["request_id"],
            request["request_id"],
        )
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertEqual(findings["status"], "ready")
        self.assertFalse(findings["applied"])
        # Findings not applied yet go out of date when their sources change.
        events = (self.source / "Map001.json").read_bytes()
        write_json(self.source / "Map001.json", {"list": []})
        self.assertEqual(
            self.guided.event_text.status(self.identity, self.native)["status"], "stale"
        )
        (self.source / "Map001.json").write_bytes(events)
        self.assertEqual(self.native["engine_options"], {})
        self.assertEqual(
            findings["recommended"]["ENABLED_PLUGINS_357"], ["TextPicture"]
        )
        self.assertEqual(findings["recommended"]["ENABLED_PATTERNS_355655"], [])
        self.guided.options_draft(
            self.identity, self.edited(self.guided.preferences(self.native))
        )
        with self.assertRaises(ValueError):
            self.guided.event_text_request(self.identity, apply=True)
        self.guided.options_draft(self.identity, None)
        with self.assertRaises(ValueError):
            self.guided.event_text_apply(self.identity, 0, "another-report")
        self.assertEqual(self.native["engine_options"], {})
        applied = self.guided.event_text_request(self.identity, apply=True)
        self.assertTrue(applied["findings"]["applied"])
        self.assertEqual(applied["findings"]["enabled"], ["CODE357"])
        self.assertEqual(
            self.native["engine_options"]["ENABLED_PLUGINS_357"], ["TextPicture"]
        )
        review = self.guided.event_text.require(self.identity, self.native)
        self.assertEqual(review["reportId"], findings["reportId"])
        self.assertEqual(review["settings"]["ENABLED_PLUGINS_357"], ["TextPicture"])
        # Later edits are the user's own choices for these same findings.
        self.native["engine_options"]["CODE356"] = True
        self.assertTrue(
            self.guided.event_text.status(self.identity, self.native)["applied"]
        )
        self.native["engine_options"]["CODE356"] = False
        self.projects.get(self.identity)["phase"] = "advanced"
        quote = self.preview()
        # A DazedTL update leaves applied findings current, but a quote made
        # before it needs a new estimate.
        self.catalog["fingerprint"] = "changed-installed-parser"
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertEqual((findings["status"], findings["applied"]), ("ready", True))
        with self.assertRaises(ValueError):
            self.guided.execute(self.identity, quote["token"])
        self.assertEqual(self.started, [])
        self.catalog["fingerprint"] = "fixture-definitions"
        # Applied findings stay through later game edits, but not past the
        # event files they covered.
        write_json(self.source / "Map001.json", {"list": []})
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertEqual((findings["status"], findings["applied"]), ("ready", True))
        self.assertEqual(self.native["selected"], ["Items.json", "Map001.json"])
        write_json(self.source / "Map002.json", {"list": []})
        self.backend.phase_files = lambda _native, phase: (
            ["Items.json"] if phase == "database" else ["Map001.json", "Map002.json"]
        )
        self.native["selected"].append("Map002.json")
        self.assertEqual(
            self.guided.event_text.status(self.identity, self.native)["status"], "stale"
        )
        plugin = self.source / "js/plugins/Display.js"
        plugin.parent.mkdir(parents=True)
        plugin.write_text("original display implementation", encoding="utf-8")
        relative = "js/plugins/Display.js"
        self.translation.engine.source_bindings = lambda _root, paths: (
            {relative: "original-plugin-blob"} if relative in paths else {}
        )
        self.translation.engine.original_blobs = lambda _root, blobs: (
            (blob, b"original display implementation") for blob in blobs
        )
        before = self.guided.event_text.context(
            self.identity, self.native, self.catalog
        )
        plugin.write_text("modified logic implementation", encoding="utf-8")
        after = self.guided.event_text.context(self.identity, self.native, self.catalog)
        self.assertEqual(
            before["dependencies"][relative], after["dependencies"][relative]
        )
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])

    def test_event_findings_reject_foreign_partial_unknown_targets_and_keep_mixed_coverage_off(
        self,
    ):
        _, report = self.event_report()
        for mutate, status in (
            (lambda r: r.update(project_id="foreign"), "stale"),
            # Findings for an earlier request wait for the refreshed task's.
            (lambda r: r.update(request_id="earlier"), "waiting"),
            (lambda r: r["sources"].pop("CODE356"), "invalid"),
            (
                lambda r: r["sources"]["CODE357"].update(targets=["mock-placeholder"]),
                "invalid",
            ),
            (lambda r: r["sources"]["CODE356"].update(targets=["D_TEXT"]), "invalid"),
            (
                lambda r: r["sources"]["CODE356"].update(spacing={"D_TEXT": "nbsp"}),
                "invalid",
            ),
            (lambda r: r["sources"]["CODE122"].update(custom=[]), "invalid"),
            # A pattern without a capture has no text to translate, and a
            # nested repeat can hang the engine on a line it almost matches.
            *(
                (
                    lambda r, regex=regex: r["sources"]["CODE355655"].update(
                        custom=[{"name": "notice", "regex": regex}]
                    ),
                    "invalid",
                )
                for regex in (r"Notice\.show", r"Notice\.show\('((?:\w+)*)'\)")
            ),
        ):
            value = deepcopy(report)
            mutate(value)
            write_json(self.source / event_text.REPORT, value)
            with self.subTest(status=status):
                self.assertEqual(
                    self.guided.event_text.status(self.identity, self.native)["status"],
                    status,
                )
        report["sources"]["CODE357"].update(
            coverage="mixed", exclusions=["Same handler also consumes an internal key."]
        )
        write_json(self.source / event_text.REPORT, report)
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertEqual(findings["status"], "ready")
        self.assertFalse(findings["recommended"]["CODE357"])
        self.native["engine_options"] = {
            **findings["recommended"],
            "CODE357": True,
            "ENABLED_PLUGINS_357": ["TextPicture"],
        }
        self.assertEqual(
            self.guided.event_text.require(self.identity, self.native)["settings"][
                "ENABLED_PLUGINS_357"
            ],
            ["TextPicture"],
        )
        self.native["engine_options"]["ENABLED_PLUGINS_357"] = ["not-installed"]
        with self.assertRaises(ValueError):
            self.guided.event_text.require(self.identity, self.native)

    def test_event_findings_keep_only_commands_found_in_the_selected_events(self):
        # A mistyped command to keep would silently leave an internal value,
        # such as DTextPicture's [マップ表示名] placeholder, to translation.
        placeholder = "D_TEXT [マップ表示名] 24"
        _, report = self.event_report(
            [
                {"code": 356, "parameters": [text]}
                for text in (placeholder, "D_TEXT 時刻 24")
            ]
        )
        report["sources"]["CODE356"].update(
            decision="enable",
            coverage="safe",
            spacing={"D_TEXT ": "nbsp", "CommonPopup": "underscore"},
            keep=[placeholder + " "],
        )
        write_json(self.source / event_text.REPORT, report)
        with self.assertRaisesRegex(ValueError, "not in the selected event files"):
            self.guided.event_text_request(self.identity, apply=True)
        self.assertEqual(self.native["engine_options"], {})
        report["sources"]["CODE356"]["keep"] = [placeholder]
        write_json(self.source / event_text.REPORT, report)
        applied = self.guided.event_text_request(self.identity, apply=True)
        self.assertEqual(applied["findings"]["enabled"], ["CODE357", "CODE356"])
        options = self.native["engine_options"]
        self.assertEqual(
            (options["NBSP_356"], options["SPACES_356"], options["KEEP_356"]),
            (["D_TEXT "], [], [placeholder]),
        )

    def test_event_findings_apply_the_games_own_patterns_only_where_they_capture_japanese(
        self,
    ):
        # Text no installed handler captured needed an engine change. The
        # assistant's own patterns stand in for one only when each captures
        # Japanese in the selected events, inside its quotes, one per command.
        quest = {"title": "クエスト", "data": '{"reward":"宝"}'}
        _, report = self.event_report(
            [
                {"code": 355, "parameters": ["Notice.show('宝箱だ');"]},
                {"code": 357, "parameters": ["QuestLog", "add", "", quest]},
            ]
        )
        notice = {"name": "notice", "regex": r"Notice\.show\('(.*)'\)"}
        handler = {"plugin": "QuestLog", "command": "add", "args": ["title"]}
        report["sources"]["CODE355655"].update(decision="enable", coverage="safe")
        report["sources"]["CODE357"]["custom"] = [handler]
        for code, custom, problem in (
            (
                "CODE355655",
                [{**notice, "regex": r"Notice\.show\('(se_\w+)'\)"}],
                "no Japanese",
            ),
            ("CODE355655", [notice, {**notice, "name": "again"}], "both capture"),
            ("CODE355655", [{**notice, "regex": r"Notice\.show\((.*)\)"}], "quotes"),
            # A struct argument is JSON text the plugin parses.
            ("CODE357", [{**handler, "args": ["data"]}], "structured data"),
        ):
            sources = deepcopy(report["sources"])
            sources["CODE355655"]["custom"] = [notice]
            sources[code]["custom"] = custom
            write_json(self.source / event_text.REPORT, {**report, "sources": sources})
            with (
                self.subTest(problem=problem),
                self.assertRaisesRegex(ValueError, problem),
            ):
                self.guided.event_text_request(self.identity, apply=True)
        self.assertEqual(self.native["engine_options"], {})
        report["sources"]["CODE355655"]["custom"] = [notice]
        write_json(self.source / event_text.REPORT, report)
        applied = self.guided.event_text_request(self.identity, apply=True)
        # The source needs no registered entry when its own pattern covers it.
        self.assertEqual(applied["findings"]["enabled"], ["CODE357", "CODE355655"])
        options = self.native["engine_options"]
        self.assertEqual(
            (options["CUSTOM_355655"], options["CUSTOM_357"]), ([notice], [handler])
        )
        row = next(
            row for row in applied["findings"]["rows"] if row["key"] == "CODE355655"
        )
        self.assertTrue(any(notice["regex"] in note for note in row["observations"]))
        # A file Git holds no original of, such as VX Ace's converted data,
        # reads a translated command's original text from its _original.
        _, report = self.event_report(
            [
                {
                    "code": 355,
                    "parameters": ["Notice.show('A chest!');"],
                    "_original": "Notice.show('宝箱だ');",
                },
                {"code": 357, "parameters": ["QuestLog", "add", "", quest]},
            ]
        )
        report["sources"]["CODE355655"].update(
            decision="enable", coverage="safe", custom=[notice]
        )
        report["sources"]["CODE357"]["custom"] = [handler]
        write_json(self.source / event_text.REPORT, report)
        applied = self.guided.event_text_request(self.identity, apply=True)
        self.assertEqual(applied["findings"]["enabled"], ["CODE357", "CODE355655"])

    def test_empty_registry_selection_needs_effective_builtin_coverage_and_picker_is_project_owned(
        self,
    ):
        # Empty filters must not authorize meaningless runs; built-in coverage
        # is explicit and cannot be mistaken for per-handler isolation.
        self.event_report()
        self.native["engine_options"] = {"CODE357": True, "ENABLED_PLUGINS_357": []}
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertTrue(findings["errors"])
        with self.assertRaises(ValueError):
            self.guided.event_text.require(self.identity, self.native)
        write_json(
            self.source / "Map001.json",
            {
                "list": [
                    {
                        "code": 357,
                        "parameters": ["BuiltinPlugin", "show", "", {"text": "表示"}],
                    }
                ]
            },
        )
        findings = self.guided.event_text.status(self.identity, self.native)
        self.assertEqual(findings["builtinHits"]["CODE357"], ["BuiltinPlugin"])
        self.assertEqual(findings["errors"], [])
        draft = {
            "key": "ENABLED_PLUGINS_357",
            "selected": ["TextPicture", "QuestSystem"],
            "baseline": [],
            "query": "hidden",
            "filter": "selected",
        }
        self.guided.event_text_picker(self.identity, draft)
        reopened = Guided(self.backend, self.projects, self.settings, self.translation)
        self.assertEqual(
            reopened.event_text.status(self.identity, self.native)["picker"], draft
        )
        self.guided.event_text_picker(self.identity, None)
        self.assertIsNone(
            reopened.event_text.status(self.identity, self.native)["picker"]
        )
        with self.assertRaises(ValueError):
            self.guided.event_text_picker(
                self.identity, {**draft, "key": "ENABLED_PLUGINS_356"}
            )

    def test_new_games_do_not_inherit_another_games_advanced_targets(self):
        self.record.pop("backend_id")
        self.backend.workflows.projects.clear()
        self.native["engine_options"] = {
            "CODE122": True,
            "CODE357": True,
            "CODE122_VAR_RANGES": "17,26",
            "ENABLED_PLUGINS_357": ["TextPicture"],
            "ENABLED_PATTERNS_355655": ["gameVariables.setValue"],
            "FIXTEXTWRAP": True,
        }
        self.translation.drafts = lambda _: {"documents": {}}
        self.backend.describe = lambda source: {"source": source, "engine": "MVMZ"}

        def open_workflow(_source):
            self.backend.workflows.projects["native"] = self.native
            return {"project": self.native}

        self.backend.workflows.open = open_workflow
        self.native["selected"] = []
        self.guided.open(self.identity)
        self.assertEqual(self.native["selected"], ["Items.json"])
        options = self.native["engine_options"]
        self.assertFalse(options["CODE122"])
        self.assertFalse(options["CODE357"])
        self.assertEqual(options["CODE122_VAR_RANGES"], "")
        self.assertEqual(options["ENABLED_PLUGINS_357"], [])
        self.assertEqual(options["ENABLED_PATTERNS_355655"], [])
        self.assertTrue(options["FIXTEXTWRAP"])
        # Reopening a game retains its own reviewed choices and saved run.
        options.update(CODE122=True, CODE122_VAR_RANGES="5,10-18")
        self.native["manual_job"] = "existing-run"
        self.native["selected"] = []
        self.guided.open(self.identity)
        self.assertTrue(self.native["engine_options"]["CODE122"])
        self.assertEqual(self.native["engine_options"]["CODE122_VAR_RANGES"], "5,10-18")
        self.assertEqual(self.native["manual_job"], "existing-run")
        self.assertEqual(self.native["selected"], [])

    def test_comment_text_turns_on_once_for_plugin_shown_comments(self):
        # MPP_ChoiceEX shows the comment lines under a marker its settings
        # list as each choice's help. A project's next look turns Comment
        # text on; turned off afterwards, it stays off.
        plugin = {
            "name": "MPP_ChoiceEX",
            "status": True,
            "parameters": {"Choice Help Commands": '["ChoiceHelp"]'},
        }
        plugins = self.source / "js/plugins.js"
        plugins.parent.mkdir(parents=True)
        plugins.write_text(f"var $plugins =\n[{json.dumps(plugin)}];\n", "utf-8")
        help_lines = [
            {"code": 108, "indent": 0, "parameters": ["ChoiceHelp"]},
            {"code": 408, "indent": 0, "parameters": ["所要時間:20分"]},
        ]
        write_json(
            self.source / "Map001.json", {"events": [{"pages": [{"list": help_lines}]}]}
        )
        self.native["plugins"] = str(plugins)
        self.guided.comment_text(self.identity)
        native = self.backend.workflows.projects["native"]
        self.assertTrue(native["phase1_comments"])
        # A working copy made before then counts its help as a line still
        # in Japanese, under the plugin's marker as the engine reads it.
        inputs = self.guided.inputs(self.native)
        inputs.prepare(["Map001.json"])
        markers = comment_text.markers(self.source)
        self.assertEqual(
            inputs.line_counts({"Map001.json": "dialogue"}, markers),
            {"Map001.json": {"lines": 1, "translated": 0, "help": 1}},
        )
        # A file shaped unlike RPG Maker data holds no lines, rather than
        # failing every look at the project; the game's own help still counts.
        odd = [{"code": 108, "parameters": {"text": "ChoiceHelp"}}]
        write_json(self.source / "CustomEvents.json", odd)
        write_json(self.folder / "translated/Map001.json", odd)
        self.assertEqual(
            inputs.line_counts({"Map001.json": "dialogue"}, markers),
            {"Map001.json": {"lines": 0, "translated": 0}},
        )
        self.assertTrue(
            comment_text.shows_comment_text(self.source, self.native["plugins"])
        )
        native.update(phase1_comments=False, revision=native["revision"] + 1)
        self.guided.comment_text(self.identity)
        self.assertFalse(self.backend.workflows.projects["native"]["phase1_comments"])

    def test_a_translated_map_name_counts_before_any_run_binds_its_file(self):
        # A game opened with its maps already translated, such as a copy made
        # after translating, counted no map name line until a run recorded
        # the file's original, so its maps read a line short or Done.
        write_json(self.source / "Map001.json", {"displayName": "Village"})
        self.translation.engine.source_bindings = lambda _source, paths: {
            path: "unbound-map-name" for path in paths if path.endswith("Map001.json")
        }
        self.translation.engine.original_blobs = lambda _source, blobs: (
            (blob, '{"displayName": "村"}'.encode()) for blob in blobs
        )
        self.assertEqual(
            self.guided.inputs(self.native).line_counts(
                {"Map001.json": "dialogue"}, frozenset()
            ),
            {"Map001.json": {"lines": 1, "translated": 1}},
        )

    def test_estimate_freezes_estimate_mode_without_changing_the_saved_api_choice(self):
        observed = []

        def phase(*_args):
            observed.append(self.native["mode"])
            return {"id": "estimate"}

        self.backend.workflows.phase = phase
        for mode in ("translate", "batch"):
            with self.subTest(mode=mode):
                self.native["mode"] = mode
                preview = self.guided.preview(
                    self.identity, "start", options={"mode": "estimate"}
                )
                self.guided.execute(self.identity, preview["token"])
                self.assertEqual(
                    self.guided.preferences(self.native)["values"]["mode"], mode
                )
        self.assertEqual(observed, ["estimate", "estimate"])

    def test_checkpoint_manifest_distinguishes_new_plugins_from_original_assets(self):
        write_json(self.source / "new-plugin.js", {"fixture": True})
        # A game set up with its translation already in Git has no prepared
        # record, and the game as found holds that translation's additions,
        # such as GameUpdate's config, which the checkpoint cannot supply as
        # originals.
        config = self.source / "gameupdate/patch-config.txt"
        config.parent.mkdir()
        config.write_text("owner=translator", encoding="utf-8")
        original_files.record(self.source, original_files.FOUND)
        self.assertEqual(
            self.guided.patch_manifest(
                self.identity, ["gameupdate/patch-config.txt"], "checkpoint"
            )["files"]["gameupdate/patch-config.txt"],
            {"original_sha256": None},
        )
        original_files.record(self.source, original_files.PREPARED, "1.0")
        write_json(self.source / "added-later.js", {"fixture": True})
        manifest = self.guided.patch_manifest(
            self.identity, ["Items.json", "added-later.js"], "checkpoint"
        )
        self.assertEqual(manifest["files"]["Items.json"], {})
        self.assertEqual(manifest["files"]["added-later.js"], {"original_sha256": None})
        # A source file already tracked on original is not a translation-only addition.
        self.translation.engine.source_bindings = lambda *_args: {
            "new-plugin.js": "original-blob"
        }
        self.assertEqual(
            self.guided.patch_manifest(self.identity, ["new-plugin.js"], "checkpoint")[
                "files"
            ]["new-plugin.js"],
            {},
        )

    def test_reopening_refreshes_inventory_without_losing_options_or_run_ownership(
        self,
    ):
        pending = self.edited(self.guided.preferences(self.native))
        self.guided.options_draft(self.identity, pending)
        self.native["manual_job"] = "saved-batch"
        self.backend.describe = lambda _: {
            "source": str(self.source),
            "engine": "MVMZ",
            "files": [{"name": "Items.json"}, {"name": "Map002.json"}],
        }
        self.backend.workflows.save = Mock()
        self.guided.open(self.identity)
        _, refreshed = self.guided.record(self.identity)
        self.assertEqual(
            [row["name"] for row in refreshed["files"]], ["Items.json", "Map002.json"]
        )
        self.assertEqual(refreshed["manual_job"], "saved-batch")
        self.assertEqual(refreshed["selected"], ["Items.json"])
        self.assertEqual(refreshed["mode"], "batch")
        self.assertEqual(self.record["backend_id"], "native")
        self.assertEqual(read_json(self.guided.path(self.identity, "draft")), pending)

    def test_checked_scope_controls_the_next_run_and_expanding_it_keeps_phase_work(
        self,
    ):
        write_json(self.source / "System.json", {"gameTitle": "ゲーム"})
        self.backend.phase_files = lambda _native, _phase: ["Items.json", "System.json"]
        self.native["imported"] = ["Items.json", "System.json"]
        write_json(self.folder / "files/System.json", {"gameTitle": "Saved phase work"})
        calls = []
        self.backend.guided_phase = lambda owner, phase, files: (
            calls.append(files) or {"id": "run"}
        )
        preview = self.preview()
        self.assertEqual(preview["paths"], ["Items.json"])
        self.guided.execute(self.identity, preview["token"])
        self.assertEqual(calls, [["Items.json"]])
        self.assertEqual(
            read_json(self.folder / "files/System.json"),
            {"gameTitle": "Saved phase work"},
        )
        self.assertEqual(read_json(self.folder / "files/Items.json"), [{"name": "薬"}])
        self.native["selected"] = []
        with self.assertRaises(ValueError):
            self.preview()
        self.assertEqual(len(calls), 1)

    def test_game_edits_do_not_replace_working_progress_until_explicit_reload(self):
        inputs = self.guided.inputs(self.native)
        inputs.prepare(["Items.json"])
        write_json(self.folder / "translated/Items.json", [{"name": "Potion"}])
        write_json(self.folder / "files/Items.json", [{"name": "Saved database phase"}])
        write_json(self.source / "Items.json", [{"name": "新しい薬"}])
        self.assertIsNotNone(self.preview()["token"])
        self.assertEqual(inputs.status(["Items.json"])["changed"], [])
        self.assertEqual(
            read_json(self.folder / "files/Items.json"),
            [{"name": "Saved database phase"}],
        )
        refreshed = inputs.prepare(
            ["Items.json"],
            refresh=True,
            expected=inputs.sources(
                ["Items.json"], inputs.record()["inputs"], fresh=True
            ),
            retired=["former-run"],
        )
        archive = Path(refreshed["archive"])
        self.assertEqual(
            read_json(archive / "translated/Items.json"), [{"name": "Potion"}]
        )
        self.assertEqual(
            read_json(archive / "files/Items.json"), [{"name": "Saved database phase"}]
        )
        self.assertFalse((self.folder / "translated/Items.json").exists())
        self.assertEqual(inputs.record()["retired_runs"], ["former-run"])
        self.assertEqual(inputs.record()["file_versions"]["Items.json"], archive.name)
        self.assertEqual(
            read_json(self.folder / "files/Items.json"), [{"name": "新しい薬"}]
        )
        self.assertIsNotNone(self.preview()["token"])
        with self.assertRaises(ValueError):
            inputs.prepare(["Items.json"], refresh=True, expected={})

        # A failed replacement restores both the old generation and its bytes;
        # an abrupt interruption must already have retired the old generation.
        before = inputs.record()
        write_json(self.folder / "log/var_translation_map.json", {"薬": "Potion"})
        write_json(
            self.folder / "translated/Items.json", [{"name": "New saved translation"}]
        )
        preserved = {
            path: path.read_bytes()
            for path in [
                inputs.index,
                self.folder / "files/Items.json",
                self.folder / "translated/Items.json",
                self.folder / "log/var_translation_map.json",
            ]
        }

        def fail_after_version(message):
            if message.startswith("Preparing source copy:"):
                self.assertNotEqual(
                    inputs.record()["file_versions"], before["file_versions"]
                )
                raise OSError("Fixture replacement failure")

        with self.assertRaisesRegex(OSError, "replacement failure"):
            inputs.prepare(["Items.json"], refresh=True, progress=fail_after_version)
        self.assertEqual({path: path.read_bytes() for path in preserved}, preserved)

        def interrupt_after_version(message):
            if message.startswith("Preparing source copy:"):
                raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            inputs.prepare(
                ["Items.json"], refresh=True, progress=interrupt_after_version
            )
        self.assertNotEqual(inputs.record()["file_versions"], before["file_versions"])
        self.assertEqual(
            read_json(
                self.folder
                / "source-history"
                / inputs.record()["last_refresh"]
                / "translated/Items.json"
            ),
            [{"name": "New saved translation"}],
        )

    def test_current_game_seeds_working_copies_and_original_backups_remain_separate(
        self,
    ):
        write_json(self.source / "Items.json", [{"name": "English runtime"}])
        inputs = GuidedInputs(
            self.folder,
            self.source,
            self.source,
            lambda *_args: {"Items.json": "original"},
            lambda *_args: b'[{"name":"Japanese baseline"}]',
        )
        inputs.prepare(["Items.json"])
        self.assertEqual(
            read_json(self.folder / "files/Items.json"), [{"name": "English runtime"}]
        )
        self.assertEqual(inputs.status(["Items.json"])["changed"], [])
        # Applying or editing the game leaves its original as it was; an
        # update that brings in a new release's file does not.
        write_json(self.folder / "translated/Items.json", [{"name": "Potion"}])
        write_json(self.source / "Items.json", [{"name": "Potion"}])
        self.assertEqual(inputs.status(["Items.json"])["changed"], [])
        inputs.bindings = lambda *_args: {"Items.json": "updated original"}
        self.assertEqual(inputs.status(["Items.json"])["changed"], ["Items.json"])
        inputs.bindings = lambda *_args: {"Items.json": "original"}
        # Native Ace JSON exports do not live in Git; an exact applied output is
        # still the same source identity. Game edits wait for explicit reload.
        self.guided.inputs(self.native).prepare(["Items.json"], refresh=True)
        write_json(self.folder / "translated/Items.json", [{"name": "Applied English"}])
        (self.source / "Items.json").write_bytes(
            (self.folder / "translated/Items.json").read_bytes()
        )
        self.assertEqual(
            self.guided.inputs(self.native).status(["Items.json"])["changed"], []
        )
        write_json(self.source / "Items.json", [{"name": "Changed export"}])
        self.assertEqual(
            self.guided.inputs(self.native).status(["Items.json"])["changed"], []
        )
        native_inputs = GuidedInputs(
            self.folder,
            self.source,
            self.source,
            lambda *_: {"Data/Items.rvdata2": "native-original"},
            lambda *_: b"",
            native_exports=True,
        )
        native_inputs.prepare(["Items.json"], refresh=True)
        write_json(self.source / "Items.json", [{"name": "Fitted runtime English"}])
        self.assertEqual(native_inputs.status(["Items.json"])["changed"], [])
        # A game update records the new release's data as the original, so
        # the translated copy reads changed until it is reloaded, though the
        # original now holds the export too.
        native_inputs.bindings = lambda *_: {
            "Data/Items.rvdata2": "new-native-original",
            "Items.json": "export-original",
        }
        self.assertEqual(
            native_inputs.status(["Items.json"])["changed"], ["Items.json"]
        )
        native_inputs.bindings = lambda *_: {
            "Data/Items.rvdata2": "new-native-original"
        }
        native_inputs.prepare(["Items.json"], refresh=True)
        self.assertEqual(native_inputs.status(["Items.json"])["changed"], [])
        self.assertEqual(
            native_inputs.record()["inputs"]["Items.json"]["identity"][
                "native_original"
            ]["blob"],
            "new-native-original",
        )

    def test_apply_and_new_line_widths_fit_translated_text(self):
        from types import ModuleType

        from dazedtl.compatibility.text import (
            prepare_publication,
            run_fit,
            run_publication,
        )

        # An output translated before narrower Line widths holds a description
        # too wide for its help window; Apply writes it fitted, and Japanese
        # left untranslated stays as it is.
        output = [
            None,
            {
                "id": 1,
                "name": "Potion",
                "description": "Restores a little health to every ally.",
                "_original": {"description": "体力を少し回復する"},
            },
            {
                "id": 2,
                "name": "薬草",
                "description": "体力をとても少しだけ回復する草です",
            },
            # A word wider than any help window, which no wrap can fit.
            {
                "id": 3,
                "name": "Elixir",
                "description": "Supercalifragilisticexpialidocious",
                "_original": {"description": "万能薬"},
            },
        ]
        write_json(self.folder / "translated/Items.json", output)
        self.native["widths"] = {**self.native["widths"], "listWidth": 24}
        actions = ModuleType("desktop.backend.workflow_actions")
        actions.validate_plan = lambda _: None
        actions.action_guard = lambda *_: {}

        def plan(action, options):
            return {
                "project_id": "native",
                "project": self.native,
                "folder": str(self.folder),
                "action": action,
                "label": action,
                "options": options,
                "guard": {},
            }

        with replaced_modules({"desktop.backend.workflow_actions": actions}):
            apply = plan("export_selected", {"files": ["Items.json"]})
            prepare_publication(apply)
            run_publication(apply, lambda _: None)
            applied = read_json(self.source / "Items.json")
            self.assertEqual(
                applied[1]["description"], "Restores a little\nhealth to every ally."
            )
            self.assertEqual(applied[2], output[2])
            # A message translated at a narrower Dialogue width is applied as
            # the game's widths lay it out.
            from util.rpgmaker_rewrap import Layout, fit_document

            message = [
                {"code": 101, "parameters": ["", 0, 0, 2]},
                {
                    "code": 401,
                    "parameters": ["The forest road is dangerous, so be careful."],
                },
                {"code": 0, "parameters": []},
            ]

            def translated():
                return {"events": [None, {"pages": [{"list": deepcopy(message)}]}]}

            narrow, direct = translated(), translated()
            fit_document(narrow, "Map001.json", Layout(30, 30, 50, 50, 4))
            fit_document(direct, "Map001.json", Layout(50, 40, 50, 50, 4))
            self.assertNotEqual(narrow, direct)
            write_json(self.source / "Map001.json", {"events": []})
            write_json(self.folder / "translated/Map001.json", narrow)
            apply = plan("export_selected", {"files": ["Map001.json"]})
            prepare_publication(apply)
            run_publication(apply, lambda _: None)
            self.assertEqual(read_json(self.source / "Map001.json"), direct)
            # The bytes Apply fitted are no later edit for the next Apply.
            again = plan("export_selected", {"files": ["Items.json"]})
            rows = prepare_publication(again)["publication"]
            self.assertFalse(rows[0]["later_edits"])
            # New widths fit the applied text again in their own area only.
            # Weapons.json counts as applied where its bytes equal a run's
            # output, but no Apply wrote it.
            fit = {"files": ["Items.json", "Weapons.json"]}
            # A fit that rewraps nothing still lists the text it cannot fit,
            # in every area, with the widths it fitted to.
            result = run_fit(
                plan("fit_text", {"areas": ["width"], **fit}), lambda _: None
            )
            self.assertEqual(result["lines"], 0)
            self.assertEqual(
                (result["misfits"], result["misfit_count"]),
                (
                    [
                        {
                            "file": "Items.json",
                            "pointer": "/3/description",
                            "reason": "has a line 34 characters wide; "
                            "its line width is 24",
                        }
                    ],
                    1,
                ),
            )
            self.assertEqual(result["widths"], self.native["widths"])
            self.assertNotIn("Every line", result["message"])
            self.native["widths"] = {**self.native["widths"], "listWidth": 20}
            # A file DazedTL never applied, such as one translated by hand,
            # stays as it is.
            hand = [
                None,
                {"id": 1, "description": "Written by hand, wider than any window."},
            ]
            write_json(self.source / "Weapons.json", hand)
            result = run_fit(
                plan("fit_text", {"areas": ["listWidth"], **fit}), lambda _: None
            )
            self.assertEqual(result["lines"], 1)
            refitted = read_json(self.source / "Items.json")[1]["description"]
            self.assertLessEqual(max(map(len, refitted.split("\n"))), 20)
            self.assertEqual(read_json(self.source / "Weapons.json"), hand)
            # The fit is the last Apply's text fitted again, not a later edit.
            again = plan("export_selected", {"files": ["Items.json"]})
            self.assertFalse(
                prepare_publication(again)["publication"][0]["later_edits"]
            )
        # Saving new widths queues the fit, which starts once nothing runs
        # and the game holds applied text.
        self.guided.text_fit.request(
            self.identity, self.native, {"listWidth": 20}, {"listWidth": 30}
        )
        self.assertTrue(self.guided.text_fit.pending(self.identity))
        self.backend.running = lambda: True
        self.assertIsNone(
            self.guided.text_fit.advance(self.identity, self.native, ["Items.json"])
        )
        self.backend.running = lambda: False
        # A game update's merge stopped on conflicts leaves their markers in
        # applied files: the fit failed on them with a raw JSON error and used
        # up the request. It waits, saying why, until Git is done.
        git = {
            "configured": True,
            "pending_operations": ["MERGE_HEAD"],
            "current_branch": "main",
            "translation_branch": "main",
        }
        self.translation.engine.git_status = lambda *_: git
        self.assertIsNone(
            self.guided.text_fit.advance(self.identity, self.native, ["Items.json"])
        )
        self.assertIn(
            "unfinished Git merge", self.guided.text_fit.waiting(self.identity)
        )
        self.backend.operations.start.assert_not_called()
        git["pending_operations"] = []
        self.guided.text_fit.advance(self.identity, self.native, ["Items.json"])
        started = self.backend.operations.start.call_args.args[0]
        self.assertEqual(
            (started["action"], started["options"]),
            ("fit_text", {"areas": ["listWidth"], "files": ["Items.json"]}),
        )
        self.assertFalse(self.guided.text_fit.pending(self.identity))
        # A snapshot starts the queued fit before it lists what runs.
        self.backend.operations.start.reset_mock()
        self.guided.text_fit.request(
            self.identity, self.native, {"listWidth": 30}, {"listWidth": 40}
        )
        self.backend.workflows.state = lambda _: {
            "project": {**self.native, "files": [{"name": "Items.json"}]}
        }
        self.guided.start_queued(self.identity)
        self.backend.operations.start.assert_called_once()
        self.assertFalse(self.guided.text_fit.pending(self.identity))
        # Saving the same widths again retries a fit that failed.
        operations = self.root / "operations"
        write_json(operations / "fit/plan.json", {"options": {"areas": ["listWidth"]}})
        self.backend.operations.root = operations
        self.backend.operations.jobs = {
            "fit": {
                "id": "fit",
                "project_id": "native",
                "action": "fit_text",
                "status": "failed",
                "created": 1,
            }
        }
        same = {"listWidth": 30}
        self.guided.text_fit.request(self.identity, self.native, same, same)
        self.assertTrue(self.guided.text_fit.pending(self.identity))
        # New message rows rewrap nothing but check again what does not fit.
        (self.guided.path(self.identity, "text-fit")).unlink()
        jobs = self.backend.operations.jobs
        jobs["fit"]["status"] = "complete"
        self.guided.text_fit.request(
            self.identity, self.native, {"messageRows": 4}, {"messageRows": 3}
        )
        self.assertTrue(self.guided.text_fit.pending(self.identity))
        self.assertEqual(
            read_json(self.guided.path(self.identity, "text-fit"))["areas"], []
        )
        # The newest fit's misfits show while its text is the game's: until
        # another write to the game's text or new widths.
        listed = {"misfits": result["misfits"], "misfit_count": 1}
        jobs["fit"].update(
            status="complete", result={**listed, "widths": self.native["widths"]}
        )
        self.assertEqual(self.guided.text_fit.misfits(self.native), listed)
        jobs["apply"] = {
            "id": "apply",
            "project_id": "native",
            "action": "export_selected",
            "status": "complete",
            "created": 2,
        }
        unlisted = {"misfits": [], "misfit_count": 0}
        self.assertEqual(self.guided.text_fit.misfits(self.native), unlisted)
        del jobs["apply"]
        self.native["widths"] = {**self.native["widths"], "listWidth": 40}
        self.assertEqual(self.guided.text_fit.misfits(self.native), unlisted)

    def test_edits_after_apply_do_not_request_reapplication_and_changed_review_or_missing_output_is_pending(
        self,
    ):
        self.native["files"] = [{"name": "Items.json"}]
        write_json(self.source / "Items.json", [{"name": "Applied English"}])
        raw = (self.source / "Items.json").read_bytes()
        write_json(self.folder / "translated/Items.json", [{"name": "Applied English"}])
        write_json(
            self.folder / "applied-outputs.json",
            {"version": 1, "files": {"Items.json": digest(raw)}},
        )
        # An Apply that fitted the output to the Line widths on the way wrote
        # those bytes, which are no later edit.
        write_json(self.source / "Items.json", [{"name": "Fitted\nEnglish"}])
        output = (self.folder / "translated/Items.json").read_bytes()
        write_json(
            self.folder / "applied-outputs.json",
            {
                "version": 1,
                "files": {"Items.json": digest(output)},
                "written": {
                    "Items.json": digest((self.source / "Items.json").read_bytes())
                },
            },
        )
        fitted = self.guided.readiness(self.identity, self.native, {"jobs": []})
        self.assertEqual(fitted["applied"], ["Items.json"])
        self.assertEqual(fitted["runtime_edited"], [])
        write_json(self.source / "Items.json", [{"name": "Edited\nEnglish"}])
        changed = self.guided.readiness(self.identity, self.native, {"jobs": []})
        self.assertEqual(changed["applied"], ["Items.json"])
        self.assertEqual(changed["runtime_edited"], ["Items.json"])
        (self.folder / "translated/Items.json").unlink()
        self.assertEqual(
            self.guided.readiness(self.identity, self.native, {"jobs": []})["outputs"],
            [],
        )
