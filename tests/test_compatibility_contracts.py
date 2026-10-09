"""Focused contracts at the maintained-engine boundary, without importing a sibling checkout."""

import json
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.compatibility.guided import (
    apply_selected,
    phased_workflows,
    rewrap_review,
    run_ace,
    runtime_files,
)
from dazedtl.compatibility.manual import (
    DECLINED_SPEAKERS,
    canceled_before_submission,
    manual_jobs,
)
from dazedtl.compatibility.speaker_scan import collect as collect_speakers
from dazedtl.compatibility.translation import (
    ProviderFailure,
    TranslationEngine,
    provider_errors,
)
from dazedtl.settings.preferences import GENERATION_PARAMETERS
from dazedtl.storage import write_json
from dazedtl.translation.compilation import compile_requests
from dazedtl.translation.files import digest

from tests.engine import ENGINE, engine_module, point


class CompatibilityContracts(unittest.TestCase):
    def test_engine_extension_layers_reach_aliases_and_reconfigure_in_place(self):
        # Host wrappers used to reassign module attributes: aliases bound at
        # import missed them, and repeated configuration stacked duplicates.
        extensions = engine_module("util/extensions.py")

        @extensions.point
        def native(value):
            return [value]

        alias = native

        def tag(label):
            return lambda call, value: [*call(value), label]

        native.layer("inner", tag("inner"))
        native.layer("outer", tag("outer"))
        native.layer("inner", tag("again"))
        self.assertEqual(alias(1), [1, "again", "outer"])
        native.remove("inner")
        native.remove("outer")
        self.assertEqual(alias(1), [1])

        class Task:
            @extensions.point
            def run(self):
                return "native"

        Task().run.layer("host", lambda call, task: "host " + call(task))
        self.assertEqual(Task().run(), "host native")

    def test_frozen_worker_defaults_preserve_payloads_and_legacy_recovery(self):
        # Regression: the native builder injects unsupported temperature into a
        # new guided Batch. Normalize before collection and Live serialization,
        # but never reinterpret the saved policy of a historical run.
        from copy import deepcopy

        from dazedtl.compatibility.worker_policy import install

        desktop, backend, environment, util, translation = (
            ModuleType(name)
            for name in (
                "desktop",
                "desktop.backend",
                "desktop.backend.manual_environment",
                "util",
                "util.translation",
            )
        )
        desktop.backend = backend
        backend.manual_environment = environment
        util.translation = translation
        baseline = {
            "messages": [
                {"role": "system", "content": "Approved game guidance"},
                {"role": "user", "content": '{"Line1":"防御"}'},
            ],
            "max_completion_tokens": 8192,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"Line1": {"type": "string"}},
                        "required": ["Line1"],
                        "additionalProperties": False,
                    },
                },
            },
        }

        def native(model):
            return {
                **deepcopy(baseline),
                "model": model,
                "temperature": 0,
                "frequency_penalty": 0.05,
                "reasoning_effort": "none",
            }

        translation.buildOpenAIRequest = point(native)
        translation.buildClaudeRequest = point(native)
        translation._translation_completion_limit = point(
            lambda *_args, **_kwargs: 8192
        )
        translation._openai_batch_token_limit = point(lambda: 600_000)
        translation._load_litellm_pricing = point(lambda: None)
        for name in ("estimateCostComparison", "translateAI", "calculateCost"):
            setattr(translation, name, point(Mock()))
        quote = {
            "model": "gpt-6.1-sol",
            "provider": "openai",
            "input_tokens": 98_016,
            "output_tokens": 4_617,
            "cache_read_tokens": 86_528,
            "cache_write_tokens": 11_360,
            "uses_prompt_cache": True,
            "batch_nocache_cost": 0.121101,
            "batch_cached_cost": 0.0460658,
        }
        native_estimate = Mock(return_value=quote)
        translation.estimateBatchCost = point(native_estimate)

        def pricing(model):
            rates = translation._load_litellm_pricing()[model]
            return {
                "inputAPICost": rates["input_cost_per_token"] * 1_000_000,
                "outputAPICost": rates["output_cost_per_token"] * 1_000_000,
            }

        translation.getPricingConfig = pricing
        native_prepare = Mock(return_value="prepared")
        environment.prepare = point(native_prepare)
        modules = {
            module.__name__: module
            for module in (desktop, backend, environment, util, translation)
        }
        with TemporaryDirectory() as temporary, patch.dict(sys.modules, modules):
            root = Path(temporary)
            policy = {
                "version": 1,
                "model": "gpt-6.1-sol",
                "entriesPerRequest": 50,
                "inputRate": 2,
                "outputRate": 10,
                "generationParameters": GENERATION_PARAMETERS,
            }
            plan = {
                "settings": {"model": "gpt-6.1-sol", "batchsize": 50},
                "dazedtl_request_policy": policy,
            }
            write_json(root / "plan.json", plan)
            write_json(
                root / "log/batch_requests.json", {"historical": native("gpt-6.1-sol")}
            )
            frozen = {
                name: (root / name).read_bytes()
                for name in ("plan.json", "log/batch_requests.json")
            }
            install()
            self.assertEqual(environment.prepare(root), "prepared")
            # New quotes must use Sol 6.1's 5% cache-read price, preserve the
            # cache-write charge, and never repeatedly discount a saved value.
            self.assertAlmostEqual(
                translation.estimateBatchCost()["batch_cached_cost"], 0.0417394
            )
            self.assertEqual(quote["batch_cached_cost"], 0.0460658)
            environment.prepare(root)
            self.assertAlmostEqual(
                translation.estimateBatchCost()["batch_cached_cost"], 0.0417394
            )
            self.assertEqual(native_estimate.call_count, 2)
            with patch.object(
                translation,
                "getPricingConfig",
                return_value={"inputAPICost": 4, "outputAPICost": 20},
            ):
                self.assertAlmostEqual(
                    translation.estimateBatchCost()["batch_cached_cost"], 0.0834788
                )
            for other in (
                {**quote, "provider": "anthropic"},
                {**quote, "model": "gpt-6-sol"},
                {**quote, "cache_read_tokens": None},
            ):
                native_estimate.return_value = other
                self.assertIs(translation.estimateBatchCost(), other)
            native_estimate.return_value = quote
            for model in (
                "gpt-6.1-sol",
                "gpt-6-sol",
                "gpt-6-luna",
                "gpt-6-astra",
                "gpt-4.1",
                "custom-model",
            ):
                with self.subTest(model=model):
                    live = translation.buildOpenAIRequest(model)
                    batch_body = json.loads(
                        json.dumps({"body": translation.buildOpenAIRequest(model)})
                    )["body"]
                    self.assertEqual(live, {**baseline, "model": model})
                    self.assertEqual(batch_body, live)
                    self.assertEqual(translation.buildClaudeRequest(model), live)
            self.assertEqual(
                {name: (root / name).read_bytes() for name in frozen}, frozen
            )
            # Host pinning must reach every new payload without replacing
            # unrelated SDK fields or persisting into automatic/legacy runs.
            baseline["extra_body"] = {"prompt_cache_key": "fixture-cache"}
            plan["settings"].update(
                API_PROVIDER="openai", api="https://openrouter.ai/api/v1"
            )
            plan["dazedtl_request_policy"] = {**policy, "openrouterHost": "deepinfra"}
            write_json(root / "plan.json", plan)
            for _ in range(2):
                environment.prepare(root)
                expected_body = {
                    **baseline["extra_body"],
                    "provider": {"only": ["deepinfra"], "allow_fallbacks": False},
                }
                self.assertEqual(
                    translation.buildOpenAIRequest("fixture")["extra_body"],
                    expected_body,
                )
                self.assertEqual(
                    translation.buildClaudeRequest("fixture")["extra_body"],
                    baseline["extra_body"],
                )
            # A new allowance reaches every transport and the late Mistral
            # override, but the saved request body is never rewritten on resume.
            for allowance in (32768, 16384):
                plan["dazedtl_request_policy"] = {
                    **policy,
                    "maxOutputTokens": allowance,
                    "openrouterHost": "deepinfra",
                }
                write_json(root / "plan.json", plan)
                for _ in range(2):
                    environment.prepare(root)
                    for builder in (
                        translation.buildOpenAIRequest,
                        translation.buildClaudeRequest,
                    ):
                        payload = builder("fixture")
                        self.assertEqual(payload["max_completion_tokens"], allowance)
                        self.assertEqual(payload["messages"], baseline["messages"])
                        self.assertNotIn("reasoning_effort", payload)
                    self.assertEqual(
                        translation._translation_completion_limit(
                            "short text", ceiling=8192
                        ),
                        allowance,
                    )
                self.assertEqual(
                    (root / "log/batch_requests.json").read_bytes(),
                    frozen["log/batch_requests.json"],
                )
            plan["settings"]["api"] = "https://api.openai.com/v1"
            write_json(root / "plan.json", plan)
            with self.assertRaisesRegex(
                ValueError, "requires an OpenRouter connection"
            ):
                environment.prepare(root)
            plan["settings"]["api"] = "https://openrouter.ai/api/v1"
            # A saved per-model allowance must reach the submitter, survive
            # repeated preparation, and never leak into an older frozen run.
            from dazedtl.settings.preferences import DEFAULT_BATCH_INPUT_TOKENS

            for allowance in (8_000_000, DEFAULT_BATCH_INPUT_TOKENS):
                plan["dazedtl_request_policy"] = {
                    **policy,
                    "batchInputTokens": allowance,
                }
                write_json(root / "plan.json", plan)
                for _ in range(2):
                    environment.prepare(root)
                    self.assertEqual(translation._openai_batch_token_limit(), allowance)
                    self.assertEqual(
                        translation.buildOpenAIRequest("fixture")["extra_body"],
                        baseline["extra_body"],
                    )
            for legacy in (
                {
                    key: value
                    for key, value in policy.items()
                    if key != "generationParameters"
                },
                None,
            ):
                if legacy is None:
                    plan.pop("dazedtl_request_policy")
                else:
                    plan["dazedtl_request_policy"] = legacy
                write_json(root / "plan.json", plan)
                environment.prepare(root)
                self.assertEqual(translation._openai_batch_token_limit(), 600_000)
                self.assertEqual(
                    translation.buildOpenAIRequest("gpt-6.1-sol"), native("gpt-6.1-sol")
                )
                self.assertEqual(
                    translation._translation_completion_limit("short text"), 8192
                )
                if legacy is None:
                    self.assertIs(translation.estimateBatchCost(), quote)
            plan["dazedtl_request_policy"] = {
                **policy,
                "generationParameters": "unsupported-future-policy",
            }
            write_json(root / "plan.json", plan)
            before = native_prepare.call_count
            with self.assertRaisesRegex(ValueError, "invalid or unsupported"):
                environment.prepare(root)
            self.assertEqual(native_prepare.call_count, before)

    def test_openrouter_batch_lifts_the_frozen_host_and_rejects_mixed_routes_before_submission(
        self,
    ):
        # Batch routing belongs before the requests array in the batch header;
        # per-row routing must never be dropped or silently combined.
        from dazedtl.compatibility.openrouter_batch import Client
        from dazedtl.compatibility.request_parameters import host_routing
        from dazedtl.settings.openrouter import TRANSPORT

        package, providers = ModuleType("util"), ModuleType("util.batch_providers")
        providers._openai_batch_body = lambda _, params: {
            **{key: value for key, value in params.items() if key != "extra_body"},
            **params.get("extra_body", {}),
        }
        client = Client.__new__(Client)
        client.policy = {
            "transport": TRANSPORT,
            "model": "fixture-model",
            "input": 1,
            "output": 2,
            "max_requests": 100,
            "max_bytes": 10000,
        }
        client.request = Mock(return_value={"id": "batch-fixture"})
        client.archive = Mock()
        base = {
            "model": "fixture-model",
            "messages": [{"role": "user", "content": "Translate this source."}],
        }
        with patch.dict(
            sys.modules, {"util": package, "util.batch_providers": providers}
        ):
            for host in ("", "deepinfra"):
                rows = [
                    {"custom_id": key, "params": host_routing(base, host)}
                    for key in ("first", "second")
                ]
                client.submit(rows)
                sent = client.request.call_args.kwargs["body"]
                self.assertEqual(
                    sent.get("provider"), {"only": ["deepinfra"]} if host else None
                )
                self.assertEqual(list(sent)[-1], "requests")
                self.assertTrue(
                    all("provider" not in row["body"] for row in sent["requests"])
                )
                self.assertEqual(rows[0]["params"], host_routing(base, host))
            client.request.reset_mock()
            for other in ("", "novita"):
                with self.assertRaisesRegex(ValueError, "same host"):
                    client.submit(
                        [
                            {
                                "custom_id": "first",
                                "params": host_routing(base, "deepinfra"),
                            },
                            {
                                "custom_id": "second",
                                "params": host_routing(base, other),
                            },
                        ]
                    )
            with self.assertRaisesRegex(ValueError, "exclusive host"):
                client.submit(
                    [
                        {
                            "custom_id": "first",
                            "params": {
                                **base,
                                "extra_body": {
                                    "provider": {
                                        "only": ["deepinfra"],
                                        "allow_fallbacks": True,
                                    }
                                },
                            },
                        }
                    ]
                )
            client.request.assert_not_called()

    def test_declined_speaker_preflight_retains_provider_work_and_resets_retry_phase(
        self,
    ):
        # The native worker reports several failures with the same canceled message.
        # Only its explicit no-submission evidence can retire a first declined run.
        import threading
        from copy import deepcopy

        with TemporaryDirectory() as temporary:
            source = Path(temporary)
            folder = source / "profile/manual/jobs/fixture"
            plan = {"mode": "batch"}
            write_json(folder / "plan.json", plan)
            write_json(
                folder / "attempt.json", {"resume": False, "batch_resume_state": None}
            )
            job = {
                "id": "fixture",
                "status": "failed",
                "mode": "batch",
                "phase": "preparing",
                "message": "Speaker translation canceled",
                "log": [DECLINED_SPEAKERS],
                "outputs": {},
                "completed": [],
                "errors": {},
                "mismatches": {},
                "plan_hash": digest((folder / "plan.json").read_bytes()),
            }
            self.assertTrue(canceled_before_submission(job, folder))
            for changes in (
                {"log": []},
                {"phase": "consume"},
                {"outputs": {"Items.json": "receipt"}},
                {"completed": ["Items.json"]},
                {"errors": {"Items.json": "Parse failure"}},
                {"batch_root": "/fixture/paid-queue"},
                {"batch_detail": {"id": "provider-id"}},
                {"plan_hash": "changed"},
            ):
                self.assertFalse(canceled_before_submission({**job, **changes}, folder))
            write_json(
                folder / "attempt.json", {"resume": True, "batch_resume_state": None}
            )
            self.assertFalse(canceled_before_submission(job, folder))
            write_json(
                folder / "attempt.json", {"resume": False, "batch_resume_state": None}
            )
            write_json(
                folder / "log/batch_state.json",
                {"status": "submitted", "id": "retained"},
            )
            self.assertFalse(canceled_before_submission(job, folder))
            (folder / "log/batch_state.json").unlink()
            write_json(folder / "job.json", job)
            module = source / "desktop/backend/manual.py"
            module.parent.mkdir(parents=True)
            module.write_text("""import json, threading
from pathlib import Path
from tests.engine import point
launch_worker = point(lambda *_args, **_kwargs: None)
class ManualJobs:
    def __init__(self, workspace, lock, **kwargs):
        self.root = Path(workspace)/'manual'
        self.lock = lock
        self.stopping = threading.Event()
        self.jobs = {}
        self.load_saved()
    def folder(self, identity): return self.root/'jobs'/identity
    def load_saved(self):
        self.jobs['fixture'] = json.loads((self.folder('fixture')/'job.json').read_text())
    def _event(self, job, event):
        if event['event'] == 'log': return
        job.update(status='canceled' if job['phase']=='canceled' else 'complete' if event['args'][0] else 'failed', message=event['args'][1])
    def _launch(self, job, resume): job['status'] = 'running'
""")
            controller = manual_jobs(
                source, source / "profile", threading.RLock(), False
            )
            self.assertEqual(controller.jobs["fixture"]["status"], "canceled")
            self.assertEqual(json.loads((folder / "job.json").read_text()), job)
            # Retry must not inherit canceled phase and hide a subsequent paid failure.
            retry = deepcopy(controller.jobs["fixture"])
            controller._launch(retry, True)
            self.assertEqual(retry["phase"], "preparing")
            write_json(
                folder / "attempt.json", {"resume": True, "batch_resume_state": None}
            )
            controller._event(
                retry,
                {"event": "finished", "args": [False, "Speaker translation canceled"]},
            )
            self.assertEqual(retry["status"], "failed")
            self.assertEqual(retry["log"], job["log"])
            # Fresh explicit decline is canceled; a failure after payment keeps outputs.
            write_json(
                folder / "attempt.json", {"resume": False, "batch_resume_state": None}
            )
            fresh = {**deepcopy(job), "status": "running"}
            controller._event(
                fresh,
                {"event": "finished", "args": [False, "Speaker translation canceled"]},
            )
            self.assertEqual(fresh["status"], "canceled")
            paid = {
                **deepcopy(job),
                "status": "running",
                "outputs": {"Items.json": "kept"},
            }
            controller._event(
                paid,
                {"event": "finished", "args": [False, "Speaker translation canceled"]},
            )
            self.assertEqual(
                (paid["status"], paid["outputs"]), ("failed", {"Items.json": "kept"})
            )
            # A failure the engine only summarizes names its first file error.
            broken = {
                **deepcopy(job),
                "status": "running",
                "errors": {"Map001.json": "Connection refused", "Map002.json": "x"},
            }
            controller._event(
                broken, {"event": "finished", "args": [False, "Translation failed"]}
            )
            self.assertIn("Map001.json: Connection refused", broken["message"])
            controller._event(paid, {"event": "finished", "args": [True, "Completed"]})
            self.assertEqual(
                (paid["status"], paid["outputs"]), ("complete", {"Items.json": "kept"})
            )
            # Keep every file's metric receipt after the native log cap, and
            # never present Batch collection/estimate figures as paid results.
            from dazedtl.compatibility.process_view import file_metrics

            metric_run = {
                "mode": "batch",
                "phase": "collect",
                "files": ["Items.json"],
                "log": [],
            }
            event = {
                "event": "log",
                "args": [
                    "Items.json: [Input: 120] [Output: 20] [Cost: $0.0042] [12.5s] ✓"
                ],
            }
            controller._event(metric_run, event)
            self.assertEqual(file_metrics(metric_run), {})
            metric_run["phase"] = "consume"
            controller._event(metric_run, event)
            metric_run["phase"] = "done"
            self.assertEqual(
                file_metrics(metric_run),
                {"Items.json": {"cost": 0.0042, "seconds": 12.5}},
            )
            restored = json.loads(json.dumps(metric_run))
            self.assertEqual(file_metrics(restored), file_metrics(metric_run))
            legacy = {
                "mode": "translate",
                "files": ["Items.json"],
                "log": event["args"],
            }
            self.assertEqual(file_metrics(legacy), file_metrics(restored))
            legacy["files"] = ["Other.json"]
            self.assertEqual(file_metrics(legacy), {})

    def test_event_text_catalog_excludes_dictionary_keys_but_retains_coarse_handlers(
        self,
    ):
        from dazedtl.compatibility.event_text import catalog

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "modules").mkdir()
            (root / "modules/rpgmakermvmz.py").write_text("""
HEADER_MAPPINGS_357 = {"Case/Plugin": (["message"], "font")}
PATTERNS_355655 = {"gameVariables.setValue": ("text(.+)", False)}
def parse(codeList, i, headerString, jaString):
    if codeList[i]["code"] == 357 and CODE357:
        if headerString == "BuiltIn" and len(codeList[i]["parameters"]) > 3:
            pass
        if "SelectedPlugin" in headerString and "SelectedPlugin" in ENABLED_PLUGINS_357:
            pass
    if codeList[i]["code"] == 355 and CODE355655:
        if "_Text" in jaString and codeList[i]["code"] == 355:
            pass
    if codeList[i]["code"] == 356 and CODE356:
        if "MessageCommand" in jaString:
            pass
        if "AlwaysCheckedChoice":
            pass
""")
            rows = {row["key"]: row for row in catalog(root)["controls"]}
            self.assertEqual(rows["CODE357"]["builtins"], ["BuiltIn"])
            self.assertEqual(rows["CODE355655"]["builtins"], ["_Text"])
            self.assertEqual(
                rows["CODE356"]["builtins"], ["AlwaysCheckedChoice", "MessageCommand"]
            )
            self.assertEqual(rows["CODE357"]["choices"][0]["id"], "Case/Plugin")
            self.assertIn("message", rows["CODE357"]["choices"][0]["details"])
            self.assertEqual(rows["CODE356"]["choices"], [])

    def test_preparation_preview_keeps_native_guards_and_public_configuration(self):
        from dazedtl.compatibility.dazedmtl import ExistingBackend

        backend = ExistingBackend.__new__(ExistingBackend)
        plans = {}

        def preview(owner, action, options):
            self.assertEqual((owner, action, options), ("fixture", "prepare", {}))
            plans["token"] = {
                "action": action,
                "label": "Prepare game files",
                "guard": {"data": "source-hash"},
                "options": {"public_settings": {"gameUpdateUsername": "fixture"}},
            }
            return {"token": "token", "options": plans["token"]["options"]}

        backend.workflows = SimpleNamespace(previews=plans, preview=preview)
        result = backend.guided_preparation_preview("fixture", "prepare_game", {})
        self.assertEqual(plans["token"]["action"], "prepare_game")
        self.assertEqual(plans["token"]["guard"], {"data": "source-hash"})
        self.assertEqual(
            result["options"]["public_settings"]["gameUpdateUsername"], "fixture"
        )

    def test_speaker_scan_rejects_partial_parser_results_without_finalizing_names(self):
        engine = SimpleNamespace(
            SPEAKER_COLLECTED=[],
            MISMATCH=[],
            resetSpeakerState=Mock(),
            setSpeakerParseMode=Mock(),
            finalizeSpeakerParse=Mock(
                side_effect=AssertionError("Must not translate names")
            ),
        )
        engine.openFiles = point(
            lambda name: (
                {},
                [0, 0],
                ValueError("broken JSON") if name == "bad.json" else None,
            )
        )

        def handle(name, _estimate):
            engine.openFiles(name)
            engine.SPEAKER_COLLECTED.extend(["リーナ", "リーナ"])

        engine.handleMVMZ = handle
        self.assertEqual(
            collect_speakers(engine, ["good.json"], lambda _: None), ["リーナ"]
        )
        with self.assertRaisesRegex(ValueError, "bad.json"):
            collect_speakers(engine, ["good.json", "bad.json"], lambda _: None)
        engine.setSpeakerParseMode.assert_called_with(False)
        engine.finalizeSpeakerParse.assert_not_called()

    def test_apply_uses_reviewed_selection_even_when_other_outputs_are_prepared(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {
                "options": {"files": ["Items.json"]},
                "folder": str(root / "work"),
                "project": {
                    "source": str(root / "game"),
                    "data": str(root / "game/data"),
                    "engine": "MVMZ",
                },
                "guard": {
                    "files": {"Items.json": "input", "System.json": "input"},
                    "translated": {"Items.json": "output", "System.json": "output"},
                },
            }
            actions = ModuleType("desktop.backend.workflow_actions")
            actions.validate_plan = Mock()
            actions.regular = lambda _root, path: path
            scanner = ModuleType("util.project_scanner")
            scanner.export_to_game = Mock(return_value=(1, []))
            with patch.dict(
                sys.modules, {actions.__name__: actions, scanner.__name__: scanner}
            ):
                self.assertEqual(apply_selected(plan, lambda _: None)["files"], 1)
                self.assertEqual(
                    scanner.export_to_game.call_args.kwargs["filenames"], ["Items.json"]
                )
                actions.validate_plan.assert_called_once_with(plan)
                plan["options"]["files"] = ["Missing.json"]
                with self.assertRaises(ValueError):
                    apply_selected(plan, lambda _: None)
                self.assertEqual(scanner.export_to_game.call_count, 1)

    def test_guided_patch_proposal_keeps_previously_tracked_runtime_assets(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            write_json(game / "data/Items.json", [None])
            (game / "img").mkdir()
            (game / "img/title.png").write_bytes(b"generated asset fixture")
            (game / "README.md").write_text("Repository metadata")
            preparation = ModuleType("util.project_preparation")
            preparation.rpgmaker_layout = lambda _: {
                "engine": "MVMZ",
                "data_path": game / "data",
                "plugins_js": None,
            }
            preparation.RPG_GAMEUPDATE_COPY_SKIP_NAMES = set()
            paths = ModuleType("util.paths")
            paths.PROJECT_ROOT = root / "engine"
            scope = ModuleType("util.len_patch_scope")
            scope.patch_manifest = lambda value: value
            git = ModuleType("util.version_update.git_workflow")
            git._run_git = lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0, stdout="img/title.png\0README.md\0"
            )
            with patch.dict(
                sys.modules,
                {
                    module.__name__: module
                    for module in (preparation, paths, scope, git)
                },
            ):
                self.assertEqual(
                    runtime_files(game), ["data/Items.json", "img/title.png"]
                )

    def test_ace_packing_saves_a_receipt_only_when_every_export_was_packed(self):
        from dazedtl.translation.release import packing_state

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            game, folder = root / "game", root / "profile/workflows/project"
            folder.mkdir(parents=True)
            for name in ("CommonEvents", "Items"):
                write_json(game / f"ace_json/{name}.json", [None, {"name": name}])
            native = {
                "source": str(game),
                "data": str(game / "ace_json"),
                "engine": "ACE",
            }
            plan = {"action": "ace_pack", "folder": str(folder), "project": native}
            packed = []

            def pack(_root, _action, _log):
                for name in packed:
                    path = game / "Data" / name
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(b"\x04\x08generated " + name.encode())
                return [game / "Data" / name for name in packed]

            converter = ModuleType("util.ace")
            converter.actions = SimpleNamespace(run=pack)
            workflow = ModuleType("desktop.backend.workflow_actions")
            workflow.validate_plan = lambda _plan: None
            with patch.dict(
                sys.modules,
                {"util.ace": converter, "desktop.backend.workflow_actions": workflow},
            ):
                # The game names its common events file in another case.
                packed[:] = ["Commonevents.rvdata2", "Scripts.rvdata2"]
                with self.assertRaisesRegex(ValueError, "ace_json/Items.json"):
                    run_ace(plan, lambda _line: None)
                self.assertFalse(packing_state(native, folder)["current"])
                packed.append("Items.rvdata2")
                self.assertEqual(
                    run_ace(plan, lambda _line: None), {"completed": "ace_pack"}
                )
                self.assertTrue(packing_state(native, folder)["current"])

    def test_phased_worker_launcher_preserves_pipe_controls_and_isolates_the_child(
        self,
    ):
        # A substituted subprocess namespace once dropped PIPE before launch; the
        # launch layer must keep the native pipe controls.
        with TemporaryDirectory() as temporary:
            source = Path(temporary)
            module = source / "desktop/backend/manual.py"
            module.parent.mkdir(parents=True)
            module.write_text("""import subprocess, sys, threading
from pathlib import Path
from tests.engine import point
@point
def launch_worker(arguments, **kwargs):
    return subprocess.Popen(arguments, **kwargs)
class ManualJobs:
    def __init__(self, workspace, lock, **kwargs):
        self.workspace = workspace
        self.root = workspace/'manual'
        self.lock = threading.RLock()
        self.jobs, self.worker, self.process, self.active = {}, None, None, ''
        self.allow_providers = False
    def running(self): return False
    def start(self, source, engine, files, *args, **kwargs): return {'id': str(len(files)), 'files': files}
    def save(self, job): pass
    def stop(self, identity): return self.jobs[identity]
    def close(self):
        if self.active: self.stop(self.active)
    def launch(self):
        return launch_worker([sys.executable, '-u', str(Path(__file__).with_name('manual_worker.py')), str(self.workspace/'run')],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, env={})
""")
            with patch("subprocess.Popen") as launch:
                controller = manual_jobs(source, source / "profile", None, False)
                run = source / "profile/run"
                write_json(run / "job.json", {})
                controller.launch()
                args, kwargs = launch.call_args
                self.assertEqual(Path(args[0][2]).name, "manual_worker.py")
                self.assertNotEqual(Path(args[0][2]).parent, module.parent)
                self.assertEqual(
                    (kwargs["stdin"], kwargs["stdout"]),
                    (subprocess.PIPE, subprocess.PIPE),
                )
                self.assertEqual(kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
                # A collected-only worker must never fall back to queued or
                # partially submitted work, even if state changed before launch.
                write_json(
                    run / "job.json", {"mode": "batch", "dazedtl_consume_only": True}
                )
                for state in ("queued", "partially_submitted", "submitted", None):
                    write_json(
                        run / "attempt.json",
                        {"resume": True, "batch_resume_state": state},
                    )
                    with self.assertRaisesRegex(ValueError, "already collected"):
                        controller.launch()
                self.assertEqual(launch.call_count, 1)
                write_json(
                    run / "attempt.json",
                    {"resume": True, "batch_resume_state": "fetched"},
                )
                controller.launch()
                self.assertEqual(launch.call_count, 2)
                # App shutdown must not revoke an approved Batch's remainder;
                # an explicit stop must prevent automatic continuation.
                controller.jobs["batch"] = {"id": "batch", "mode": "batch"}
                child = controller.controller("batch")
                child.active = "batch"
                child.close()
                self.assertNotIn("dazedtl_batch_stopped", controller.jobs["batch"])
                controller.stop("batch")
                self.assertTrue(controller.jobs["batch"]["dazedtl_batch_stopped"])
                # The preserved phase may find more files than the user checked.
                # Filter only its new run, preserving its native phase setup.
                with controller.selected_workflow("owner", ["Items.json"]):
                    self.assertEqual(
                        controller.start(
                            "work",
                            "engine",
                            ["Items.json", "System.json"],
                            workflow={"id": "owner"},
                        )["files"],
                        ["Items.json"],
                    )
                    with self.assertRaises(ValueError):
                        controller.start(
                            "work",
                            "engine",
                            ["Items.json"],
                            workflow={"id": "another-owner"},
                        )
                self.assertEqual(
                    controller.start("work", "engine", ["Items.json", "System.json"])[
                        "files"
                    ],
                    ["Items.json", "System.json"],
                )
            workflow = ModuleType("desktop.backend.workflow")
            collected = []

            class Workflows:
                def __init__(self, workspace, lock, operations, manual):
                    self.root, self.manual, self.operations = (
                        workspace,
                        SimpleNamespace(jobs={}),
                        operations,
                    )

                def folder(self, identity):
                    return self.root / identity

                def _collect(self, project):
                    collected.append(project["manual_job"])

            workflow.Workflows = Workflows
            with patch.dict(sys.modules, {workflow.__name__: workflow}):
                operations = SimpleNamespace(jobs={})
                phases = phased_workflows(
                    source / "phases", None, operations, controller
                )
                write_json(
                    phases.folder("owner") / "source-inputs.json",
                    {"version": 1, "inputs": {}, "retired_runs": ["older-source-run"]},
                )
                phases._collect({"id": "owner", "manual_job": "older-source-run"})
                self.assertEqual(collected, [])
                phases._collect({"id": "owner", "manual_job": "current-source-run"})
                self.assertEqual(collected, ["current-source-run"])
                # Reloading Items must not resurrect its old checkpoint, while
                # an unaffected file in the same interrupted run remains usable.
                phases.save = lambda _: None
                phases.manual.folder = lambda identity: source / "saved-runs" / identity
                directory = phases.manual.folder("partial")
                before = {
                    "Items.json": [{"name": "薬"}],
                    "System.json": {"gameTitle": "題"},
                }
                for name, value in before.items():
                    write_json(phases.folder("owner") / "files" / name, value)
                    write_json(directory / "files" / name, value)
                    write_json(directory / "translated" / name, {"translated": name})
                plan = {
                    "workflow": {"id": "owner"},
                    "files": [
                        {
                            "name": name,
                            "sha256": digest((directory / "files" / name).read_bytes()),
                        }
                        for name in before
                    ],
                }
                write_json(directory / "plan.json", plan)
                plan_hash = digest((directory / "plan.json").read_bytes())
                write_json(
                    directory / "log/dazedtl-checkpoints.json",
                    {
                        "version": 1,
                        "plan_hash": plan_hash,
                        "files": {
                            name: digest((directory / "translated" / name).read_bytes())
                            for name in before
                        },
                    },
                )
                phases.manual.jobs["partial"] = {
                    "id": "partial",
                    "files": list(before),
                    "mode": "translate",
                    "status": "interrupted",
                    "plan_hash": plan_hash,
                }
                # Scratch collection before cost approval cannot become saved output.
                phases.manual.jobs["partial"]["dazedtl_preapproval"] = True
                phases._collect({"id": "owner", "manual_job": "partial"})
                self.assertFalse(
                    (phases.folder("owner") / "translated/System.json").exists()
                )
                self.assertNotIn("partial", collected)
                phases.manual.jobs["partial"]["dazedtl_approved"] = True
                # Approval starts provider work, but collection-pass JSON is
                # still scratch data until the consume pass actually runs.
                phases.manual.jobs["partial"].update(mode="batch", phase="poll_status")
                phases._collect({"id": "owner", "manual_job": "partial"})
                self.assertFalse(
                    (phases.folder("owner") / "translated/System.json").exists()
                )
                phases.manual.jobs["partial"]["phase"] = "consume"
                # Neither collection path may publish into the workspace while
                # reload is between its archive and replacement writes.
                operations.jobs["reload"] = {
                    "project_id": "owner",
                    "action": "refresh_sources",
                    "status": "running",
                }
                collected.clear()
                phases._collect({"id": "owner", "manual_job": "partial"})
                self.assertEqual(collected, [])
                self.assertFalse(
                    (phases.folder("owner") / "translated/System.json").exists()
                )
                write_json(
                    phases.folder("owner") / "source-inputs.json",
                    {
                        "version": 1,
                        "inputs": {},
                        "file_versions": {"Items.json": "reloaded"},
                    },
                )
                operations.jobs["reload"]["status"] = "complete"
                project = {"id": "owner", "manual_job": "partial"}
                phases._collect(project)
                self.assertFalse(
                    (phases.folder("owner") / "translated/Items.json").exists()
                )
                self.assertEqual(
                    json.loads(
                        (phases.folder("owner") / "translated/System.json").read_text()
                    ),
                    {"translated": "System.json"},
                )
                # Completing the same Batch later still cannot restore Items
                # through the native full-run collector or the partial collector.
                phases.manual.jobs["partial"].update(
                    status="complete",
                    outputs={
                        name: digest((directory / "translated" / name).read_bytes())
                        for name in before
                    },
                )
                phases._collect(project)
                self.assertEqual(collected, [])
                self.assertFalse(
                    (phases.folder("owner") / "translated/Items.json").exists()
                )
                self.assertTrue((directory / "translated/Items.json").is_file())

    def test_full_overwrite_ignores_game_edits_but_binds_the_reviewed_working_output(
        self,
    ):
        from dazedtl.compatibility.text import validate_publication

        actions = ModuleType("desktop.backend.workflow_actions")
        current = {
            "layout": "same game",
            "data": "new manual edits",
            "translated": "reviewed output",
        }
        actions.action_guard = lambda *_: current
        actions.validate_plan = Mock()
        plan = {
            "action": "export_selected",
            "overwrite_runtime": True,
            "project": {},
            "folder": "work",
            "guard": {**current, "data": "before edits"},
        }
        with patch.dict(sys.modules, {actions.__name__: actions}):
            validate_publication(plan)
            actions.validate_plan.assert_not_called()
            current["translated"] = "different output"
            with self.assertRaises(ValueError):
                validate_publication(plan)

    def test_rewrap_apply_requires_the_same_completed_scan_and_settings(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = {"options": {"width": 50}, "guard": {"data": "reviewed"}}
            path = root / "scan/plan.json"
            write_json(path, plan)
            job = {
                "id": "scan",
                "project_id": "game",
                "action": "rewrap_preview",
                "status": "complete",
                "created": "today",
                "result": {"changes_found": 1},
                "plan_hash": digest(path.read_bytes()),
            }
            backend = SimpleNamespace(
                operations=SimpleNamespace(root=root, jobs={"scan": job}),
                workflows=SimpleNamespace(previews={"token": plan}),
            )
            self.assertEqual(
                rewrap_review(backend, "game", "token"), {"changes_found": 1}
            )
            for current in (
                {**plan, "options": {"width": 60}},
                {**plan, "guard": {"data": "changed"}},
            ):
                backend.workflows.previews["token"] = current
                with self.assertRaises(ValueError):
                    rewrap_review(backend, "game", "token")
            with self.assertRaises(ValueError):
                rewrap_review(backend, "other-game", "token")

    def test_line_metadata_reaches_both_provider_payloads_without_changing_the_legacy_batch_contract(
        self,
    ):
        package, context_module, skill_module, provider_module = (
            ModuleType(name)
            for name in (
                "util",
                "util.len_translation",
                "util.skills",
                "util.translation",
            )
        )
        note = "Check whether the visitor or guard left."
        source_context = "門に二人がいる。"

        def contexts(_project, batches):
            self.assertEqual(
                set(batches[0]),
                {"id", "sources", "speakers", "source_context", "instruction_key"},
            )
            self.assertEqual(batches[0]["speakers"], {"line": None})
            return [
                {
                    "context": {
                        "system": "Translate into English",
                        "glossary": "Approved names and voice",
                        "sfx_reference": "SFX",
                        "user": json.dumps(batch["sources"], ensure_ascii=False),
                        "preceding_japanese_source_context": batch["source_context"],
                        "request_instructions": "Field guidance",
                    }
                }
                for batch in batches
            ]

        context_module.request_contexts = contexts
        skill_module.ctx = lambda *_args, **_kwargs: "Field guidance"
        provider_module.buildClaudeRequest = lambda **kwargs: {
            "captured": kwargs,
            "max_tokens": 8192,
        }
        provider_module.buildOpenAIRequest = lambda **kwargs: {
            "captured": kwargs,
            "temperature": 0,
            "model": kwargs["model"],
            "max_tokens": 8192,
            "frequency_penalty": 0.05,
            "reasoning_effort": "none",
            "extra_body": {"prompt_cache_key": "fixture-cache"},
        }
        modules = {
            module.__name__: module
            for module in (package, context_module, skill_module, provider_module)
        }
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.project = lambda *_args: None
        engine.compiler_fingerprint = lambda: "compiler"
        plan = {
            "batches": [
                {
                    "id": "scene",
                    "sources": {"line": "行った。"},
                    "kinds": {"line": "dialogue"},
                    "speakers": {"line": None},
                    "qa_notes": {"line": note},
                    "source_context": source_context,
                    "scene_context": "Two people at the gate",
                    "instruction_key": "dialogue",
                }
            ]
        }
        with patch.dict(sys.modules, modules):
            rows, _compiler = compile_requests(engine, "unused", {}, plan, "English")
            row = rows[0]
            self.assertEqual(row["context"]["line_kinds"], {"line": "dialogue"})
            self.assertEqual(row["context"]["qa_notes"], {"line": note})
            for provider, protocol, mode in (
                ("openai", "openai", "live"),
                ("anthropic", "anthropic", "batch"),
                ("openrouter", "openai", "live"),
                ("gemini", "gemini", "batch"),
                ("mistral", "mistral", "live"),
                ("custom", "openai", "live"),
            ):
                with self.subTest(protocol=protocol):
                    payload = engine.payload(
                        row,
                        {
                            "protocol": protocol,
                            "provider": provider,
                            "mode": mode,
                            "model": "fixture",
                            "endpoint": "https://provider.invalid/v1",
                            "openrouterHost": "deepinfra",
                            "maxOutputTokens": 32768,
                            "generationParameters": GENERATION_PARAMETERS,
                        },
                    )
                    self.assertFalse(
                        {"temperature", "frequency_penalty", "reasoning_effort"}
                        & payload.keys()
                    )
                    self.assertEqual(payload["max_tokens"], 32768)
                    sent = payload["captured"]
                    self.assertEqual(sent["user"], row["context"]["user"])
                    self.assertIn(note, sent["user"])
                    self.assertEqual(sent["history"], source_context)
                    self.assertIn("Approved names and voice", sent["vocab_text"])
                    self.assertIn(
                        "Two people at the gate", sent["request_instructions"]
                    )
                    if provider == "openrouter":
                        self.assertEqual(
                            payload["response_format"], {"type": "json_object"}
                        )
                        self.assertEqual(
                            payload["extra_body"],
                            {
                                "prompt_cache_key": "fixture-cache",
                                "provider": {
                                    "only": ["deepinfra"],
                                    "allow_fallbacks": False,
                                },
                            },
                        )
                    else:
                        self.assertNotIn("provider", payload.get("extra_body", {}))

            # New OpenRouter plans require the exact source-ID schema on both
            # transports; the legacy branch above retains its saved JSON mode.
            from dazedtl.settings.openrouter import STRUCTURED_OUTPUTS, TRANSPORT
            from dazedtl.translation.requests import output_schema

            router_policy = {
                "transport": TRANSPORT,
                "model": "deepseek/fixture",
                "host": "",
                "input": 1,
                "output": 2,
                "max_requests": 100,
                "max_bytes": 10000,
                "structuredOutputs": STRUCTURED_OUTPUTS,
                "providers": ["deepinfra", "fireworks"],
            }
            for mode in ("live", "batch"):
                for host in ("", "deepinfra"):
                    batch_policy = {
                        **router_policy,
                        "host": host,
                        "providers": [host] if host else router_policy["providers"],
                    }
                    payload = engine.payload(
                        row,
                        {
                            "protocol": "openai",
                            "provider": "openrouter",
                            "mode": mode,
                            "model": "deepseek/fixture",
                            "endpoint": "https://openrouter.ai/api/v1",
                            "openrouterHost": host,
                            "openrouterStructuredOutputs": STRUCTURED_OUTPUTS,
                            "openrouterBatch": batch_policy,
                        },
                    )
                    self.assertEqual(
                        payload["response_format"],
                        {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "translation",
                                "strict": True,
                                "schema": output_schema(row["sources"]),
                            },
                        },
                    )
                    expected = (
                        {
                            "require_parameters": True,
                            **(
                                {"only": [host], "allow_fallbacks": False}
                                if host
                                else {}
                            ),
                        }
                        if mode == "live"
                        else {
                            "only": batch_policy["providers"],
                            "allow_fallbacks": False,
                        }
                    )
                    self.assertEqual(
                        payload["extra_body"],
                        {"prompt_cache_key": "fixture-cache", "provider": expected},
                    )

    def test_native_update_completion_property_survives_public_serialization(self):
        @dataclass
        class Update:
            translation_commit: str | None
            pending_conflicts: tuple = ()

            @property
            def complete(self):
                return (
                    self.translation_commit is not None and not self.pending_conflicts
                )

        package = ModuleType("util")
        module = ModuleType("util.version_update")
        package.version_update = module
        engine = TranslationEngine.__new__(TranslationEngine)
        for result in (Update("saved"), Update(None, ("data/Items.json",))):
            with self.subTest(result=result):
                module.continue_with_official = lambda _source: result
                with patch.dict(
                    sys.modules, {"util": package, "util.version_update": module}
                ):
                    value = engine.version(Path("unused"), "continue", {})
                self.assertEqual(value["complete"], result.complete)
                self.assertEqual(value["pending_conflicts"], result.pending_conflicts)

    def test_provider_errors_do_not_reveal_credentials_or_request_bodies(self):
        @provider_errors
        def request():
            raise ValueError(
                "Invalid Authorization header: Bearer fixture-private-key; private request body"
            )

        with self.assertRaises(ProviderFailure) as raised:
            request()
        self.assertNotIn("fixture-private-key", str(raised.exception))
        self.assertNotIn("private request body", str(raised.exception))
        self.assertIsNone(raised.exception.status_code)

    def test_progress_reports_leave_a_checkpointed_gitignore_unchanged(self):
        # A checkpoint after an image apply leaves the image rules between
        # Len's work block and its patch block. Moving the work block again
        # dirtied the committed .gitignore, so packaging refused.
        script = """
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from util.len_translation import _WORK_IGNORE_BLOCK, _prepare_local_work
root = Path(sys.argv[2])
text = (_WORK_IGNORE_BLOCK + "\\n# DazedTL selected image patches\\n!/img/\\n"
        "\\n# BEGIN DazedTL Len patch files\\n/*\\n# END DazedTL Len patch files\\n")
(root / ".gitignore").write_text(text)
_prepare_local_work(SimpleNamespace(game_root=root, work_root=root / "work"))
print((root / ".gitignore").read_text() == text)
"""
        with TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", script, str(ENGINE), folder],
                capture_output=True,
                text=True,
                check=True,
            )
        self.assertEqual(result.stdout.strip(), "True")

    def test_bundled_forge_accepts_the_install_patches(self):
        # Upstream refreshes rename Forge's minified identifiers; patches pinned
        # to the old names made every Forge install fail.
        patches = engine_module("util/forge/modern_patches.py")
        bundle = ENGINE / "util/forge/upstream/Forge_MZ.js"
        text = patches.apply_modern_forge_patches(
            bundle.read_text(encoding="utf-8"), "Ctrl+F9"
        )
        self.assertIn("keyStr:`ctrl f9`", text)
