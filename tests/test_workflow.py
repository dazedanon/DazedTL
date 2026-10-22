"""A small project goes from source-bound plans to reusable accepted work."""

import json
import shutil
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.api.contracts.validation import check_response
from dazedtl.api.server import assistant_dispatch
from dazedtl.compatibility import original_files
from dazedtl.projects.store import Projects
from dazedtl.settings.execution import configuration, connection_summary, worker_secret
from dazedtl.settings.store import Settings
from dazedtl.storage import WorkspaceLock, write_json
from dazedtl.translation import delivery, progress_report
from dazedtl.translation.compilation import compile_requests
from dazedtl.translation.files import digest, evidence, read_json
from dazedtl.translation.game_update import ABSENT
from dazedtl.translation.helper_command import helper_command
from dazedtl.translation.jobs import REPLACED
from dazedtl.translation.operations import (
    execute,
    lifecycle,
    lifecycle_path,
    require_baseline,
    take_census,
    verify_guided_review,
)
from dazedtl.translation.project import DEFAULTS, WORK, ProjectWorkspace, scope
from dazedtl.translation.requests import plan_input
from dazedtl.translation.results import EXPORT, Results
from dazedtl.translation.run_compiler import CENSUS_UNCOVERED, SCOPE_RULES
from dazedtl.translation.service import IMAGE_UNITS, Translation

from tests.fixtures import old_backup


