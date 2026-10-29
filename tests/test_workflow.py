"""A small project goes from source-bound plans to reusable accepted work."""

import json
import os
import shutil
import unittest
from copy import deepcopy
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.api.contracts.validation import check_response
from dazedtl.api.server import assistant_dispatch
from dazedtl.compatibility import estimate_prices, original_files
from dazedtl.projects.store import Projects
from dazedtl.settings.execution import configuration, connection_summary, worker_secret
from dazedtl.settings.store import Settings
from dazedtl.storage import WorkspaceLock, write_json
from dazedtl.translation import (
    delivery,
    name_codes,
    organize,
    progress_report,
    publication,
)
from dazedtl.translation.compilation import compile_requests
from dazedtl.translation.files import digest, evidence, read_json
from dazedtl.translation.game_update import ABSENT
from dazedtl.translation.helper_command import helper_command
from dazedtl.translation.jobs import REPLACED
from dazedtl.translation.operations import (
    census_path,
    execute,
    lifecycle,
    lifecycle_path,
    require_baseline,
    take_census,
)
from dazedtl.translation.project import DEFAULTS, WORK, ProjectWorkspace, scope
from dazedtl.translation.release import current
from dazedtl.translation.requests import (
    LINE_KEYS,
    SKILL_USERS,
    logical_request,
    plan_input,
    provider_view,
)
from dazedtl.translation.results import EXPORT, Results, review_digest
from dazedtl.translation.run_compiler import (
    CENSUS_UNCOVERED,
    SCOPE_RULES,
    coverage_path,
    inventory_path,
)
from dazedtl.translation.service import IMAGE_UNITS, Translation
from dazedtl.translation.skill_users import for_batch
from util import provider_costs

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

    def compile(
        self, _root, _options, plan, language, skill_users=None, actor_variables=None
    ):
        self.actor_variables = actor_variables

        def users(batch):
            notes, _names = for_batch(skill_users or {}, batch["sources"])
            return {"skill_users": notes} if notes else {}

        return [
            {
                "context": {
                    **users(batch),
                    "system": "Translate into " + language,
                    "glossary": getattr(self, "glossary_text", "Approved names"),
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

    def prepare(self, source, _options, *, language="English", refresh=True):
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

    @staticmethod
    def openai_cache(_requests):
        return {"cache_read_tokens": 0, "cacheable_tokens": 0}

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
            "version": 3,
            "revision": 1,
            "sourceLanguage": "Japanese",
            "values": {"language": "English"},
            "active": "connection",
            "connections": [connection],
        }
        self.settings_data = settings_data
        self.settings = SimpleNamespace(
            _read=lambda: deepcopy(settings_data),
            language=lambda: settings_data["values"]["language"],
            source_language=lambda: settings_data["sourceLanguage"],
            convert_quotes=lambda: True,
            _connection=Settings._connection,
            _configured=Settings._configured,
            connection_summary=lambda: connection_summary(self.settings),
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

    def test_lines_without_source_letters_are_written_without_a_request(self):
        # Guided never sends 「……」 or ！？; it writes them in English form.
        units = WORK + "/work/source-units.json"
        write_json(
            self.game / units,
            {
                "version": 1,
                "units": [
                    {"id": "a/1", "scene": "a", "source": "はい。"},
                    {"id": "a/2", "scene": "a", "source": "「……」\n\\C[2]！？"},
                    # Its token holds a mark the English form would change.
                    {
                        "id": "a/3",
                        "scene": "a",
                        "source": "【？】",
                        "tokens": ["【？】"],
                    },
                ],
            },
        )
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        organized = self.prepared(self.service.organize(self.identity, units))
        self.assertEqual(organized["summary"]["converted"], 1)
        run = organized["run"]["id"]
        _job, plan = self.service.jobs.store.load(run)
        self.assertEqual(
            [list(request["sources"]) for request in plan["requests"]],
            [["a/1", "a/3"]],
        )
        written = self.service.results(self.identity, run)
        self.assertEqual(written["translated"], 1)
        self.assertEqual(
            read_json(self.game / written["path"])["translations"],
            {"a/2": '"……"\n\\C[2]!?'},
        )
        Results(self.game).export(plan)
        rows = [
            row
            for part in read_json(self.game / EXPORT)["parts"]
            for row in read_json(self.game / part)["units"]
        ]
        self.assertEqual(
            [(row["source_id"], row.get("converted")) for row in rows],
            [("a/1", None), ("a/3", None), ("a/2", True)],
        )
        # It counts as translated and reviewed, as Guided reviews no such line.
        self.assertEqual(
            rows[2]["reviewed_sha256"],
            review_digest(rows[2]["source"], rows[2]["translation"]),
        )

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
        # Text QA leaves its lines to that model (text_qa.untranslated).
        self.assertEqual(
            self.service.jobs.store.declined_sources(self.identity), ["いいえ。"]
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
            self.service.job_views([record], "agent", self.game)[0]["settings_changed"]
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
        self.assertEqual(self.service.jobs.store.declined_sources(self.identity), [])
        self.assertEqual(self.service.results(self.identity, run)["missing"], {})
        # A result saved before "Declined." read as a refusal note is no
        # translation: the run waits on its request again, which the
        # assistant may now decline.
        path = self.game / Results(self.game).relative(preview["request"])
        legacy = read_json(path)
        del legacy["refusal_rules"]
        legacy["translations"] = {"a/1": "Declined."}
        legacy["result_sha256"] = digest(legacy["translations"])
        write_json(path, legacy)
        self.assertEqual(
            self.service.results(self.identity, run)["missing"], {"pending": 1}
        )
        self.assertEqual(self.service.run(self.identity, run)["status"], "ready")
        # The run counts it declined, though its refusal note stays saved.
        declined = self.service.decline(self.identity, run, "a/1", "Not here")
        self.assertEqual((declined["status"], declined["declined_units"]), ("ready", 1))
        self.assertEqual(self.service.finish(self.identity, run)["finishes"], run)
        write_json(
            self.game / units,
            {"version": 1, "units": [{"id": "a/1", "scene": "a", "source": "うん。"}]},
        )
        with self.assertRaisesRegex(ValueError, "Organize them again"):
            self.service.results(self.identity, run)

    def test_organizing_again_quotes_only_the_lines_without_a_translation(self):
        # A saved result answered only a request compiled exactly as before,
        # so a glossary edit quoted every line of each request it touched
        # again, and a line a run kept in its source text read translated
        # and was never sent again.
        selected = self.project.read()
        self.service.save(
            self.identity, selected["revision"], {**selected["options"], "mode": "live"}
        )
        units = WORK + "/work/source-units.json"
        write_json(
            self.game / units,
            {
                "version": 1,
                "units": [
                    {"id": "a/1", "scene": "a", "source": "はい。"},
                    {"id": "a/2", "scene": "a", "source": "いいえ。"},
                    {"id": "b/1", "scene": "b", "source": "ありがとう。"},
                    {"id": "c/1", "scene": "c", "source": "ありがとう。"},
                ],
            },
        )
        # The provider reads b's and c's requests the same, so one is sent.
        self.engine.payload = lambda request, configuration: {
            "model": configuration["model"],
            "lines": list(request["sources"].values()),
        }
        results = Results(self.game)

        def organized(policy=True, neighbours=True):
            operation = self.service.organize(self.identity, units, True)
            job, plan = self.service.jobs.store.load(operation["id"], self.identity)
            if not policy:
                # As an organize prepared before the policy froze it.
                del plan["compile"]["reuse"]
            if not neighbours:
                del plan["compile"]["neighbours"]
                del plan["compile"]["delivered"]
            with patch("dazedtl.translation.run_compiler.require_coverage"):
                result = execute(self.engine, self.profile, job, plan, lambda: False)
            job.update(status="complete", result=result)
            self.service.jobs.store.save(job)
            run = self.service.run(self.identity, result["run"])
            return run, self.service.jobs.store.load(run["id"])[1]

        first, plan = organized()
        self.assertEqual(plan["askers"], {"c/1": "b/1"})
        # The run names no split scene's earlier lines; an organize frozen
        # before the policy names none either (organize.DELIVERED).
        self.assertEqual(
            (plan["delivered"], plan["preceding"]), (organize.DELIVERED, {})
        )
        quoted = first["quote"]
        self.assertEqual((quoted["requests"], quoted["units"]), (2, 3))
        # The run keeps a/2 in its source text, as after a failed check.
        replies = {
            "a/1": {"a/1": "Yes.", "a/2": "いいえ。"},
            "b/1": {"b/1": "Thanks."},
            "c/1": {"c/1": "Thanks."},
        }
        for request in plan["requests"]:
            results.accept(request, replies[request["id"]], {"run_id": first["id"]})
        self.engine.glossary_text = "Approved names\nリリ (Lili)"
        # An organize frozen before neighbours sends the line as a scene of
        # its own; now its request quotes the translated line before it.
        _older, plan = organized(neighbours=False)
        self.assertNotIn("stretches", plan["requests"][0]["context"])
        self.assertNotIn("delivered", plan)
        second, plan = organized()
        self.assertEqual([list(row["sources"]) for row in plan["requests"]], [["a/2"]])
        self.assertEqual(
            plan["requests"][0]["context"]["stretches"],
            [{"first": "a/2", "last": "a/2", "before": [["はい。", "Yes."]]}],
        )
        self.service.validate_current(self.identity, plan)
        self.assertEqual(second["quote"]["units"], 1)
        # Compiling organize's plan by hand made a run without the kept lines.
        with self.assertRaisesRegex(ValueError, "Run organize --input"):
            self.service.compile(self.identity, "./" + plan["input_path"])
        # Progress reads the kept line left and the others translated.
        index = read_json(self.game / EXPORT)
        self.assertEqual(
            {
                row["source_id"]: row.get("translation")
                for part in index["parts"]
                for row in read_json(self.game / part)["units"]
            },
            {"a/2": None, "a/1": "Yes.", "b/1": "Thanks.", "c/1": "Thanks."},
        )
        written = self.service.results(self.identity, second["id"])
        self.assertEqual(
            read_json(self.game / written["path"])["translations"],
            {"a/1": "Yes.", "b/1": "Thanks.", "c/1": "Thanks."},
        )
        self.assertEqual(written["missing"], {"pending": 1})
        results.accept(plan["requests"][0], {"a/2": "No."}, {"run_id": second["id"]})
        self.service.refresh_progress(self.identity, plan)
        report = read_json(self.game / (WORK + "/progress-report.json"))
        report.update(phase=None)
        report["phases"].update(
            translation="complete",
            injection="complete",
            qa="complete",
            patch="complete",
        )
        write_json(self.game / (WORK + "/progress-report.json"), report)
        # With every line translated, the next organize has nothing to send,
        # and no translation changed, so finished phases stay finished.
        third, plan = organized()
        self.assertEqual(self.engine.reports[-1]["phases"]["qa"], "complete")
        self.assertEqual(
            (third["status"], third["requests"], third["quote"]["requests"]),
            ("complete", 0, 0),
        )
        self.assertEqual(
            self.service.results(self.identity, third["id"])["translated"], 4
        )
        self.service.validate_current(self.identity, plan)
        # An organize prepared before the policy packs every line.
        _older, plan = organized(policy=False)
        self.assertNotIn("reused", plan)
        self.assertEqual(sum(len(row["sources"]) for row in plan["requests"]), 4)

    def test_the_newest_run_corrects_a_line_it_reused_from_an_earlier_run(self):
        # Once organize kept a line from an earlier run, nothing could
        # correct it after a guidance edit: the newest run held no request
        # for it, and the run that did refused as its guidance changed.
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        units = WORK + "/work/source-units.json"

        def organized(lines, bound=12):
            write_json(
                self.game / units,
                {
                    "version": 1,
                    "units": [
                        {
                            "id": identity,
                            "scene": identity[0],
                            "source": source,
                            "max_characters": bound,
                        }
                        for identity, source in lines.items()
                    ],
                },
            )
            run = self.prepared(self.service.organize(self.identity, units))["run"]
            return run, self.service.jobs.store.load(run["id"])[1]

        receipt = WORK + "/work/receipt.json"

        def accept(run, request, translations, replaces=None):
            write_json(
                self.game / receipt,
                {
                    "request_sha256": request["fingerprint"],
                    "translations": translations,
                    **({"replaces_sha256": replaces} if replaces else {}),
                },
            )
            return self.service.accept(self.identity, run["id"], request["id"], receipt)

        results = Results(self.game)
        first, older = organized(
            {"a/1": "はい。", "a/2": "いいえ。", "b/1": "ありがとう。"}
        )
        earlier, other = older["requests"]
        accept(first, earlier, {"a/1": "Yes.", "a/2": "No."})
        accept(first, other, {"b/1": "Thanks."})
        self.service.review(
            self.identity, first["id"], earlier["id"], earlier["fingerprint"]
        )
        saved = results.get(earlier)

        def run_files(run):
            folder = self.service.jobs.store.folder(run["id"])
            return {path: path.read_bytes() for path in folder.rglob("*.json")}

        older_files = run_files(first)
        self.assertTrue(older_files)
        self.engine.glossary_text = "Approved names\nリリ (Lili)"
        # a/1 changed in the game, so the new run translates it itself, in
        # a request of the same ID; the extractor now bounds every line closer.
        lines = {"a/1": "はい！", "a/2": "いいえ。", "b/1": "ありがとう。"}
        second, plan = organized(lines, 8)
        self.assertEqual(set(plan["reused"]["units"]), {"a/2", "b/1"})
        self.assertEqual([row["id"] for row in plan["requests"]], [earlier["id"]])
        corrected = {"a/1": "Yes.", "a/2": "Nope."}
        # The run that translated the line refuses its guidance changed.
        with self.assertRaisesRegex(ValueError, "Compile and review"):
            accept(first, earlier, corrected, saved["result_sha256"])
        accept(second, earlier, corrected, saved["result_sha256"])
        value = results.get(earlier)
        self.assertEqual(value["translations"], corrected)
        self.assertEqual(value["provenance"]["run_id"], second["id"])
        # The line it did not change keeps its review.
        self.assertEqual(set(value["reviewed"]), {"a/1"})
        # The run reads that request back by the request_sha256 its export
        # row names, with the lines it keeps from it, and reviews those.
        preview = self.service.request(
            self.identity, second["id"], request_sha256=earlier["fingerprint"]
        )
        check_response("translation_request", preview)
        self.assertEqual(preview["result"]["result_sha256"], value["result_sha256"])
        self.assertEqual(preview["result"]["translations"], corrected)
        self.assertEqual(preview["kept"], ["a/2"])
        self.service.review(
            self.identity, second["id"], earlier["id"], earlier["fingerprint"]
        )
        self.assertEqual(set(results.get(earlier)["reviewed"]), {"a/1", "a/2"})
        with self.assertRaisesRegex(ValueError, "exact saved request"):
            self.service.review(
                self.identity, second["id"], "z/1", earlier["fingerprint"]
            )
        # Progress and results read the correction, and the next organize
        # reuses it.
        index = read_json(self.game / EXPORT)
        self.assertIn(
            "Nope.",
            [
                row.get("translation")
                for part in index["parts"]
                for row in read_json(self.game / part)["units"]
            ],
        )
        written = self.service.results(self.identity, second["id"])
        self.assertEqual(
            read_json(self.game / written["path"])["translations"]["a/2"], "Nope."
        )
        _third, newer = organized(lines, 8)
        self.assertEqual(
            newer["reused"]["units"]["a/2"]["request"], earlier["fingerprint"]
        )
        # A line the run did not reuse, or a request it holds no line of, is
        # still refused; so is one over the bound organize kept it by, or a
        # receipt that replaces an older result.
        with self.assertRaisesRegex(ValueError, "a/1 is not a line this run reads"):
            accept(
                second,
                earlier,
                {"a/1": "Yeah.", "a/2": "Nope."},
                value["result_sha256"],
            )
        with self.assertRaisesRegex(ValueError, "character bound"):
            accept(
                second,
                earlier,
                {"a/1": "Yes.", "a/2": "Nope, no."},
                value["result_sha256"],
            )
        with self.assertRaisesRegex(ValueError, "current result hash"):
            accept(second, earlier, saved["translations"], saved["result_sha256"])
        with self.assertRaisesRegex(ValueError, "replaces_sha256"):
            accept(second, earlier, saved["translations"])
        stranger = {**earlier, "fingerprint": "f" * 64}
        with self.assertRaisesRegex(ValueError, "bind translations"):
            accept(second, stranger, corrected, value["result_sha256"])
        with self.assertRaisesRegex(ValueError, "Unknown request ID"):
            accept(second, {**stranger, "id": "z/1"}, corrected, value["result_sha256"])
        # The earlier run's own files never change.
        self.assertEqual(run_files(first), older_files)

    def test_a_units_skill_message_names_the_skills_users_as_guided_does(self):
        # Guided notes each skill message with who uses the skill, so "%1"
        # gets the right pronouns (engine util/battle_users). A unit holding
        # that message, found by its text in the original game's Skills data
        # and never by its ID, carries the same note: one covering two
        # skills' message names both skills' users, and a party that can only
        # hold アリナ makes a skill nobody else uses hers.
        data = self.game / "data"
        data.mkdir()
        for name, value in {
            "Actors.json": [None, {"id": 1, "name": "アリナ", "classId": 1}],
            "Classes.json": [None, {"id": 1, "learnings": [{"skillId": 1}]}],
            "Enemies.json": [
                None,
                {
                    "id": 1,
                    "name": "スライム",
                    "actions": [{"skillId": 2}, {"skillId": 3}],
                },
            ],
            "System.json": {"partyMembers": [1]},
            "Skills.json": [
                None,
                *(
                    {"id": skill, "name": "", "message1": message}
                    for skill, message in enumerate(
                        ["%1は斬りかかった！", "%1は体当たりした！"]
                        + ["%1は斬りかかった！", "%1は祈った！"],
                        1,
                    )
                ),
            ],
        }.items():
            write_json(data / name, value)
        original_files.record(self.game, original_files.PREPARED)
        # The working copy's names are translated; the original's are read.
        write_json(data / "Actors.json", [None, {"id": 1, "name": "Arina"}])
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        units = WORK + "/work/source-units.json"
        sources = ["%1は斬りかかった！", "%1は体当たりした！", "%1は祈った！", "はい。"]
        write_json(
            self.game / units,
            {
                "version": 1,
                "units": [
                    {"id": f"u{index}", "scene": "battle", "source": text}
                    for index, text in enumerate(sources, 1)
                ],
            },
        )
        run = self.prepared(self.service.organize(self.identity, units))["run"]
        _job, plan = self.service.jobs.store.load(run["id"])
        (request,) = plan["requests"]
        notes = {
            "u1": "actor アリナ; enemy スライム",
            "u2": "enemy スライム",
            "u3": "actor アリナ",
        }
        self.assertEqual(request["context"]["skill_users"], notes)
        self.assertIn(
            SKILL_USERS + "\n" + json.dumps(notes, ensure_ascii=False),
            request["context"]["user"],
        )
        keyed = provider_view(request, {"lineKeys": LINE_KEYS})["user"]
        self.assertIn(
            SKILL_USERS
            + "\n1: actor アリナ; enemy スライム\n2: enemy スライム\n3: actor アリナ\n",
            keyed,
        )
        self.service.validate_current(self.identity, plan)
        # A run frozen before the policy keeps its requests.
        with patch("dazedtl.translation.service.BATTLE_MESSAGE_USERS", None):
            older = self.prepared(self.service.organize(self.identity, units))["run"]
        _job, older = self.service.jobs.store.load(older["id"])
        self.assertNotIn("skill_users", older["requests"][0]["context"])
        self.service.validate_current(self.identity, older)

    def test_a_runs_name_codes_show_the_actor_a_script_names_in_the_original(self):
        # Guided shows \\V[n] as the actor's name when a Control Variables
        # script sets variable n to it; a new Assistant-led run reads those
        # scripts from the original game, and only when a line shows one.
        data = self.game / "data"
        data.mkdir()
        script = "$gameActors.actor(1).name()"
        write_json(data / "System.json", {})
        command = {"code": 122, "indent": 0, "parameters": [4, 5, 0, 4, script]}
        write_json(
            data / "Map001.json",
            {"events": [None, {"pages": [{"list": [command]}]}]},
        )
        original_files.record(self.game, original_files.PREPARED)
        # The working copy's scripts are not read.
        write_json(data / "Map001.json", {"events": []})
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        units = WORK + "/work/source-units.json"

        def organized(*sources):
            write_json(
                self.game / units,
                {
                    "version": 1,
                    "units": [
                        {"id": f"u{index}", "scene": "s", "source": text}
                        for index, text in enumerate(sources, 1)
                    ],
                },
            )
            run = self.prepared(self.service.organize(self.identity, units))["run"]
            return self.service.jobs.store.load(run["id"])[1]

        plan = organized("\\V[4]は来た。", "\\N[1]だ。")
        self.assertEqual(plan["configuration"][name_codes.KEY], name_codes.POLICY)
        self.assertEqual(self.engine.actor_variables, {4: 1, 5: 1})
        self.service.validate_current(self.identity, plan)
        self.assertEqual(self.engine.actor_variables, {4: 1, 5: 1})
        # A run frozen before the policy compiles its requests with the codes.
        older = {
            **plan,
            "configuration": {
                key: value
                for key, value in plan["configuration"].items()
                if key != name_codes.KEY
            },
        }
        self.service.validate_current(self.identity, older)
        self.assertIsNone(self.engine.actor_variables)
        # A run without a variable code shows its \\N[n] without reading them.
        with patch.object(name_codes, "_scanned", side_effect=AssertionError):
            organized("\\N[1]だ。")
        self.assertEqual(self.engine.actor_variables, {})

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
        # Copying or restoring a profile can leave the census younger than
        # the coverage counted against it: the census it names still stands.
        coverage_file = coverage_path(self.profile, self.identity)

        def touch(path, seconds):
            stamp = coverage_file.stat().st_mtime_ns + seconds * 10**9
            os.utime(path, ns=(stamp, stamp))

        touch(census_path(self.profile, self.identity), 5)
        self.assertFalse(self.service.state(self.identity)["coverage"]["stale"])
        # Coverage an earlier DazedTL saved names no census: file times decide.
        saved = read_json(coverage_file)
        write_json(coverage_file, {k: v for k, v in saved.items() if k != "census_id"})
        touch(census_path(self.profile, self.identity), 5)
        self.assertTrue(self.service.state(self.identity)["coverage"]["stale"])
        touch(census_path(self.profile, self.identity), -5)
        self.assertFalse(self.service.state(self.identity)["coverage"]["stale"])
        write_json(coverage_file, saved)
        # A patch needs every accepted unit exported, against the same census.
        with self.assertRaisesRegex(ValueError, "fewer than the 2") as refused:
            self.service.require_inventory(self.identity, 1)
        # Release tells the user why in their terms, not the assistant's.
        self.assertEqual(
            refused.exception.reason,
            "Your assistant saves every translated line first.",
        )
        self.service.require_inventory(self.identity, 2)
        # A census an earlier DazedTL took had no ID: the inventory it
        # accepted names it by its digest.
        taken = read_json(census_path(self.profile, self.identity))
        accepted = read_json(inventory_path(self.profile, self.identity))
        write_json(
            census_path(self.profile, self.identity),
            {k: v for k, v in taken.items() if k != "id"},
        )
        write_json(
            inventory_path(self.profile, self.identity),
            {
                "census_sha256": digest(
                    census_path(self.profile, self.identity).read_bytes()
                ),
                "units": 2,
            },
        )
        self.service.require_inventory(self.identity, 2)
        write_json(census_path(self.profile, self.identity), taken)
        with self.assertRaisesRegex(ValueError, "after the latest census"):
            self.service.require_inventory(self.identity, 2)
        write_json(inventory_path(self.profile, self.identity), accepted)
        self.service.require_inventory(self.identity, 2)
        # A census an earlier DazedTL counted by other rules, before it
        # counted choice help, asks for a new census before organize or a
        # patch accepts it.
        counted = read_json(census_path(self.profile, self.identity))
        write_json(
            census_path(self.profile, self.identity),
            {**counted, "version": counted["version"] - 1},
        )
        self.assertTrue(self.service.state(self.identity)["coverage"]["stale"])
        with self.assertRaisesRegex(ValueError, "no longer counts the game"):
            self.service.require_inventory(self.identity, 2)
        with self.assertRaisesRegex(ValueError, "Run census again"):
            self.prepared(self.service.organize(self.identity, units, True))
        census()
        self.prepared(self.service.organize(self.identity, units, True))
        self.service.require_inventory(self.identity, 2)
        page.append(line(401, "追加の台詞。"))
        write_json(
            self.game / "data/Map001.json",
            {"events": [None, {"name": "", "pages": [{"list": page}]}]},
        )
        back_up()
        # A game update records a new prepared original: Progress reads the
        # count as stale and packaging refuses before any organize runs.
        self.assertTrue(self.service.state(self.identity)["coverage"]["stale"])
        with self.assertRaisesRegex(ValueError, "no longer counts the game"):
            self.service.require_inventory(self.identity, 2)
        census()
        # The new census is current, but the coverage counted the old one,
        # even once the census reads older than it.
        self.assertTrue(self.service.state(self.identity)["coverage"]["stale"])
        touch(census_path(self.profile, self.identity), -5)
        self.assertTrue(self.service.state(self.identity)["coverage"]["stale"])
        with self.assertRaisesRegex(ValueError, "after the latest census"):
            self.service.require_inventory(self.identity, 2)
        back_up()
        with self.assertRaisesRegex(ValueError, "Run census again"):
            self.prepared(self.service.organize(self.identity, units, True))

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
        # The provider's Batch discount prices it, so the run freezes none.
        _job, frozen = self.service.jobs.store.load(run["id"])
        self.assertNotIn("batch_factor", frozen["configuration"]["rates"])
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

    def test_a_pricing_fix_prices_a_waiting_estimate_again_or_outdates_it(self):
        # A pricing fix left a waiting quote at the price rules of the
        # release that made it, which the user then approved.
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        store = self.service.jobs.store
        self.assertEqual(run["quote"]["provider"], "custom")
        self.assertIn("cacheable_tokens", run["quote"])

        def view(identity):
            jobs = self.service.state(self.identity)["jobs"]
            return next(job for job in jobs if job["id"] == identity)

        def older(identity, **prices):
            # Saved before quotes named their price rules, at an older price.
            job, _plan = store.load(identity)
            job["quote"] = {
                **{
                    key: item
                    for key, item in job["quote"].items()
                    if key != "price_rules"
                },
                **prices,
            }
            store.save(job)

        # Under today's rules it stands as saved.
        self.assertEqual(view(run["id"])["quote"], run["quote"])
        # A change to how a quote counts its output outdates it instead, as
        # its counts can't follow; the quote's own token no longer approves.
        self.assertEqual(run["quote"]["output_rules"], 1)
        with patch.object(estimate_prices, "OUTPUT_RULES_VERSION", 2):
            recounted = view(run["id"])
            self.assertTrue(recounted["pricing_changed"])
            self.assertFalse(recounted["settings_changed"])
            with self.assertRaisesRegex(ValueError, "price changed"):
                self.service.start(self.identity, run["id"], run["approval_token"])
        older(run["id"], cost=9.0, batch_cost=9.0, live_cost=18.0)
        # Its OpenAI Batch counts are priced again under today's rules.
        shown = view(run["id"])
        self.assertFalse(shown["settings_changed"] or shown["pricing_changed"])
        self.assertEqual(shown["quote"], run["quote"])

        # The shown price's token follows only its own route's rules: a fix
        # to Claude's keeps it, one to OpenAI's Batch changes it.
        def fix(route):
            # A pricing fix to ``route``'s rules, as provider_costs records it.
            version = provider_costs.PRICE_RULES_VERSION + 1
            return patch.multiple(
                provider_costs,
                ROUTE_PRICE_RULES={**provider_costs.ROUTE_PRICE_RULES, route: version},
                PRICE_RULES_VERSION=version,
            )

        with fix("anthropic"):
            self.assertEqual(view(run["id"])["approval_token"], shown["approval_token"])
        with fix("openai"):
            raised = view(run["id"])
            self.assertNotEqual(raised["approval_token"], shown["approval_token"])
            with self.assertRaisesRegex(ValueError, "price changed"):
                self.service.start(self.identity, run["id"], shown["approval_token"])
        # The quote's own token approved the older price; only the shown
        # price's token approves, and freezes the run at it.
        with self.assertRaisesRegex(ValueError, "price changed"):
            self.service.start(self.identity, run["id"], run["approval_token"])
        with self.assertRaisesRegex(ValueError, "Provider execution is disabled"):
            self.service.start(self.identity, run["id"], shown["approval_token"])
        job, _plan = store.load(run["id"])
        self.assertTrue(store.authorized(job))
        self.assertEqual(job["quote"], shown["quote"])
        # Claude counts with each model's own tokenizer and keeps no counts
        # of its cached instructions, so its quote reads outdated instead.
        self.settings_data["connections"][0]["protocol"] = "anthropic"
        self.engine.batch_supported = lambda _configuration: "anthropic"
        self.engine.claude_input_tokens = lambda *_args: None
        self.engine.claude_cache = lambda *_args: None
        claude = self.prepared(self.service.compile(self.identity, self.plan_path))
        self.assertFalse(view(claude["id"])["pricing_changed"])
        older(claude["id"], cost=9.0)
        outdated = view(claude["id"])
        self.assertTrue(outdated["pricing_changed"])
        self.assertFalse(outdated["settings_changed"])
        self.assertEqual(outdated["quote"]["cost"], 9.0)
        for token in (claude["approval_token"], outdated["approval_token"]):
            with self.assertRaisesRegex(ValueError, "price changed"):
                self.service.start(self.identity, claude["id"], token)
        self.assertFalse(store.authorized(store.load(claude["id"])[0]))
        # A fix to another route's rules leaves it standing: versions 3 and 4
        # changed OpenAI's Batch prices, Claude's last changed at 2.
        for rules in (2, 3):
            older(claude["id"], cost=9.0, price_rules=rules)
            kept = view(claude["id"])
            self.assertFalse(kept["settings_changed"] or kept["pricing_changed"])
            self.assertEqual(kept["quote"]["cost"], 9.0)
            self.assertEqual(kept["approval_token"], claude["approval_token"])
        # Under today's rules on every route, it still reads changed once
        # its settings send it on another route than the one that priced
        # it, which can't price its counts; one saved before quotes recorded
        # their route reads its settings' route.
        self.assertEqual(claude["quote"]["route"], "anthropic")
        older(claude["id"], cost=9.0, price_rules=provider_costs.PRICE_RULES_VERSION)
        with patch.object(self.engine, "batch_supported", return_value="openai"):
            self.assertTrue(view(claude["id"])["pricing_changed"])
            with self.assertRaisesRegex(ValueError, "price changed"):
                self.service.start(
                    self.identity, claude["id"], claude["approval_token"]
                )
            job, _plan = store.load(claude["id"])
            del job["quote"]["route"]
            store.save(job)
            self.assertFalse(view(claude["id"])["pricing_changed"])
        with self.assertRaisesRegex(ValueError, "Provider execution is disabled"):
            self.service.start(self.identity, claude["id"], claude["approval_token"])

    def test_a_waiting_gpt_4_1_batch_quote_drops_cache_reads_its_batch_never_gets(
        self,
    ):
        # A GPT-4.1 Batch quote offered a lower price reusing cached
        # instructions, though OpenAI's Batch caches nothing on GPT-4.1; one
        # saved before the fix showed that price until estimated again.
        connection = self.settings_data["connections"][0]
        options = connection["model_options"]
        options["gpt-4.1"] = {**options["fixture-model"], "inputRate": 2}
        options["gpt-4.1"]["outputRate"] = 8
        connection["model"] = "gpt-4.1"
        self.engine.openai_cache = lambda _requests: {
            "cache_read_tokens": 10**9,
            "cacheable_tokens": 10**9,
        }
        run = self.prepared(self.service.compile(self.identity, self.plan_path))
        store = self.service.jobs.store
        self.assertNotIn("batch_cost_reused", run["quote"])
        self.assertEqual(run["quote"]["cost"], run["quote"]["batch_cost"])
        # As a release before the fix priced it, under version 2's rules, or
        # under version 3's, which version 4 changed on OpenAI's route again.
        for rules in (2, 3):
            job, _plan = store.load(run["id"])
            job["quote"] = {
                **run["quote"],
                "price_rules": rules,
                "batch_cost_reused": run["quote"]["cost"] / 4,
            }
            store.save(job)
            shown = next(
                job
                for job in self.service.state(self.identity)["jobs"]
                if job["id"] == run["id"]
            )
            self.assertFalse(shown["settings_changed"] or shown["pricing_changed"])
            self.assertEqual(shown["quote"], run["quote"])

    def test_deepseek_spend_is_priced_by_when_each_request_arrived(self):
        # DeepSeek bills half outside its weekday peak hours, but Progress
        # Spent and Requests Recorded usage priced every request at peak.
        from datetime import UTC, datetime

        from dazedtl.translation.runner import Runner

        rows = []
        for identity in ("peak", "off-peak", "older"):
            row = logical_request(
                {"id": identity, "sources": {identity: "はい。"}},
                {"speakers": {identity: None}},
            )
            row["params"] = {"model": "deepseek-flash", "messages": []}
            rows.append(row)
        store = self.service.jobs.store
        job = store.create(
            self.identity,
            {
                "version": 1,
                "kind": "translation",
                "source": str(self.game),
                "complete": True,
                "requests": rows,
                "configuration": {
                    "mode": "live",
                    "model": "deepseek-flash",
                    "provider": "deepseek",
                    "endpoint": "https://api.deepseek.com",
                    # Approved before runs stopped freezing a Batch discount.
                    "rates": {"input": 0.30, "output": 1.20, "batch_factor": 0.5},
                },
                "batch_limits": [50, 100000],
            },
            {"cost": 1},
        )
        store.authorize(job)
        # Monday 26 October 2026: peak hours end at 10:00 UTC.
        ten = datetime(2026, 10, 26, 10, tzinfo=UTC).timestamp()
        sent = iter(zip(("peak", "off-peak", "older"), (ten - 1, ten, ten)))

        class Provider:
            def live(self, _params):
                line, created = next(sent)
                return {
                    "text": json.dumps({line: "Yes."}),
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 1_000_000,
                    "created": created,
                }

        Runner(store, job["id"], Provider(), lambda: None).step()
        current, _plan = store.load(job["id"])
        self.assertEqual(current["status"], "complete")
        # A row saved before rows held a time keeps the peak price.
        del current["request_usage"]["older"]["received_at"]
        store.save(current)
        self.engine.batch_supported = lambda _configuration: None
        record = store.record(job["id"])
        view = self.service.job_views([record], "live", self.game)[0]
        self.assertAlmostEqual(view["usage_cost"], 1.50 + 0.75 + 1.50)

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
        with self.assertRaisesRegex(ValueError, "interrupted update"):
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

    def test_a_saved_batch_runs_live_on_a_connection_that_cannot_run_batch(self):
        # A project saved on API Batch, opened on a Live-only connection such
        # as DeepSeek's, runs Live and says why instead of refusing its run.
        # The page's options keep Batch, so saving another option there keeps
        # it too, and a Batch connection brings it back.
        live_only = {"model": "fixture-model", "batch_supported": False}
        self.settings.translation_defaults = lambda: live_only
        self.assertEqual(self.service.run_mode(self.project), "live")
        self.assertEqual(
            self.service.state(self.identity)["batchUnavailable"],
            "This connection can't run Batch.",
        )
        selected = self.service.options(self.project)
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "instructions": "Keep honorifics."},
        )
        self.settings.translation_defaults = lambda: {
            **live_only,
            "batch_supported": True,
        }
        self.assertEqual(self.service.run_mode(self.project), "batch")

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

    def test_originals_stage_only_the_files_a_translation_changed(self):
        # A run reads a value that keeps no source of its own against the
        # game's original file (engine util/original_values): the record's
        # files that differ from the game's are staged, laid out as the game
        # is, and a game whose originals are not recorded stages none.
        from dazedtl.translation import originals

        with TemporaryDirectory() as folder:
            game, staged = Path(folder) / "game", Path(folder) / "staged"
            for name, text in (
                ("www/data/Map001.json", "はじまりの村"),
                ("www/data/Map002.json", "森"),
                ("www/js/plugins.js", "var $plugins = [];"),
            ):
                (game / name).parent.mkdir(parents=True, exist_ok=True)
                (game / name).write_text(text, encoding="utf-8")
            names = ["Map001.json", "Map002.json"]
            self.assertFalse(originals.stage(game, names, game / "www/data", staged))
            original_files.record(game, original_files.FOUND)
            (game / "www/data/Map001.json").write_text("起始之村", encoding="utf-8")
            self.assertTrue(
                originals.stage(game, names, game / "www/data", staged, plugins=True)
            )
            self.assertEqual(
                sorted(
                    path.relative_to(staged).as_posix() for path in staged.rglob("*.*")
                ),
                ["data/Map001.json"],
            )
            self.assertEqual(
                (staged / "data/Map001.json").read_text("utf-8"), "はじまりの村"
            )

    def test_undoing_a_phase_checkpoint_reopens_it_and_every_later_phase(self):
        # Checkpoints' undo put the game back before the injection, yet
        # Progress still read injection, QA and the patch done.
        from dazedtl.compatibility.checkpoint_commits import Change, _git, save
        from util.len_git import setup_git
        from util.len_translation import LenProject

        setup_git(LenProject(self.game), version="1.0", current_is_untranslated=True)
        done = dict.fromkeys(
            ("preparation", "extraction", "translation", "injection", "qa"),
            "complete",
        )
        report = {
            "phase": "patch",
            "phases": {**done, "images": "out_of_scope", "patch": "blocked"},
            "blocker": "Choose where the patch goes.",
        }
        progress_report.publish(
            self.profile, self.identity, self.engine, self.game, DEFAULTS, report
        )
        write_json(self.game / "source.json", {"line": "Yes."})
        save(self.game, Change("Injection", "Assistant-led", "assistant_phase"))
        injected = _git(self.game, "rev-parse", "HEAD").stdout.strip()
        (self.game / "notes.txt").write_text("QA\n", encoding="utf-8")
        save(self.game, progress_report.phase(self.game), ["notes.txt"])
        write_json(
            lifecycle_path(self.profile, self.identity),
            {**lifecycle(self.profile, self.identity), "delivery": {"path": "p.zip"}},
        )
        execute(
            self.engine,
            self.profile,
            {"project_id": self.identity},
            {
                "source": str(self.game),
                "options": DEFAULTS,
                "action": "checkpoint_undo",
                "arguments": {"commit": injected},
            },
            lambda: False,
        )
        reopened = self.engine.reports[-1]
        self.assertEqual(reopened["phase"], "injection")
        self.assertEqual(
            reopened["phases"],
            {
                **done,
                "images": "out_of_scope",
                "injection": "active",
                "qa": "pending",
                "patch": "pending",
            },
        )
        # The question it asked at the patch no longer stands.
        self.assertEqual(
            (reopened["blocker"], reopened["next_action"]),
            ("", progress_report.REOPENED.format("injection")),
        )
        # The last patch stays on Release and Progress, read Outdated.
        kept = lifecycle(self.profile, self.identity)["delivery"]
        self.assertEqual(kept["path"], "p.zip")
        self.assertIs(current(kept, self.game), False)

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
        # A Guided Apply put a translation in; starting over takes it out,
        # so its records must stop reading it as applied, as an undo's do.
        publications = self.root / "publications"
        publications.mkdir()
        publication.publish(
            publications,
            self.game,
            publication.freeze(
                publications,
                self.game,
                {"source.json": b'{"line": "Yes!"}'},
                "export_selected",
                outputs={"source.json": "translated"},
            ),
        )
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
        # The game's settings, such as Line widths and its GameUpdate record,
        # and the user's skills are the project's, never the original game's.
        portable = {
            self.game / ".dazedtl/settings.json": '{"line_widths": {"x": 1}}',
            self.game / ".dazedtl/skills/custom.md": "custom skill",
        }
        for path, text in portable.items():
            path.parent.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
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
                    "publications": str(publications),
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
        self.assertEqual(
            [row["state"] for row in publication.history(publications)],
            ["complete", "restored"],
        )
        self.assertEqual(read_json(publications / "applied-outputs.json")["files"], {})
        self.assertTrue((archive / "len-method/progress.json").is_file())
        self.assertFalse((self.game / ".dazedtl/playtest").exists())
        self.assertTrue((archive / "playtest/DazedTL_Fixes.js").is_file())
        self.assertTrue(self.project.path.is_file())
        self.assertEqual(glossary.read_text(encoding="utf-8"), "Lili (リリ)")
        for path, text in portable.items():
            self.assertEqual(path.read_text(encoding="utf-8"), text)
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

    def test_a_patch_update_records_an_older_projects_new_originals(self):
        # A project set up before Git kept its original files, which reads
        # its backup, recorded nothing for a patch laid over the game, so an
        # undo deleted a file the patch added outside the translation's
        # patch and put back the old bytes of one it changed.
        import hashlib
        from dataclasses import asdict

        from dazedtl.compatibility.checkpoint_history import Entry, _Game
        from dazedtl.compatibility.translation import TranslationEngine
        from dazedtl.translation import originals
        from util import version_update
        from util.len_git import setup_git
        from util.len_patch_scope import scope_ignore
        from util.len_translation import LenProject

        (self.game / "movies").mkdir()
        (self.game / "movies/old.webm").write_bytes(b"old")
        # The translation's patch holds its text alone.
        (self.game / ".gitignore").write_text(
            scope_ignore("", {"source.json"}), encoding="utf-8"
        )
        setup_git(LenProject(self.game), version="1.0", current_is_untranslated=True)
        saved = old_backup.snapshot(self.game)
        state = {
            **lifecycle(self.profile, self.identity),
            "source_backup": saved,
            "prepared_source": saved,
        }
        write_json(lifecycle_path(self.profile, self.identity), state)
        official = self.root / "patch"
        (official / "movies").mkdir(parents=True)
        (official / "movies/old.webm").write_bytes(b"changed")
        (official / "movies/added.webm").write_bytes(b"added")
        self.engine.version = TranslationEngine(self.profile).version
        preview = asdict(
            version_update.preview_official_update(
                self.game, official, "1.1", patch_overlay=True
            )
        )
        # Assistant-led had delivered the old version; Progress kept reading
        # done after the update brought new text.
        finished = dict.fromkeys(
            ("preparation", "extraction", "translation", "injection", "qa", "patch"),
            "complete",
        )
        progress_report.publish(
            self.profile,
            self.identity,
            self.engine,
            self.game,
            DEFAULTS,
            {"phases": {**finished, "images": "out_of_scope"}},
        )
        execute(
            self.engine,
            self.profile,
            {"project_id": self.identity},
            {
                "source": str(self.game),
                "options": DEFAULTS,
                "action": "version_apply",
                "arguments": {
                    "official": str(official),
                    "version": "1.1",
                    "patch_overlay": True,
                    "preview": preview,
                },
            },
            lambda: False,
        )
        reopened = self.engine.reports[-1]
        self.assertEqual(reopened["phase"], "extraction")
        self.assertEqual(
            reopened["phases"],
            {
                "preparation": "complete",
                "extraction": "active",
                "translation": "pending",
                "images": "out_of_scope",
                "injection": "pending",
                "qa": "pending",
                "patch": "pending",
            },
        )
        # The task after it continued Len's pipeline in no mode of its own:
        # its assistant hand-edited files and translated everything itself.
        # This update's files were all outside the translation, which still
        # counts as applied.
        self.engine.applied_update = TranslationEngine(self.profile).applied_update
        task = self.service.update_task(self.identity)
        self.assertEqual(task["version"], "1.1")
        for step in (
            "with extraction active",
            "continue from step 4",
            "organize --complete",
            "Progress tab, as step 7 says",
            "API Batch",
        ):
            self.assertIn(step, task["prompt"])
        self.assertEqual(
            self.service.operation(self.identity, "version_handoff", {}), task
        )
        game = _Game(
            self.game,
            Entry("", "", "", version="1.1"),
            originals.saved(self.profile, self.identity, self.game),
        )
        for name, raw in (
            ("movies/added.webm", b"added"),
            ("movies/old.webm", b"changed"),
        ):
            blob = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
            self.assertEqual(game.wanted(name, {}), ("100644", blob))

    def test_an_update_that_never_moved_the_original_branch_leaves_its_originals(
        self,
    ):
        # An update recorded its prepared release before it moved the
        # `original` branch, and readers took the newest record of the
        # branch's version, so a release given the current version's label
        # and cancelled at a conflict, or failing before the branch moved,
        # became the game's original files: a Chinese target's values read
        # translated, and the census and patch sources read the wrong files.
        from dataclasses import asdict

        from dazedtl.compatibility.checkpoint_commits import _git
        from dazedtl.compatibility.checkpoint_history import Entry, _Game
        from dazedtl.compatibility.translation import TranslationEngine
        from dazedtl.translation import originals
        from util import version_update
        from util.len_git import setup_git
        from util.len_translation import LenProject

        def git(*arguments):
            return _git(self.game, *arguments).stdout.strip()

        def reads():
            """The prepared original every reader takes, which must agree."""
            recorded = originals.recorded_now(self.game)
            self.assertEqual(
                originals.prepared(self.profile, self.identity, self.game).id,
                recorded,
            )
            game = _Game(self.game, Entry("", "", "", version="1.0"))
            self.assertEqual(
                game.recorded,
                {
                    path: row[:2]
                    for path, row in original_files.files(self.game, recorded).items()
                },
            )
            return recorded

        original_files.record(self.game, original_files.PREPARED, "1.0")
        setup_git(LenProject(self.game), version="1.0", current_is_untranslated=True)
        # A game set up before records were named reads the newest record of
        # its version, as it did, here one an update cancelled then left.
        legacy = original_files.record(self.game, original_files.PREPARED, "1.0")
        self.assertEqual(reads(), legacy)
        write_json(self.game / "source.json", {"line": "Yes."})
        git("add", "source.json")
        git("-c", "user.name=T", "-c", "user.email=t@t", "commit", "-qm", "Apply")
        official = self.root / "release"
        official.mkdir()
        write_json(official / "source.json", {"line": "いいえ。"})
        engine = TranslationEngine(self.profile)
        self.engine.version = engine.version

        def apply(*, stop=False, change=None):
            preview = asdict(
                version_update.preview_official_update(self.game, official, "1.0")
            )
            if change:
                change()
            with patch.object(
                version_update,
                "apply_official_update",
                partial(version_update.apply_official_update, auto_resolve=not stop),
            ):
                return operation("version_apply", preview=preview)

        def operation(action, **arguments):
            return execute(
                self.engine,
                self.profile,
                {"project_id": self.identity},
                {
                    "source": str(self.game),
                    "options": DEFAULTS,
                    "action": action,
                    "arguments": {
                        "official": str(official),
                        "version": "1.0",
                        **arguments,
                    },
                },
                lambda: False,
            )

        # The developer's new release under the same label, stopped at its
        # conflict and cancelled.
        self.assertFalse(apply(stop=True)["complete"])
        operation("version_abort")
        self.assertEqual(
            git("show", "original:source.json"), '{\n  "line": "はい。"\n}'
        )
        self.assertEqual(reads(), legacy)
        # One whose release changed after its preview fails before it moves
        # the branch.
        with self.assertRaisesRegex(Exception, "changed after preview"):
            apply(change=lambda: write_json(official / "extra.json", {}))
        self.assertEqual(reads(), legacy)
        # Applied, its record is the original, under the same label.
        self.assertTrue(apply()["complete"])
        update = reads()
        self.assertNotEqual(update, legacy)
        self.assertIn("extra.json", original_files.files(self.game, update))

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
        (self.root / "patch.zip").write_bytes(b"patch")
        self.engine.package = Mock(
            side_effect=lambda *_args, **_kwargs: {
                "path": str(self.root / "patch.zip"),
                "paths": [],
            }
        )
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
        with self.assertRaises(ValueError):
            self.service.operation(self.identity, "release_patch", {})
        path = WORK + "/work/patch-files.json"
        write_json(self.game / path, ["source.json"])
        delivery.record(self.game, path, ["source.json"])
        delivery.verify(self.game, full=True)
        write_json(self.game / "source.json", {"line": "Changed after review"})
        with self.assertRaises(ValueError):
            delivery.verify(self.game, full=True)