class Engine:
    def __init__(self, source):
        self.source = source
        self.reports = []
        self.pending = []
        self.branch = "main"
        self.checkpoints = []

    def git_status(self, source, *_args):
        return {
            "repo_root": str(source),
            "configured": True,
            "original_version": "1.0",
            "translation_version": "1.0",
            "current_branch": self.branch,
            "translation_branch": "main",
            "pending_operations": self.pending,
            "asset_sync_pending": False,
        }

    def compile(self, _root, _options, plan, language):
        return [
            {
                "context": {
                    "system": "Translate into " + language,
                    "glossary": "Approved names",
                    "sfx_reference": "Advisory SFX",
                    "request_instructions": batch.get("instruction_key", ""),
                    "preceding_japanese_source_context": batch.get(
                        "source_context", ""
                    ),
                    "user": json.dumps(
                        {"sources": batch["sources"], "speakers": batch.get("speakers")}
                    ),
                    "reference_translations": {"matches": {}},
                }
            }
            for batch in plan["batches"]
        ]

    def glossary_terms(self, _source):
        return getattr(self, "glossary", [])

    def census_decoders(self, _root, _workdir):
        def undecodable(*_args):
            raise ValueError("No such data in this fixture.")

        return SimpleNamespace(
            marshal=undecodable, rgssad=undecodable, wolf=undecodable
        )

    def payload(self, request, configuration):
        return {
            "model": configuration["model"],
            "messages": [{"role": "user", "content": request["context"]["user"]}],
        }

    def detect(self, _source):
        return "MVMZ"

    def release_stage(self, _source, copy, kind, destination):
        shutil.move(copy, destination)
        return {"kind": kind or "game", "source": "", "target": ""}

    def game_update(self, _source, _defaults, _action=None, _repo=None):
        return ABSENT

    def documents(self, _source):
        return {}

    def prepare(self, source, _options, *, refresh=True):
        self.refreshed = refresh
        return {"skill": "SKILL.md", "setup": str(Path(source) / "setup.md")}

    def pending_checkpoint(self, _source, change, _named=()):
        self.checkpoints.append(f"{change.stage}: {change.summary}")

    def progress(self, _source, _options, report=None, **_kwargs):
        if report is not None:
            self.reports.append(deepcopy(report))
        return self.reports[-1] if self.reports else {}

    def batch_supported(self, _configuration):
        return "openai"

    def batch_factor(self, provider):
        return 0.5 if provider else None

    def batch_limits(self, _configuration):
        # OpenAI's own endpoint also caps the input tokens a Batch queues.
        return [50, 100000, 1000000]

    def input_tokens(self, parameters):
        return len(json.dumps(parameters))

    def token_count(self, text):
        return len(text)

    def source_bindings(self, _source, _paths):
        return {}

    def verify_bindings(self, _source, bindings):
        if bindings:
            raise ValueError("Fixture sources are independent files.")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "game"
        self.game.mkdir()
        write_json(self.game / "source.json", {"line": "はい。"})
        self.profile = self.root / "profile"
        self.projects = Projects(self.profile)
        self.record = self.projects.open(
            {"source": str(self.game), "engine": "Investigation pending"}
        )
        self.identity = self.record["id"]
        self.project = ProjectWorkspace(self.game)
        self.project.save(
            self.project.read()["revision"], {**DEFAULTS, "include_images": False}
        )
        connection = {
            "id": "connection",
            "name": "Local provider",
            "provider": "custom",
            "protocol": "openai",
            "endpoint": "https://provider.invalid/v1",
            "secret": "fixture-private-value",
            "keyless": False,
            "organization": "",
            "model": "fixture-model",
            "model_options": {
                "fixture-model": {
                    "pricing": "custom",
                    "inputRate": 1,
                    "outputRate": 2,
                    "entriesPerRequest": 50,
                }
            },
        }
        settings_data = {
            "version": 2,
            "revision": 1,
            "values": {"language": "English"},
            "active": "connection",
            "connections": [connection],
        }
        self.settings_data = settings_data
        self.settings = SimpleNamespace(
            _read=lambda: deepcopy(settings_data),
            _connection=Settings._connection,
            _configured=Settings._configured,
            model_defaults=lambda *_args, **_kwargs: {},
            translation_defaults=lambda: {"batch_supported": True},
            game_update=dict,
            adapter=SimpleNamespace(
                allow_providers=False,
                running=lambda: False,
                workflows=SimpleNamespace(projects={}),
                validate_route=lambda _value: None,
            ),
            prepare_engine=lambda: None,
        )
        self.engine = Engine(self.root)
        self.service = Translation(
            self.profile, self.projects, self.settings, self.engine
        )
        # Organize and compile only start a worker; prepared() runs its
        # operation here instead.
        jobs, start = self.service.jobs, self.service.jobs.start
        jobs.start = lambda identity, project_id: (
            jobs.store.view(jobs.store.record(identity))
            if jobs.store.record(identity)["kind"] == "operation"
            else start(identity, project_id)
        )
        self.plan_path = WORK + "/work/requests.json"
        write_json(
            self.game / self.plan_path,
            {
                "version": 2,
                "complete": True,
                "inputs": ["source.json"],
                "batches": [
                    {
                        "id": "scene",
                        "sources": {"line": "はい。"},
                        "kinds": {"line": "dialogue"},
                        "speakers": {"line": None},
                        "source_context": "Previous exchange",
                    }
                ],
            },
        )

    def prepared(self, operation):
        """Runs the operation organize or compile started, as its worker
        would, and returns the run it saved with organize's counts; a refusal
        raises, as the helper reports it."""
        self.assertEqual(operation["kind"], "operation")
        job, plan = self.service.jobs.store.load(operation["id"], self.identity)
        result = execute(self.engine, self.profile, job, plan, lambda: False)
        job.update(status="complete", result=result)
        self.service.jobs.store.save(job)
        run = self.service.run(self.identity, result["run"])
        return (
            {"run": run, "summary": result["summary"]} if "summary" in result else run
        )

    def test_agent_receipt_review_and_mode_switch_keep_the_same_saved_work(self):
        raw = read_json(self.game / self.plan_path)
        note = (
            "Check whether this answer affirms the visitor's question or the guard's."
        )
        raw["batches"][0]["qa_notes"] = {"line": note}
        write_json(self.game / self.plan_path, raw)
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        self.assertEqual(run["qa_requests"], [{"id": "scene", "index": 0, "notes": 1}])
        preview = self.service.request(self.identity, run["id"], 0)
        self.assertEqual(preview["request"]["context"]["qa_notes"], {"line": note})
        receipt = WORK + "/work/result.json"
        write_json(
            self.game / receipt,
            {
                "request_sha256": preview["request"]["fingerprint"],
                "translations": {"line": "Yes."},
            },
        )
        accepted = self.service.accept(self.identity, run["id"], "scene", receipt)
        self.assertEqual(accepted["accepted_units"], 1)
        self.assertEqual(accepted["status"], "complete")
        # The finished run, and each later report, save the assistant's work
        # as a checkpoint of the phase it was done in.
        report = read_json(self.game / (WORK + "/progress-report.json"))
        write_json(
            self.game / (WORK + "/work/injection.json"),
            {**report, "phase": "injection"},
        )
        self.service.progress(self.identity, WORK + "/work/injection.json")
        self.assertEqual(
            self.engine.checkpoints,
            ["Assistant-led: Translation", "Assistant-led: Translation"],
        )
        self.service.progress(self.identity, WORK + "/work/injection.json")
        self.assertEqual(self.engine.checkpoints[-1], "Assistant-led: Injection")
        report = read_json(self.game / (WORK + "/progress-report.json"))
        report.update(phase=None)
        report["phases"].update(
            translation="complete",
            injection="complete",
            qa="complete",
            patch="complete",
        )
        write_json(self.game / (WORK + "/progress-report.json"), report)
        self.service.review(
            self.identity, run["id"], "scene", preview["request"]["fingerprint"]
        )
        preview = self.service.request(self.identity, run["id"], 0)
        # The assistant reads an accepted request back for a correction.
        check_response("translation_request", preview)
        requests = self.service.requests(self.identity, run["id"])
        check_response("translation_requests", requests)
        self.assertEqual(requests, [{"id": "scene", "state": "accepted"}])
        reviewed = preview["result"]
        self.assertIn("line", reviewed["reviewed"])
        index = read_json(self.game / (WORK + "/work/translation-units.json"))
        exported = read_json(self.game / index["parts"][0])["units"][0]
        self.assertEqual(
            (exported["kind"], exported["speaker"], exported["qa_note"]),
            ("dialogue", None, note),
        )
        self.assertEqual(self.engine.reports[-1]["phases"]["qa"], "complete")
        selected = self.project.read()
        self.service.save(
            self.identity, selected["revision"], {**selected["options"], "mode": "live"}
        )
        reused = self.prepared(self.service.compile(self.identity, self.plan_path))
        self.assertEqual(reused["status"], "complete")
        self.assertEqual(reused["quote"]["requests"], 0)
        self.assertEqual(self.engine.reports[-1]["phases"]["qa"], "complete")
        _job, frozen = self.service.jobs.store.load(reused["id"])
        self.assertNotIn("secret", frozen["configuration"])
        self.assertNotIn("fixture-private-value", json.dumps(frozen))
        self.assertIn(note, frozen["requests"][0]["params"]["messages"][0]["content"])
        write_json(
            self.game / receipt,
            {
                "request_sha256": preview["request"]["fingerprint"],
                "translations": {"line": "That's right."},
                "replaces_sha256": reviewed["result_sha256"],
            },
        )
        self.service.accept(self.identity, reused["id"], "scene", receipt)
        corrected = self.service.request(self.identity, reused["id"], 0)
        self.assertNotIn("reviewed", corrected["result"])
        self.assertEqual(corrected["request"]["context"]["qa_notes"]["line"], note)

    def test_saving_a_request_rebuilds_only_its_part_of_the_progress_export(self):
        # The export held every line of the run, so each accepted receipt
        # reread every saved result and rewrote every line.
        units = WORK + "/work/source-units.json"
        write_json(
            self.game / units,
            {
                "version": 1,
                "units": [
                    {"id": "a/1", "scene": "a", "source": "はい。"},
                    {"id": "b/1", "scene": "b", "source": "いいえ。"},
                ],
            },
        )
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        # Files written this moment count as settled, so their parts are kept.
        with (
            patch("dazedtl.translation.results.PART_REQUESTS", 1),
            patch("util.freshness.SETTLED_NS", -1),
        ):
            run = self.prepared(self.service.organize(self.identity, units))["run"]
            _job, plan = self.service.jobs.store.load(run["id"])
            first, second = plan["requests"]
            receipt = WORK + "/work/receipt.json"
            for request, text in ((first, "Yes."), (second, "No.")):
                write_json(
                    self.game / receipt,
                    {
                        "request_sha256": request["fingerprint"],
                        "translations": {request["id"]: text},
                    },
                )
                read = []
                get = Results.get

                def spy(results, request, *args):
                    read.append(request["id"])
                    return get(results, request, *args)

                with patch.object(Results, "get", spy):
                    self.service.accept(
                        self.identity, run["id"], request["id"], receipt
                    )
                self.assertNotIn(
                    first["id"] if request is second else second["id"], read
                )
            index = read_json(self.game / EXPORT)
            self.assertEqual(
                [
                    read_json(self.game / part)["units"][0]["translation"]
                    for part in index["parts"]
                ],
                ["Yes.", "No."],
            )
            # An export from before parts, with the same translations, is
            # replaced without reopening injection and QA.
            results = Results(self.game)
            legacy = results.units(plan["requests"], results.listing())
            write_json(
                self.game / EXPORT, {"complete": plan["complete"], "units": legacy}
            )
            self.assertEqual(results.export(plan), (EXPORT, False))
            self.assertEqual(read_json(self.game / EXPORT), index)

    def test_organized_lines_are_translated_declined_finished_and_read_back_by_id(self):
        units = WORK + "/work/source-units.json"
        write_json(
            self.game / units,
            {
                "version": 1,
                "units": [
                    {
                        "id": "a/1",
                        "scene": "a",
                        "source": "はい。",
                        "kind": "dialogue",
                        "speaker": "リリ",
                    },
                    {"id": "b/1", "scene": "b", "source": "いいえ。"},
                ],
            },
        )
        with self.assertRaisesRegex(ValueError, "--complete"):
            self.service.organize(self.identity, units)
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        organized = self.prepared(self.service.organize(self.identity, units))
        self.assertEqual(organized["run"]["requests"], 2)
        self.assertEqual(organized["summary"]["named_speakers"], 1)
        self.assertNotIn("はい", json.dumps(organized, ensure_ascii=False))
        plan = read_json(self.game / organized["summary"]["plan"])
        self.assertEqual(plan["inputs"], [units])
        run = organized["run"]["id"]
        preview = self.service.request(self.identity, run, 0)
        self.assertEqual(preview["request"]["context"]["speakers"], {"a/1": "リリ"})
        # A request the assistant won't translate is set aside so it carries
        # on; another model finishes it once nothing else is pending.
        declined = self.service.decline(self.identity, run, "b/1", "Declined")
        self.assertEqual(
            (declined["counts"]["declined"], declined["declined_units"]), (1, 1)
        )
        with self.assertRaisesRegex(ValueError, "still translating"):
            self.service.finish(self.identity, run)
        receipt = WORK + "/work/receipt.json"
        write_json(
            self.game / receipt,
            {
                "request_sha256": preview["request"]["fingerprint"],
                "translations": {"a/1": "Yes."},
            },
        )
        self.service.accept(self.identity, run, "a/1", receipt)
        with self.assertRaisesRegex(ValueError, "already has a saved translation"):
            self.service.decline(self.identity, run, "a/1", "Not here")
        # The injector reads translations by line ID from a file; the reply
        # carries counts only.
        written = self.service.results(self.identity, run)
        self.assertEqual(
            (written["translated"], written["missing"]), (1, {"declined": 1})
        )
        self.assertEqual(
            read_json(self.game / written["path"]),
            {
                "run_id": run,
                "translations": {"a/1": "Yes."},
                "missing": {"b/1": "declined"},
            },
        )
        prompt = self.service.translator_prompt(self.identity, run)["handoff"]
        self.assertIn("- 1: b/1", prompt)
        self.assertIn(f"accept --run {run}", prompt)
        finishing = self.prepared(self.service.finish(self.identity, run))
        self.assertEqual(
            (finishing["mode"], finishing["finishes"], finishing["quote"]["requests"]),
            ("batch", run, 1),
        )
        # The project stays in Assistant only; the estimate keeps its own mode.
        record = self.service.jobs.store.record(finishing["id"])
        self.assertFalse(
            self.service.job_views([record], "agent")[0]["settings_changed"]
        )
        # Approval gets past the settings check; this test app sends nothing.
        # It leaves compiling every request again to the run's worker.
        with (
            patch.object(self.engine, "compile", side_effect=AssertionError),
            self.assertRaisesRegex(ValueError, "Provider execution is disabled"),
        ):
            self.service.start(
                self.identity, finishing["id"], finishing["approval_token"]
            )
        _job, frozen = self.service.jobs.store.load(finishing["id"])
        request = frozen["requests"][1]
        self.assertEqual(
            request["fingerprint"],
            self.service.request(self.identity, run, 1)["request"]["fingerprint"],
        )
        write_json(
            self.game / receipt,
            {"request_sha256": request["fingerprint"], "translations": {"b/1": "No."}},
        )
        self.service.accept(self.identity, finishing["id"], "b/1", receipt)
        settled = self.service.run(self.identity, run)
        self.assertEqual(
            (settled["status"], settled["declined_units"]), ("complete", 0)
        )
        self.assertEqual(self.service.results(self.identity, run)["missing"], {})
        write_json(
            self.game / units,
            {"version": 1, "units": [{"id": "a/1", "scene": "a", "source": "うん。"}]},
        )
        with self.assertRaisesRegex(ValueError, "Organize them again"):
            self.service.results(self.identity, run)

    def test_complete_needs_the_tools_census_covered_not_the_assistants_word(self):
        def line(code, *parameters):
            return {"code": code, "indent": 0, "parameters": list(parameters)}

        (self.game / "source.json").unlink()
        (self.game / "data").mkdir()
        page = [
            line(101, "", 0, 0, 2, "リリ"),
            line(401, "はい。"),
            line(108, "メモ"),
            line(401, "秘密の場面です。"),
        ]
        write_json(
            self.game / "data/Map001.json",
            {"events": [None, {"name": "", "pages": [{"list": page}]}]},
        )

        def back_up():
            original_files.record(self.game, original_files.PREPARED)

        def census():
            take_census(
                self.engine,
                self.profile,
                self.identity,
                self.game,
                lifecycle(self.profile, self.identity),
                None,
                lambda: False,
                lambda _message: None,
            )

        back_up()
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        units = WORK + "/work/source-units.json"
        write_json(
            self.game / units,
            {"version": 1, "units": [{"id": "a", "scene": "s", "source": "はい。"}]},
        )
        with self.assertRaisesRegex(ValueError, "Run census first"):
            self.prepared(self.service.organize(self.identity, units, True))
        census()
        # The assistant's extractor skipped a line: the census names its
        # field and location, never its text.
        with self.assertRaises(ValueError) as refused:
            self.prepared(self.service.organize(self.identity, units, True))
        self.assertIn("[code=401]/parameters/0: 1", str(refused.exception))
        self.assertNotIn("秘密", str(refused.exception))
        missing = read_json(self.game / CENSUS_UNCOVERED)["uncovered"]
        self.assertEqual(
            [entry["location"] for entry in missing],
            [
                "events/1/pages/0/list/0/parameters/4",
                "events/1/pages/0/list/3/parameters/0",
            ],
        )
        write_json(
            self.game / SCOPE_RULES,
            {
                "version": 1,
                "rules": [{"kind": "rpgmaker:map", "field": "**", "reason": "comment"}],
            },
        )
        with self.assertRaisesRegex(ValueError, "player reads"):
            self.prepared(self.service.organize(self.identity, units, True))
        (self.game / SCOPE_RULES).unlink()
        write_json(
            self.game / units,
            {
                "version": 1,
                "units": [
                    {"id": "a", "scene": "s", "source": "はい。"},
                    {"id": "b", "scene": "s", "source": "秘密の場面です。"},
                ],
            },
        )
        # Nameplates are covered by the glossary, comments set aside built in.
        self.engine.glossary = ["リリ"]
        organized = self.prepared(self.service.organize(self.identity, units, True))
        coverage = organized["summary"]["coverage"]
        self.assertEqual(
            (coverage["uncovered"], coverage["set_aside"], coverage["source"]),
            (0, 1, "tool"),
        )
        self.assertEqual(self.service.state(self.identity)["coverage"]["extracted"], 3)
        # A patch needs every accepted unit exported, against the same census.
        with self.assertRaisesRegex(ValueError, "fewer than the 2"):
            self.service.require_inventory(self.identity, 1)
        self.service.require_inventory(self.identity, 2)
        page.append(line(401, "追加の台詞。"))
        write_json(
            self.game / "data/Map001.json",
            {"events": [None, {"name": "", "pages": [{"list": page}]}]},
        )
        back_up()
        with self.assertRaisesRegex(ValueError, "Run census again"):
            self.prepared(self.service.organize(self.identity, units, True))
        census()
        with self.assertRaisesRegex(ValueError, "after the latest census"):
            self.service.require_inventory(self.identity, 2)

    def test_unversioned_saved_run_keeps_results_and_approval_through_compatible_compiler_update(
        self,
    ):
        raw = {
            "complete": True,
            "inputs": ["source.json"],
            "batches": [{"id": "scene", "sources": {"line": "はい。"}}],
        }
        write_json(self.game / self.plan_path, raw)
        self.assertEqual(plan_input(raw, allow_legacy=True), raw)
        with self.assertRaises(ValueError):
            self.prepared(self.service.compile(self.identity, self.plan_path))
        selected = self.project.read()["options"]
        cfg = configuration(self.settings, "live")
        requests, _compiler = compile_requests(
            self.engine, self.game, selected, raw, cfg["language"]
        )
        for row in requests:
            row["params"] = self.engine.payload(row, cfg)
        frozen = {
            "version": 1,
            "kind": "translation",
            "source": str(self.game),
            "options": selected,
            "scope_sha256": scope(selected),
            "configuration": cfg,
            "requests": requests,
            "complete": True,
            "evidence": evidence(self.game, [self.plan_path, "source.json"]),
            "original_bindings": {},
            "compiler": "previous-compiler",
            "input_path": self.plan_path,
            "batch_limits": None,
        }
        store = self.service.jobs.store
        job = store.create(self.identity, frozen, {"cost": 1})
        store.authorize(job)
        folder = store.folder(job["id"])
        original = {
            name: (folder / name).read_bytes()
            for name in ("plan.json", "authorization.json")
        }
        self.service.validate_current(self.identity, frozen)
        receipt = WORK + "/work/legacy-result.json"
        write_json(
            self.game / receipt,
            {
                "request_sha256": requests[0]["fingerprint"],
                "translations": {"line": "Yes."},
            },
        )
        self.service.accept(self.identity, job["id"], "scene", receipt)
        self.service.review(
            self.identity, job["id"], "scene", requests[0]["fingerprint"]
        )
        preview = self.service.request(self.identity, job["id"], 0)
        self.assertEqual(preview["result"]["translations"], {"line": "Yes."})
        self.assertNotIn("line_kinds", preview["request"]["context"])
        self.assertEqual(
            original, {name: (folder / name).read_bytes() for name in original}
        )
        self.assertTrue(store.authorized(store.record(job["id"])))
        self.assertEqual(store.view(store.record(job["id"]))["qa_requests"], [])
        with (
            patch.object(
                self.engine, "payload", return_value={"changed": "provider parameters"}
            ),
            self.assertRaisesRegex(ValueError, "payload changed"),
        ):
            self.service.validate_current(self.identity, frozen)
        changed = deepcopy(requests)
        changed[0]["context"]["system"] = "Changed guidance"
        with (
            patch.object(self.engine, "compile", return_value=changed),
            self.assertRaises(ValueError),
        ):
            self.service.validate_current(self.identity, frozen)
        # An import compiles only its own request, which matches the whole
        # plan's compile until its guidance changes.
        self.service.validate_current(self.identity, frozen, index=0)
        compile = self.engine.compile

        def guidance_changed(*args):
            rows = compile(*args)
            rows[0]["context"]["system"] = "Changed guidance"
            return rows

        with (
            patch.object(self.engine, "compile", guidance_changed),
            self.assertRaisesRegex(ValueError, "Shared guidance"),
        ):
            self.service.validate_current(self.identity, frozen, index=0)

    def test_changed_inputs_cannot_approve_or_bless_old_results(self):
        selected = self.project.read()
        self.service.save(
            self.identity, selected["revision"], {**selected["options"], "mode": "live"}
        )
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        _job, frozen = self.service.jobs.store.load(run["id"])
        before = (
            (self.game / (WORK + "/progress.json")).read_bytes()
            if (self.game / (WORK + "/progress.json")).exists()
            else None
        )
        reports = len(self.engine.reports)
        # Settings that shape the requests make the shown cost stale;
        # restoring them makes it current. New rates alone price it again.
        rates = self.settings_data["connections"][0]["model_options"]["fixture-model"]

        def outdated():
            jobs = self.service.state(self.identity)["jobs"]
            return next(job for job in jobs if job["id"] == run["id"])[
                "settings_changed"
            ]

        rates["entriesPerRequest"] = 10
        self.assertTrue(outdated())
        with self.assertRaisesRegex(ValueError, "changed after this estimate"):
            self.service.start(self.identity, run["id"], run["approval_token"])
        rates["entriesPerRequest"] = 50
        self.assertFalse(outdated())
        # Catalog prices not looked up since a restart are unknown, which reads
        # as unchanged instead of failing every snapshot.
        rates["pricing"] = "automatic"
        self.assertFalse(outdated())
        # Another model outdates it even before its prices are looked up.
        connection = self.settings_data["connections"][0]
        connection["model"] = "other-model"
        self.assertTrue(outdated())
        connection["model"] = "fixture-model"
        rates["pricing"] = "custom"
        write_json(self.game / "source.json", {"line": "変更。"})
        with self.assertRaises(ValueError):
            self.service.start(self.identity, run["id"], run["approval_token"])
        self.assertFalse(
            self.service.jobs.store.authorized(
                self.service.jobs.store.load(run["id"])[0]
            )
        )
        with self.assertRaises(ValueError):
            self.service.refresh_progress(self.identity, frozen)
        self.assertEqual(len(self.engine.reports), reports)
        if before is not None:
            self.assertEqual(
                (self.game / (WORK + "/progress.json")).read_bytes(), before
            )

    def test_a_model_switch_prices_a_waiting_estimate_again(self):
        selected = self.project.read()
        self.service.save(
            self.identity, selected["revision"], {**selected["options"], "mode": "live"}
        )
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        connection = self.settings_data["connections"][0]
        options = connection["model_options"]
        options["half-price"] = {**options["fixture-model"], "inputRate": 0.5}
        options["half-price"]["outputRate"] = 1
        options["gpt-5.6-terra"] = options["half-price"]

        def view():
            jobs = self.service.state(self.identity)["jobs"]
            return next(job for job in jobs if job["id"] == run["id"])

        # Its requests carry the same text, so the switch only prices them.
        connection["model"] = "half-price"
        repriced = view()
        self.assertFalse(repriced["settings_changed"])
        self.assertEqual(repriced["quote"]["model"], "half-price")
        self.assertEqual(
            repriced["quote"]["input_tokens"], run["quote"]["input_tokens"]
        )
        self.assertAlmostEqual(repriced["quote"]["cost"], run["quote"]["cost"] / 2)
        # GPT-5.6 sends its instructions in separately cached blocks, so its
        # token counts differ.
        connection["model"] = "gpt-5.6-terra"
        self.assertTrue(view()["settings_changed"])
        # Approval binds to the price shown: the quote's own token no longer
        # approves it, and the shown price's token freezes the run with it.
        connection["model"] = "half-price"
        with self.assertRaisesRegex(ValueError, "changed after this estimate"):
            self.service.start(self.identity, run["id"], run["approval_token"])
        token = view()["approval_token"]
        connection["model"] = "fixture-model"
        with self.assertRaisesRegex(ValueError, "price changed"):
            self.service.start(self.identity, run["id"], token)
        connection["model"] = "half-price"
        with self.assertRaisesRegex(ValueError, "Provider execution is disabled"):
            self.service.start(self.identity, run["id"], token)
        job, plan = self.service.jobs.store.load(run["id"])
        self.assertTrue(self.service.jobs.store.authorized(job))
        self.assertEqual(job["quote"], repriced["quote"])
        self.assertEqual(
            {row["params"]["model"] for row in plan["requests"]}, {"half-price"}
        )
        # Redoing an estimate GPT-5.6 can't price repeats its preparation.
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        connection["model"] = "gpt-5.6-terra"
        again = self.prepared(self.service.reestimate(self.identity, run["id"]))
        self.assertEqual(again["quote"]["model"], "gpt-5.6-terra")

    def test_reports_count_images_from_the_image_manager(self):
        # The assistant's reports must carry the Image Manager's records, or
        # translation never completes and packaging stays blocked.
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "include_images": True},
        )
        records = {"complete": False, "units": []}
        self.service.image_units = lambda _identity: records
        path = WORK + "/work/report.json"
        write_json(
            self.game / path, {"phase": "translation", "images": "my-images.json"}
        )
        self.service.progress(self.identity, path)
        self.assertEqual(self.engine.reports[-1]["images"], IMAGE_UNITS)
        self.assertEqual(read_json(self.game / IMAGE_UNITS), records)
        # Applying images republishes the last report with the new counts.
        records = {"complete": True, "units": []}
        self.service.sync_images(self.identity)
        self.assertEqual(read_json(self.game / IMAGE_UNITS), records)
        self.assertEqual(self.engine.reports[-1]["phase"], "translation")

    def test_an_api_run_answers_its_approval_and_keeps_later_questions(self):
        selected = self.project.read()
        self.service.save(
            self.identity, selected["revision"], {**selected["options"], "mode": "live"}
        )
        # Only the app's button approves, and only an estimate still waiting:
        # not one the user discarded, which sent nothing in any mode, nor one
        # a newer estimate replaced, nor any through the assistant's helper.
        discarded = self.prepared(self.service.compile(self.identity, self.plan_path))
        self.assertEqual(
            self.service.stop(self.identity, discarded["id"], True)["status"],
            "canceled",
        )
        stale = self.prepared(self.service.compile(self.identity, self.plan_path))
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        self.assertEqual(
            self.service.run(self.identity, stale["id"])["message"], REPLACED
        )
        job, plan = self.service.jobs.store.load(run["id"])
        path = WORK + "/work/report.json"

        def report(blocker, next_action):
            write_json(
                self.game / path,
                {
                    "phase": "translation",
                    "phases": {"translation": "blocked"},
                    "blocker": blocker,
                    "next_action": next_action,
                },
            )
            self.service.progress(self.identity, path)

        report("Awaiting approval to spend $0.01.", "On approval: start the run.")
        helper = assistant_dispatch(
            SimpleNamespace(closing=False, translation=self.service),
            lambda _name, params: self.service.start(**params),
        )
        with patch.object(self.service.jobs, "start"):
            for item in (discarded, stale):
                with self.assertRaisesRegex(ValueError, "no longer be approved"):
                    self.service.start(
                        self.identity, item["id"], item["approval_token"]
                    )
            with self.assertRaisesRegex(ValueError, "Only the user approves"):
                helper(
                    "translation_start",
                    {
                        "project_id": self.identity,
                        "run_id": run["id"],
                        "approval_token": run["approval_token"],
                    },
                )
            self.assertFalse(self.service.run(self.identity, run["id"])["approved"])
            self.service.start(self.identity, run["id"], run["approval_token"])
        # Progress reminds the user to tell the assistant about the approval.
        self.assertTrue(self.service.run(self.identity, run["id"])["app_approved_at"])
        # The worker's first report as the approved run starts.
        progress_report.refresh(
            self.profile, self.identity, self.engine, plan, started=True
        )
        latest = self.engine.reports[-1]
        self.assertEqual(
            (latest["blocker"], latest["next_action"], latest["phases"]["translation"]),
            ("", progress_report.NEXT_ACTION, "active"),
        )
        # A Batch can wait at the provider for hours; the assistant still reports.
        job["status"] = "running"
        self.service.jobs.store.save(job)
        lock = WorkspaceLock(self.service.jobs.store.folder(run["id"]))
        report("The hero's name is unclear.", "Reply with the hero's name.")
        # The user can hand the prompt back to the assistant during the wait,
        # without rewriting the guidance the run's frozen requests depend on.
        handoff = self.service.prepare(self.identity)["handoff"]
        self.assertIn(helper_command(self.service.workspace, self.identity), handoff)
        self.assertFalse(self.engine.refreshed)
        lock.close()
        preview = self.service.request(self.identity, run["id"], 0)
        receipt = WORK + "/work/result.json"
        write_json(
            self.game / receipt,
            {
                "request_sha256": preview["request"]["fingerprint"],
                "translations": {"line": "Yes."},
            },
        )
        self.service.accept(self.identity, run["id"], "scene", receipt)
        latest = self.engine.reports[-1]
        self.assertEqual(
            (latest["blocker"], latest["next_action"], latest["phases"]),
            (
                "The hero's name is unclear.",
                "Reply with the hero's name.",
                {
                    "translation": "blocked",
                    "injection": "pending",
                    "qa": "pending",
                    "patch": "pending",
                },
            ),
        )

    def test_conflict_recovery_is_a_real_prerequisite(self):
        state = lifecycle(self.profile, self.identity)
        self.engine.pending = ["CHERRY_PICK_HEAD"]
        with self.assertRaises(ValueError):
            require_baseline(self.engine, self.game, DEFAULTS, state)
        # Plugin files and Images, which need no baseline, refuse it too.
        with self.assertRaisesRegex(ValueError, "unfinished Git cherry-pick"):
            self.service.writable(self.identity)
        self.assertTrue(
            require_baseline(
                self.engine, self.game, DEFAULTS, state, allow_pending=True
            )["configured"]
        )
        self.engine.pending = []
        self.engine.branch = "side"
        with self.assertRaises(ValueError) as refused:
            require_baseline(self.engine, self.game, DEFAULTS, state)
        # The workspace states the same reason before any action is refused.
        self.assertIn(
            str(refused.exception), self.service.state(self.identity)["warnings"]
        )
        self.engine.branch = "main"

    def test_current_selection_excludes_drafts_and_secrets_while_saved_runs_keep_their_route(
        self,
    ):
        selected = self.project.read()
        self.service.save(
            self.identity, selected["revision"], {**selected["options"], "mode": "live"}
        )
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        _job, plan = self.service.jobs.store.load(run["id"])
        write_json(self.profile / "settings/settings.json", self.settings_data)
        self.assertEqual(
            worker_secret(self.profile, plan["configuration"]), "fixture-private-value"
        )
        self.settings_data["draft"] = {
            "connections": {"connection": {"model": "unsaved-model"}}
        }
        self.assertEqual(
            connection_summary(self.settings),
            {"name": "Local provider", "model": "fixture-model"},
        )
        self.settings_data["connections"].append(
            {
                **self.settings_data["connections"][0],
                "id": "second",
                "name": "Another provider",
                "model": "next-model",
            }
        )
        self.settings_data["active"] = "second"
        self.assertEqual(
            connection_summary(self.settings),
            {"name": "Another provider", "model": "next-model"},
        )
        self.assertEqual(plan["configuration"]["connection_id"], "connection")
        self.settings_data["active"] = ""
        self.assertIsNone(connection_summary(self.settings))
        changed = deepcopy(self.settings_data)
        changed["connections"][0]["endpoint"] = "https://different.invalid/v1"
        write_json(self.profile / "settings/settings.json", changed)
        with self.assertRaises(ValueError):
            worker_secret(self.profile, plan["configuration"])

    def test_options_draft_matching_the_saved_options_does_not_block_work(self):
        # Turning a choice off and on again leaves a draft the page shows as
        # clean, so it must not refuse the starting prompt, including one an
        # earlier version stored; a real edit still must.
        saved = self.service.options(self.project)
        same = {"revision": saved["revision"], "options": saved["options"]}
        self.service.draft(self.identity, "options", same)
        self.service.clean_drafts(self.identity)
        write_json(
            self.service.draft_path(self.identity), {"options": same, "documents": {}}
        )
        self.service.clean_drafts(self.identity)
        edited = {**saved["options"], "instructions": "Unsaved"}
        self.service.draft(self.identity, "options", {**same, "options": edited})
        with self.assertRaises(ValueError):
            self.service.clean_drafts(self.identity)
        # A stopped game update refuses saving the draft, so finishing or
        # cancelling it must not wait for one: the user had to discard it.
        for action in ("version_continue", "version_abort"):
            job = self.service.operation(self.identity, action, {})
            self.assertEqual(job["action"], action)

    def test_start_over_restores_the_original_and_sets_the_attempt_aside(self):
        # Starting over must put every original file back as one checkpoint,
        # keeping the attempt in the game's Git history and the record of its
        # original files, and move what Git doesn't keep aside instead of
        # deleting it, keeping save games, the notes the user keeps and the
        # project's options; a paid API run still waiting at its provider
        # must refuse it.
        from dazedtl.compatibility.checkpoint_commits import _git
        from util.len_git import setup_git
        from util.len_translation import LenProject

        original_files.record(self.game, original_files.FOUND)
        setup_git(LenProject(self.game), version="1.0", current_is_untranslated=True)
        self.projects.choose_method(self.identity, "len")
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        job, _plan = self.service.jobs.store.load(run["id"])
        job["status"] = "waiting"
        self.service.jobs.store.save(job)
        with self.assertRaisesRegex(ValueError, "Pause this project's API run"):
            self.service.start_over(self.identity, True)
        original = (self.game / "source.json").read_bytes()
        write_json(self.game / "source.json", {"line": "Yes."})
        (self.game / "js").mkdir()
        (self.game / "js/Forge.js").write_text("added by setup", encoding="utf-8")
        # The game's plugin list makes the folder a game's for the write check.
        (self.game / "js/plugins.js").write_text("var $plugins = [];", encoding="utf-8")
        (self.game / "save").mkdir()
        (self.game / "save/file1.rmmzsave").write_text("progress", encoding="utf-8")
        (self.game / WORK / "progress.json").write_text("{}", encoding="utf-8")
        # The playtest's fixes for this attempt; the next began from them.
        (self.game / ".dazedtl/playtest").mkdir()
        (self.game / ".dazedtl/playtest/DazedTL_Fixes.js").write_text(
            "// fix", encoding="utf-8"
        )
        glossary = self.game / ".dazedtl/glossary.txt"
        glossary.write_text("Lili (リリ)", encoding="utf-8")
        self.engine.documents = lambda _source: {"glossary": {"path": str(glossary)}}
        records = self.profile / "translation/projects" / self.identity
        write_json(records / "assistant.json", {"seen_at": "2026-10-08T00:00:00"})

        def start_over(keep_context):
            execute(
                self.engine,
                self.profile,
                {"project_id": self.identity},
                {
                    "source": str(self.game),
                    "options": DEFAULTS,
                    "action": "start_over",
                    "arguments": {"keep_context": keep_context},
                },
                lambda: False,
            )
            state = lifecycle(self.profile, self.identity)
            return state, self.game / state["started_over"]["archive"]

        def git(*arguments):
            return _git(self.game, *arguments).stdout

        state, archive = start_over(True)
        self.assertEqual((self.game / "source.json").read_bytes(), original)
        self.assertFalse((self.game / "js").exists())
        self.assertEqual(
            (self.game / "save/file1.rmmzsave").read_text(encoding="utf-8"), "progress"
        )
        # The attempt stays in Git: its edits, then the start over.
        self.assertEqual(
            git("log", "-2", "--format=%s").splitlines(),
            [
                "Assistant-led: Started over from the original game",
                "Edits made outside DazedTL",
            ],
        )
        self.assertEqual(git("show", "HEAD~1:js/Forge.js"), "added by setup")
        self.assertEqual(len(original_files.records(self.game)), 1)
        self.assertTrue((archive / "len-method/progress.json").is_file())
        self.assertFalse((self.game / ".dazedtl/playtest").exists())
        self.assertTrue((archive / "playtest/DazedTL_Fixes.js").is_file())
        self.assertTrue(self.project.path.is_file())
        self.assertEqual(glossary.read_text(encoding="utf-8"), "Lili (リリ)")
        self.assertFalse((records / "assistant.json").exists())
        self.assertFalse((self.game / ".dazedtl/backups").exists())
        # A project set up before original files were kept in Git starts
        # over from its backup. Running it again on the original changes no
        # game file, and lets the notes go when the user chose not to keep
        # them.
        saved = old_backup.snapshot(self.game)
        write_json(
            lifecycle_path(self.profile, self.identity),
            {**state, "source_backup": saved},
        )
        state, archive = start_over(False)
        self.assertEqual(state["source_backup"], saved)
        self.assertEqual((self.game / "source.json").read_bytes(), original)
        self.assertFalse(glossary.exists())
        self.assertEqual(
            (archive / "context/.dazedtl/glossary.txt").read_text(encoding="utf-8"),
            "Lili (リリ)",
        )

    def test_helper_checkpoints_save_through_git_with_dazedtls_own_files(self):
        # The helper's checkpoint once restored originals from the backup and
        # snapshotted the workspace; Git's original branch is authoritative,
        # so it saves what waits in the patch and lets the manifest's files in.
        manifest_path = WORK + "/work/patch-files.json"
        write_json(self.game / manifest_path, ["source.json"])
        main = self.game / "js/main.js"
        main.parent.mkdir()
        main.write_bytes(b"PluginManager.setup($plugins);\n")
        # Set up's update check, which plugins.js loads, and GameUpdate's
        # launcher; a patch without them stops the game at boot.
        check = self.game / "js/plugins/TranslationUpdateCheck.js"
        check.parent.mkdir()
        check.write_text("// Update check\n", encoding="utf-8")
        (self.game / "GameUpdate.bat").write_text("@echo off\n", encoding="utf-8")
        configured = [False]
        original_status = self.engine.git_status
        self.engine.git_status = lambda source, *args: {
            **original_status(source, *args),
            "configured": configured[0],
            "translation_commit": "checkpoint",
        }
        self.engine.audit_scope = lambda *_args: None
        self.engine.runtime_paths = lambda manifest: list(manifest["files"])

        def setup(_source, _options, _version, original, untranslated):
            # Git reads an untranslated game in place, not an unpacked copy.
            self.assertEqual((original, untranslated), ("", True))
            configured[0] = True
            return self.engine.git_status(self.game)

        self.engine.git_setup = setup
        self.engine.checkpoint = Mock()
        self.engine.outside_edits = Mock()
        self.engine.package = Mock(return_value={"path": str(self.root / "patch.zip")})
        self.engine.detect = lambda _source: "Other engine"
        job = {"project_id": self.identity, "id": "b" * 32}

        def operation(action, **arguments):
            return execute(
                self.engine,
                self.profile,
                job,
                {
                    "source": str(self.game),
                    "options": DEFAULTS,
                    "action": action,
                    "arguments": arguments,
                },
                lambda: False,
            )

        # An assistant records the game before its own tools change it, and
        # Git setup the prepared game. A game whose Git is set up holds
        # translation, so it is never recorded as the original.
        configured[0] = True
        self.assertFalse(operation("record_original")["recorded"])
        self.assertEqual(original_files.records(self.game), [])
        configured[0] = False
        self.assertTrue(operation("record_original")["recorded"])
        operation("git_setup", version="1.0", untranslated=True, manifest=manifest_path)
        kinds = [row.kind for row in original_files.records(self.game)]
        self.assertEqual(kinds, [original_files.FOUND, original_files.PREPARED])
        write_json(self.game / "source.json", {"line": "Yes."})
        (self.game / "js/plugins/DazedTL_Fixes.js").write_text(
            "// Fix\n", encoding="utf-8"
        )
        main.write_bytes(b"$plugins.push({});\n" + main.read_bytes())
        delivery.record(self.game, manifest_path, ["source.json"])
        operation("checkpoint", manifest=manifest_path, message="maps 1-20")
        change, named = self.engine.checkpoint.call_args.args[1:]
        self.assertEqual(
            (change.summary, change.stage, change.action),
            ("maps 1-20", "Assistant-led", "checkpoint"),
        )
        # DazedTL's own files join a manifest that leaves them out: Set up's
        # and the playtest's fixes with the main.js loading them.
        self.assertEqual(
            sorted(named),
            [
                "GameUpdate.bat",
                "js/main.js",
                "js/plugins/DazedTL_Fixes.js",
                "js/plugins/TranslationUpdateCheck.js",
                "source.json",
            ],
        )
        # Without a manifest it saves what waits in the patch.
        operation("checkpoint")
        self.assertEqual(self.engine.checkpoint.call_args.args[2], ())
        state = lifecycle(self.profile, self.identity)
        self.assertNotIn("checkpoint", state)
        self.assertNotIn("workspace_backup", state)
        operation("package")
        # Edits made outside DazedTL get their own checkpoint before the
        # package's.
        self.engine.outside_edits.assert_called_once()
        self.assertEqual(self.engine.checkpoint.call_args.args[1].action, "package")
        # Packaging takes the manifest QA was recorded for.
        other_manifest = WORK + "/work/other-patch.json"
        write_json(self.game / other_manifest, ["source.json"])
        operation("checkpoint", manifest=other_manifest)
        with self.assertRaisesRegex(ValueError, "runtime manifest before packaging"):
            operation("package")
        official = self.root / "new-official"
        official.mkdir()
        (official / "native.bin").write_bytes(b"new official bytes\r\n")
        staged = operation("stage_update", official=str(official), version="1.1")
        self.assertEqual(
            (Path(staged["official"]) / "native.bin").read_bytes(),
            b"new official bytes\r\n",
        )
        # The new release's files are kept in the game's Git as they came.
        update = original_files.records(self.game)[-1]
        self.assertEqual(
            (update.commit, update.kind, update.version),
            (staged["original"], original_files.UPDATE, "1.1"),
        )
        self.assertEqual(
            list(original_files.files(self.game, update.commit)), ["native.bin"]
        )
        # A staged patch compares only as a patch: as a complete game it
        # would remove every file it leaves out.
        patched = execute(
            self.engine,
            self.profile,
            {**job, "id": "c" * 32},
            {
                "source": str(self.game),
                "options": DEFAULTS,
                "action": "stage_update",
                "arguments": {
                    "official": str(official),
                    "version": "1.1",
                    "patch": True,
                },
            },
            lambda: False,
        )
        self.assertTrue(patched["patch"])
        store = self.service.jobs.store
        stage = store.create(
            self.identity,
            {"version": 1, "kind": "operation", "source": str(self.game)},
        )
        store.save(
            {**stage, "action": "stage_update", "status": "complete", "result": patched}
        )
        with self.assertRaisesRegex(ValueError, "staged as a patch"):
            self.service.operation(
                self.identity,
                "version_preview",
                {
                    "official": patched["official"],
                    "version": "1.1",
                    "patch_overlay": False,
                },
            )

    def test_runtime_changes_invalidate_delivery_even_if_qa_report_is_unchanged(self):
        for action in ("guided_review", "guided_package", "release_patch"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.service.operation(self.identity, action, {})
        path = WORK + "/work/patch-files.json"
        write_json(self.game / path, ["source.json"])
        delivery.record(self.game, path, ["source.json"])
        delivery.verify(self.game, full=True)
        self.engine.runtime_paths = lambda manifest: manifest["files"]
        guided_manifest = ".dazedtl/guided/runtime-manifest.json"
        write_json(self.game / guided_manifest, {"files": ["source.json"]})
        execute(
            self.engine,
            self.profile,
            {"project_id": self.identity},
            {
                "source": str(self.game),
                "options": DEFAULTS,
                "action": "guided_review",
                "arguments": {"manifest": guided_manifest},
            },
            lambda: False,
        )
        verify_guided_review(self.game, lifecycle(self.profile, self.identity))
        # A new source pass invalidates release review even when runtime bytes
        # have not changed yet; it must not revive an earlier playtest attestation.
        source_inputs = "engine/workflows/guided/source-inputs.json"
        inputs = {"version": 1, "inputs": {}}
        write_json(self.profile / source_inputs, inputs)
        execute(
            self.engine,
            self.profile,
            {"project_id": self.identity},
            {
                "source": str(self.game),
                "options": DEFAULTS,
                "action": "guided_review",
                "arguments": {
                    "manifest": guided_manifest,
                    "source_inputs": source_inputs,
                    "source_inputs_sha256": digest(inputs),
                },
            },
            lambda: False,
        )
        verify_guided_review(
            self.game, lifecycle(self.profile, self.identity), self.profile, self.engine
        )
        write_json(
            self.profile / source_inputs, {**inputs, "last_refresh": "new-source-pass"}
        )
        with self.assertRaises(ValueError):
            verify_guided_review(
                self.game,
                lifecycle(self.profile, self.identity),
                self.profile,
                self.engine,
            )
        write_json(self.game / "source.json", {"line": "Changed after review"})
        with self.assertRaises(ValueError):
            delivery.verify(self.game, full=True)
        with self.assertRaises(ValueError):
            verify_guided_review(self.game, lifecycle(self.profile, self.identity))
