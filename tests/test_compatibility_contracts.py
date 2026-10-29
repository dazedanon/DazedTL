"""Focused contracts at the maintained-engine boundary, without importing a sibling checkout."""

import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from dazedtl.actions import ROWS, handler
from dazedtl.compatibility import game_write
from dazedtl.compatibility.guided import (
    phased_workflows,
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
from dazedtl.settings import effort
from dazedtl.settings.preferences import GENERATION_PARAMETERS
from dazedtl.settings.providers import PROVIDERS
from dazedtl.storage import write_json
from dazedtl.translation.compilation import compile_requests
from dazedtl.translation.files import digest

from tests.engine import ENGINE, engine_module, point, replaced_modules
from tests.probe import Background

# Engine scripts for the tests of the same names below. Each runs in an
# interpreter of its own, where only the engine is importable, and starts
# beside the rest of the suite.
GITIGNORE = """
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from util.len_patch_scope import scope_ignore
from util.len_translation import _WORK_IGNORE_BLOCK, _prepare_local_work
from util.paths import GAME_TOOL_GITIGNORE_BLOCK
root = Path(sys.argv[2])
# A checkpointed game's Git is set up, a commit on its branch, whose history
# the work block serves.
(root / ".git/refs/heads").mkdir(parents=True, exist_ok=True)
(root / ".git/HEAD").write_text("ref: refs/heads/translated\\n")
(root / ".git/refs/heads/translated").write_text("0" * 40 + "\\n")
patch = "# BEGIN DazedTL Len patch files\\n/*\\n# END DazedTL Len patch files\\n"
text = (_WORK_IGNORE_BLOCK + "\\n# DazedTL selected image patches\\n!/img/\\n"
        "\\n" + patch + "\\n" + GAME_TOOL_GITIGNORE_BLOCK)
(root / ".gitignore").write_text(text)
_prepare_local_work(SimpleNamespace(game_root=root, work_root=root / "work"))
print((root / ".gitignore").read_text() == text)
(root / ".gitignore").write_text(patch + "\\n" + GAME_TOOL_GITIGNORE_BLOCK)
_prepare_local_work(SimpleNamespace(game_root=root, work_root=root / "work"))
result = (root / ".gitignore").read_text()
print(result.index(_WORK_IGNORE_BLOCK) < result.index(patch) and result.endswith(patch + "\\n" + GAME_TOOL_GITIGNORE_BLOCK))
(root / ".gitignore").write_text(GAME_TOOL_GITIGNORE_BLOCK)
_prepare_local_work(SimpleNamespace(game_root=root, work_root=root / "work"))
print((root / ".gitignore").read_text().endswith("\\n" + GAME_TOOL_GITIGNORE_BLOCK))
for text in (GAME_TOOL_GITIGNORE_BLOCK + "\\n" + patch, patch + "\\n" + GAME_TOOL_GITIGNORE_BLOCK):
    scoped = scope_ignore(text, {"data/x.json"})
    print(scope_ignore(scoped, {"data/x.json"}) == scoped)
print(scope_ignore("A\\n\\n" + patch + "\\nB\\n", set()).startswith("A\\n\\nB\\n"))
"""

PATCH_FILES = """
import sys
from pathlib import Path
sys.path[:0] = sys.argv[1:3]
from dazedtl.compatibility.translation import TranslationEngine
game = Path(sys.argv[3])
(game / "Game.exe").write_bytes(b"original")
added = {"Game.exe": {}, "BepInEx/plugins/Patch.dll": {"original_sha256": None}}
TranslationEngine.audit_scope(None, game, {"files": added})
try:
    TranslationEngine.audit_scope(None, game, ["Game.exe", "winhttp.dll"])
except ValueError as error:
    print(error)
"""

IMAGES_PHASE = """
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from util.len_translation import LenProject
from util.len_progress import read_progress, update_progress
root = Path(sys.argv[2])
work = root / ".dazedtl/len-method/work"
work.mkdir(parents=True)
(root / "a.png").write_bytes(b"image")
units = {"text": [{"id": "a", "source": "はい", "translation": "Yes",
                   "translated_from_sha256": hashlib.sha256("はい".encode()).hexdigest()}],
         "images": [{"id": "a.png", "source": "a.png", "translation": None}]}
for kind, rows in units.items():
    (work / (kind + ".json")).write_text(json.dumps({"complete": True, "units": rows}))
report = {"phase": "injection", "text": ".dazedtl/len-method/work/text.json",
          "images": ".dazedtl/len-method/work/images.json",
          "phases": {"preparation": "complete", "extraction": "complete", "translation": "complete"}}
project = LenProject(root)
results = [update_progress(project, report)["phases"]["images"]]
try:
    update_progress(project, {**report, "phases": {**report["phases"], "images": "complete"}})
except ValueError as error:
    results.append(str(error))
saved = root / ".dazedtl/len-method/progress.json"
old = json.loads(saved.read_text())
del old["phases"]["images"]
saved.write_text(json.dumps(old))
results.append(read_progress(project)["phases"]["images"])
del report["images"]
results.append(update_progress(LenProject(root, include_images=False), report)["phases"]["images"])
# A text export may list parts, so saving one request rewrites one part; it
# counts as the same units in one file.
text = LenProject(root, include_images=False)
rows = [{"id": "b", "source": "いいえ"}, *units["text"]]
def save(name, value):
    (work / name).write_text(json.dumps(value))
save("one.json", {"complete": True, "units": rows})
save("p1.json", {"units": rows[:1]})
save("p2.json", {"units": rows[1:]})
paths = [".dazedtl/len-method/work/p1.json", ".dazedtl/len-method/work/p2.json"]
save("parts.json", {"complete": True, "parts": paths})
def metric(name):
    return update_progress(text, {"text": ".dazedtl/len-method/work/" + name})["metrics"]["text"]
results.append(metric("parts.json") == metric("one.json"))
# An edited part counts again.
save("p1.json", {"units": [{**rows[0], "translation": "No",
                            "translated_from_sha256": hashlib.sha256("いいえ".encode()).hexdigest()}]})
results.append(metric("parts.json")["translated"])
# A unit in two parts, and image parts, are refused.
save("p1.json", {"units": rows[1:]})
save("image-parts.json", {"complete": True, "parts": paths})
for refused in ({"text": ".dazedtl/len-method/work/parts.json"},
                {"images": ".dazedtl/len-method/work/image-parts.json"}):
    try:
        update_progress(project if "images" in refused else text, refused)
    except ValueError as error:
        results.append(str(error))
print(json.dumps(results))
"""

UPDATE_CHECK_TEXT = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from util.game_settings import save_language_pair
from util.rpgmaker_plugin_registry import plugin_entries
from util.translation_update_check.installer import install
root = Path(sys.argv[2])
plugins = root / "js/plugins.js"
plugins.parent.mkdir()
plugins.write_text('var $plugins =\\n[\\n{"name":"A","status":true,"description":"","parameters":{}}\\n];\\n')
def entries():
    return [entry for entry in plugin_entries(plugins.read_text("utf-8"))
            if entry["name"] == "TranslationUpdateCheck"]
results = []
install(root)
results.append(entries()[0]["parameters"])
save_language_pair(root, "English", "Japanese")
install(root)
shown = entries()[0]["parameters"]
results.append(shown["title"])
plugins.write_text(plugins.read_text("utf-8").replace(shown["continueButton"], "つづく"))
install(root)
results.append(entries()[0]["parameters"]["continueButton"])
save_language_pair(root, "Japanese", "English")
install(root)
results.append(entries()[0]["parameters"])
results.append(len(entries()))
print(json.dumps(results, ensure_ascii=False))
"""


def script(source, *paths):
    # UTF-8 mode, as the app and the probe launcher run Python, so a script's
    # Japanese text survives Windows' locale encoding.
    background = Background()
    return background.start(
        [
            sys.executable,
            "-I",
            "-X",
            "utf8",
            "-c",
            source,
            *paths,
            background.folder,
        ],
        merge=False,
    )


gitignore = script(GITIGNORE, ENGINE)
patch_files = script(PATCH_FILES, ENGINE, ENGINE.parents[1])
images_phase = script(IMAGES_PHASE, ENGINE)
update_check_text = script(UPDATE_CHECK_TEXT, ENGINE)


def finished(background):
    returncode, output, errors = background.result()
    if returncode:
        raise AssertionError(errors)
    return output


def checkout(game, *pending):
    """A read of a set-up game's repository with the Git operations `pending`
    under way."""
    from util.version_update.git_workflow import Checkout

    return Checkout(
        selected_root=game,
        repo=game,
        prefix="",
        git_paths={"index": game / ".git/index"},
        current_branch="translation",
        translation_branch="translation",
        original_commit="0" * 40,
        translation_commit="1" * 40,
        pending_operations=pending,
        asset_sync_pending=False,
        settings={"dazedtl.preservegamefiles": "true"},
    )


class Characters:
    """A hermetic stand-in for tiktoken's encoding, which refuses text
    reading as its special token unless told to count it as text."""

    def encode(self, text, *, disallowed_special="all"):
        if disallowed_special and "<|endoftext|>" in str(text):
            raise ValueError(
                "Encountered text corresponding to disallowed special token"
            )
        return [ord(character) for character in str(text)]

    def encode_batch(self, texts, *, disallowed_special="all"):
        return [
            self.encode(text, disallowed_special=disallowed_special) for text in texts
        ]


class CompatibilityContracts(unittest.TestCase):
    def test_an_estimate_priced_for_another_model_matches_that_models_estimate(self):
        # A switch that keeps the requests' text prices an estimate's counts
        # again instead of estimating again, so the figures must be those the
        # engine's own estimate for that model gives, pricing layers included.
        # Assistant-led quotes the same requests by the same rule: its own
        # formula once left out OpenAI's cache, quoting a GPT-5.6 Batch below
        # the most it can cost.
        from dazedtl.compatibility.estimate_prices import reprice
        from dazedtl.translation.requests import CACHE_COUNTS, price
        from util import translation

        rates = {
            "gpt-5.6-sol": (4, 20),
            "gpt-5.6-terra": (2, 12),
            "gpt-4.1": (2, 8),
            "gpt-6.1-sol": (5, 30),
        }

        def request(model, index):
            params = translation.buildOpenAIRequest(
                "System " * 300,
                f"Line {index} " * 200,
                "History",
                0,
                "json",
                model,
                numLines=2,
                vocab_text="Vocabulary",
                api_provider="openai",
                request_instructions="Instructions",
                api_url="https://api.openai.com/v1",
            )
            return {"params": params, "payload": "台詞" * 40, "provider": "openai"}

        with (
            TemporaryDirectory() as temporary,
            patch.object(
                translation,
                "tiktoken",
                SimpleNamespace(encoding_for_model=lambda _model: Characters()),
            ),
            patch.object(
                translation,
                "getPricingConfig",
                lambda model: dict(
                    zip(("inputAPICost", "outputAPICost"), rates[model], strict=True)
                ),
            ),
            patch.object(
                translation, "BATCH_LOCK_FILE", Path(temporary) / "batch.lock"
            ),
            redirect_stdout(StringIO()),
        ):
            # Separately billed cache writes on both sides, from none, to none.
            for before, after in (
                ("gpt-5.6-sol", "gpt-5.6-terra"),
                ("gpt-4.1", "gpt-6.1-sol"),
                ("gpt-6.1-sol", "gpt-4.1"),
            ):
                queue = Path(temporary) / (before + ".json")
                write_json(
                    queue, {str(index): request(before, index) for index in range(3)}
                )
                expected = translation.estimateBatchCost(after, queue_file=queue)
                assert expected is not None
                configuration = {
                    "mode": "batch",
                    "model": after,
                    "provider": "openai",
                    "rates": dict(zip(("input", "output"), rates[after])),
                }
                repriced = reprice(
                    translation.estimateBatchCost(before, queue_file=queue),
                    configuration,
                    "openai",
                )
                self.assertEqual({key: repriced[key] for key in expected}, expected)
                counts = TranslationEngine.openai_cache(
                    [request(after, index) for index in range(3)]
                )
                self.assertEqual(
                    counts,
                    {key: expected[key] for key in ("input_tokens", *CACHE_COUNTS)},
                )
                quoted = price(
                    {
                        "requests": 3,
                        "units": 3,
                        "output_tokens": expected["output_tokens"],
                        **counts,
                    },
                    configuration,
                    "openai",
                )
                # An Assistant-led quote's cost is the most a Batch can cost.
                self.assertEqual(
                    (
                        quoted["live_cost"],
                        quoted["cost"],
                        quoted.get("batch_cost_reused", quoted["cost"]),
                    ),
                    (
                        expected["live_cost"],
                        expected["batch_max_cost"],
                        expected["batch_cached_cost"],
                    ),
                )

    def test_a_claude_batch_estimate_and_quote_give_the_same_figures(self):
        # Guided's estimate and Assistant-led's quote decide a Claude Batch's
        # cache by one rule (claude_cache_prices), with and without cached
        # instructions, so the same requests give the same figures.
        from dazedtl.compatibility.estimate_prices import prices
        from dazedtl.translation.requests import price
        from util import translation

        model = "claude-opus-5-5"

        def request(index, cached):
            system = [{"type": "text", "text": "System " * 300}]
            if cached:
                system[0]["cache_control"] = {"type": "ephemeral"}
            params = {
                "model": model,
                "system": [*system, {"type": "text", "text": f"Context {index % 2}"}],
                "messages": [{"role": "user", "content": f"Line {index} " * 50}],
            }
            return {"params": params, "payload": "台詞" * 40, "provider": "anthropic"}

        with (
            TemporaryDirectory() as temporary,
            patch.object(
                translation,
                "tiktoken",
                SimpleNamespace(encoding_for_model=lambda _model: Characters()),
            ),
            patch.object(
                translation,
                "getPricingConfig",
                lambda _model: {"inputAPICost": 4, "outputAPICost": 20},
            ),
            patch.object(translation, "countClaudeTokens", lambda *_args: None),
            patch.object(
                translation, "BATCH_LOCK_FILE", Path(temporary) / "batch.lock"
            ),
            redirect_stdout(StringIO()),
        ):
            for cached in (True, False):
                with self.subTest(cached=cached):
                    entries = [request(index, cached) for index in range(4)]
                    queue = Path(temporary) / f"{cached}.json"
                    write_json(queue, {str(i): e for i, e in enumerate(entries)})
                    expected = translation.estimateBatchCost(model, queue_file=queue)
                    assert expected is not None
                    # Assistant-led counts the cached prefixes with its own
                    # token count, here the same characters.
                    cache = TranslationEngine.claude_cache(
                        SimpleNamespace(token_count=len), entries, {"model": model}
                    )
                    counts = {
                        key: expected[key] for key in ("input_tokens", "output_tokens")
                    }
                    configuration = {
                        "mode": "batch",
                        "model": model,
                        "provider": "anthropic",
                        "rates": {"input": 4, "output": 20},
                    }
                    value = prices(counts, configuration, "anthropic", cache)
                    self.assertEqual(
                        expected["cache_kind"], "explicit" if cached else None
                    )
                    self.assertEqual(
                        {key: value[key] for key in value if key in expected},
                        {key: expected[key] for key in value if key in expected},
                    )
                    quoted = price(
                        {"requests": 4, "units": 4, **counts},
                        configuration,
                        "anthropic",
                        cache,
                    )
                    self.assertEqual(
                        (
                            quoted["live_cost"],
                            quoted["cost"],
                            quoted.get("batch_cost_reused", quoted["cost"]),
                        ),
                        (
                            expected["live_cost"],
                            expected["batch_max_cost"],
                            expected["batch_cached_cost"],
                        ),
                    )
            # The Live speaker estimate keys, counts and prices its requests'
            # cached prefixes by the same rule, without the Batch discount;
            # it once kept its own copy of each.
            from util.translation_task import TranslationTaskCore

            sent = []
            build = translation.buildClaudeRequest

            def recorded(*args, **kwargs):
                sent.append(build(*args, **kwargs))
                return sent[-1]

            config = translation.TranslationConfig(
                model=model,
                prompt="Name the speakers. " * 40,
                vocab="",
                batchSize=2,
                useSfxReference=False,
            )
            with (
                patch.dict("os.environ", {"api": ""}),
                patch.object(translation, "buildClaudeRequest", recorded),
            ):
                live = TranslationTaskCore._estimate_grouped_speakers(
                    # A name reading as the encoder's special token is counted
                    # as text, which failed the estimate.
                    ["太郎", "花子", "長老", "<|endoftext|>", "兵士"],
                    "Name each.",
                    config,
                    model,
                )
            entries = [
                {"params": params, "payload": "名前<|endoftext|>"} for params in sent
            ]
            cache = TranslationEngine.claude_cache(None, entries, {"model": model})
            # Two names a request, then one: two reply schemas, one read.
            self.assertEqual((len(sent), cache.keys), (3, 2))
            self.assertEqual(
                live["estimated_cost"],
                translation.claude_cache_cost(
                    cache, live["input_tokens"], live["output_tokens"], 4e-6, 20e-6
                ),
            )
            queue = Path(temporary) / "speakers.json"
            write_json(queue, {str(i): e for i, e in enumerate(entries)})
            expected = translation.estimateBatchCost(model, queue_file=queue)
            assert expected is not None
            self.assertEqual(
                (expected["cache_write_tokens"], expected["cache_max_write_tokens"]),
                (cache.writes, cache.cached),
            )

    def test_a_quote_reads_the_runs_frozen_effort_record_and_counting_rule(self):
        # Assistant-led quotes and repriced estimates judged the effort from
        # DazedTL's notes alone, so a model only its provider's list knows
        # named no default and lost the unestimated-thinking note.
        from dazedtl.compatibility import estimate_prices
        from dazedtl.translation import repricing
        from dazedtl.translation.files import digest
        from dazedtl.translation.service import changed_since, corrected

        listed = {"levels": ["low", "high"], "default": "low", "off": None}
        frozen = {
            "mode": "live",
            "provider": "openrouter",
            "model": "z-ai/glm-6",
            "rates": {"input": 1, "output": 2},
            "thinkingEffortListed": listed,
        }
        counts = {"input_tokens": 1000, "output_tokens": 2500}
        for level, named, thinks in (
            (None, "Provider default (Low)", True),
            ("high", "High", True),
        ):
            value = estimate_prices.prices(
                counts, {**frozen, "thinkingEffort": level}, None
            )
            self.assertEqual(
                (value["thinking_effort"], value["unestimated_thinking_tokens"]),
                (named, thinks),
            )
        # A model switch that changes only that record prices a waiting quote
        # again instead of counting its requests again.
        quote = {"price_rules": repricing.current_rules(), "output_rules": 1}
        current = {**frozen, "thinkingEffortListed": None}
        change = changed_since(current, digest(frozen), frozen, quote, None)
        self.assertTrue(change.priced_only)
        self.assertFalse(corrected(change))
        # A quote counts its output by a versioned rule; one saved before
        # quotes named it stands, and raising it outdates the quote.
        old = {"price_rules": repricing.current_rules()}
        self.assertIsNone(changed_since(frozen, digest(frozen), frozen, old, None))
        with patch.object(estimate_prices, "OUTPUT_RULES_VERSION", 2):
            change = changed_since(frozen, digest(frozen), frozen, old, None)
            self.assertFalse(change.priced_only)
            self.assertTrue(corrected(change))
            # The settings changing as well are still the settings' doing.
            moved = {**frozen, "endpoint": "https://elsewhere.test/v1"}
            change = changed_since(moved, digest(frozen), frozen, old, None)
            self.assertTrue(change.version and change.reshaped)
            self.assertFalse(corrected(change))
            # A run without a quote has no counts to outdate.
            self.assertIsNone(changed_since(frozen, digest(frozen), frozen, None, None))

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

    def test_stand_ins_keep_the_real_engine_package(self):
        # A plain module standing in for util hid every engine module the
        # test did not name, so Batch continuation's tests failed on their
        # own and passed only after another test had imported util.languages.
        import util
        from util import languages

        stand_in = ModuleType("util.languages")
        with replaced_modules({"util.languages": stand_in}):
            from util import languages as replaced

            self.assertIs(replaced, stand_in)
            self.assertIs(sys.modules["util"], util)
        self.assertIs(util.languages, languages)
        self.assertIs(sys.modules["util.languages"], languages)
        with (
            self.assertRaisesRegex(ValueError, "util is a package"),
            replaced_modules({"util": ModuleType("util")}),
        ):
            pass
        self.assertIs(sys.modules["util"], util)

    def test_frozen_worker_defaults_preserve_payloads_and_legacy_recovery(self):
        # Regression: the native builder injects unsupported temperature into a
        # new guided Batch. Normalize before collection and Live serialization,
        # but never reinterpret the saved policy of a historical run.
        from copy import deepcopy

        from dazedtl.compatibility.worker_policy import install

        environment, translation = (
            ModuleType(name)
            for name in ("desktop.backend.manual_environment", "util.translation")
        )
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
        for name in (
            "estimateCostComparison",
            "estimateBatchCost",
            "translateAI",
            "translateText",
            "unestimatedThinking",
            "batch_usage_cost",
        ):
            setattr(translation, name, point(Mock()))
        translation.RunRefusedError = type("RunRefusedError", (RuntimeError,), {})

        def pricing(model):
            rates = translation._load_litellm_pricing()[model]
            return {
                "inputAPICost": rates["input_cost_per_token"] * 1_000_000,
                "outputAPICost": rates["output_cost_per_token"] * 1_000_000,
            }

        translation.getPricingConfig = pricing
        native_prepare = Mock(return_value="prepared")
        environment.prepare = point(native_prepare)
        modules = {module.__name__: module for module in (environment, translation)}
        from dazedtl.compatibility import openrouter_batch

        with (
            TemporaryDirectory() as temporary,
            replaced_modules(modules),
            # A worker's prepare configures OpenRouter Batch for its process;
            # later tests in this one must not inherit that run.
            patch.multiple(
                openrouter_batch,
                _worker_policy=None,
                _worker_root=None,
                _worker_configured=False,
            ),
        ):
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
            # A chosen thinking effort reaches Live and Batch requests only for
            # a model that takes it, names itself in estimates and stops the
            # run once when the provider refuses it.
            plan["settings"].update(api="https://api.openai.com/v1")
            plan["dazedtl_request_policy"] = {**policy, "thinkingEffort": "high"}
            write_json(root / "plan.json", plan)
            environment.prepare(root)
            live = translation.buildOpenAIRequest("gpt-6.1-sol")
            self.assertEqual(
                live, {**baseline, "model": "gpt-6.1-sol", "reasoning_effort": "high"}
            )
            self.assertEqual(json.loads(json.dumps({"body": live}))["body"], live)
            self.assertEqual(
                translation.buildOpenAIRequest("gpt-4.1"),
                {**baseline, "model": "gpt-4.1"},
            )
            self.assertTrue(translation.unestimatedThinking("openai", "gpt-6.1-sol"))
            translation.estimateCostComparison = point(
                Mock(return_value={"model": "gpt-6.1-sol"})
            )
            environment.prepare(root)
            self.assertEqual(
                translation.estimateCostComparison()["thinking_effort"], "High"
            )
            refused = Exception(
                "API status error (400): Unsupported value: 'reasoning_effort'"
            )
            translation.translateText = point(Mock(side_effect=refused))
            environment.prepare(root)
            with self.assertRaisesRegex(
                translation.RunRefusedError, "gpt-6.1-sol refused thinking effort High"
            ):
                translation.translateText("s", "u", [], 0, "json", "gpt-6.1-sol")
            # A 422 naming reasoning refuses the effort too, by the rule a new
            # run freezes (settings/effort REFUSALS), which Check an effort
            # reads by; a run frozen before it sends and fails as it did.
            unsupported = Exception(
                "API status error (422): Reasoning is not supported for this model"
            )
            translation.translateText = point(Mock(side_effect=unsupported))
            environment.prepare(root)
            with self.assertRaises(Exception) as caught:
                translation.translateText("s", "u", [], 0, "json", "gpt-6.1-sol")
            self.assertIs(caught.exception, unsupported)
            plan["dazedtl_request_policy"] = {
                **policy,
                "thinkingEffort": "high",
                "thinkingEffortRefusals": effort.REFUSALS,
            }
            write_json(root / "plan.json", plan)
            environment.prepare(root)
            with self.assertRaisesRegex(
                translation.RunRefusedError, "gpt-6.1-sol refused thinking effort High"
            ):
                translation.translateText("s", "u", [], 0, "json", "gpt-6.1-sol")
            translation.translateText = point(Mock(side_effect=refused))
            plan["dazedtl_request_policy"] = policy
            write_json(root / "plan.json", plan)
            environment.prepare(root)
            self.assertEqual(
                translation.estimateCostComparison()["thinking_effort"],
                "Provider default (Medium)",
            )
            with self.assertRaises(Exception) as caught:
                translation.translateText("s", "u", [], 0, "json", "gpt-6.1-sol")
            self.assertIs(caught.exception, refused)
            # A model DazedTL's notes don't know takes the levels its
            # provider's model list gave the run, which also names its default.
            listed = {
                "levels": ["low", "high"],
                "default": "low",
                "off": None,
                "adaptive": False,
            }
            plan["settings"].update(api="https://openrouter.ai/api/v1")
            for level, named in ((None, "Provider default (Low)"), ("high", "High")):
                plan["dazedtl_request_policy"] = {
                    **policy,
                    "thinkingEffortListed": listed,
                    **({} if level is None else {"thinkingEffort": level}),
                }
                write_json(root / "plan.json", plan)
                environment.prepare(root)
                translation.estimateCostComparison = point(
                    Mock(return_value={"model": "z-ai/glm-6"})
                )
                environment.prepare(root)
                self.assertEqual(
                    translation.estimateCostComparison()["thinking_effort"], named
                )
                self.assertEqual(
                    translation.buildOpenAIRequest("z-ai/glm-6")["extra_body"],
                    baseline["extra_body"]
                    if level is None
                    else {**baseline["extra_body"], "reasoning": {"effort": "high"}},
                )
            plan["settings"].update(api="https://api.openai.com/v1")
            plan["dazedtl_request_policy"] = policy
            write_json(root / "plan.json", plan)
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
                self.assertNotIn(
                    "thinking_effort", translation.estimateCostComparison()
                )
            plan["dazedtl_request_policy"] = {
                **policy,
                "generationParameters": "unsupported-future-policy",
            }
            write_json(root / "plan.json", plan)
            before = native_prepare.call_count
            with self.assertRaisesRegex(ValueError, "invalid or unsupported"):
                environment.prepare(root)
            self.assertEqual(native_prepare.call_count, before)

    def test_a_provider_error_every_request_gets_stops_a_frozen_run(self):
        # A Guided Live run whose every request got the same HTTP 400 sent
        # each call five times and went on through every file. Under the
        # run-stop policy the same deterministic error on 3 requests in a row,
        # across workers, stops the run and nothing more is sent; one such
        # error among successes fails only its call, without a retry; a run
        # frozen before keeps each error as it was.
        from dazedtl.compatibility import run_stops
        from dazedtl.settings.preferences import RUN_STOPS

        class Stopping(RuntimeError):
            pass

        class Rejected(Exception):
            pass

        class StatusError(Exception):
            """An SDK's error, as the engine's wrapped one holds it."""

            def __init__(self, status, message):
                super().__init__(f"Error code: {status}")
                self.status_code = status
                self.body = {"message": message, "code": "model_not_found"}

        def provider_error(status, message="The model `gone` does not exist."):
            sdk = StatusError(status, message)
            wrapped = Exception(f"API status error ({status}): {sdk}")
            wrapped.__context__ = sdk
            return wrapped

        replies, sent = [], []

        def provider(*_args, **_kwargs):
            reply = replies.pop(0)
            sent.append(reply)
            if isinstance(reply, BaseException):
                raise reply
            return reply

        def worker(policy, root, coordinator=False):
            translation = SimpleNamespace(
                translateText=point(provider),
                translateAI=point(provider),
                get_batch_phase=lambda: None,
                RunStoppingError=Stopping,
                RequestRejectedError=Rejected,
            )
            run_stops.configure(translation, policy, root, coordinator=coordinator)
            return translation

        def outcomes(*calls):
            results = []
            for translation in calls:
                try:
                    results.append(translation.translateText("s", "u"))
                except Exception as error:
                    results.append(type(error).__name__)
            return results

        frozen = {"runStops": RUN_STOPS}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = root / "log/run_stop.json"
            first, second = worker(frozen, root), worker(frozen, root)
            self.assertTrue(first.RUN_STOPS)
            # One rejection among successes fails its call alone, at once.
            rejected = provider_error(400)
            replies[:] = ["ok", rejected, "ok", "ok"]
            self.assertEqual(
                outcomes(first, second, first, second),
                ["ok", "Rejected", "ok", "ok"],
            )
            self.assertFalse(record.exists())
            # Its message is the provider's own, which the file's error and
            # the run's message show, not the SDK's and engine's wrapping.
            replies[:] = [provider_error(400), "ok"]
            with self.assertRaises(Rejected) as caught:
                first.translateText("s", "u")
            self.assertEqual(
                str(caught.exception),
                "The provider rejected the request: HTTP 400 - The model `gone` "
                "does not exist.",
            )
            self.assertEqual(first.translateText("s", "u"), "ok")
            # Prompts a safety system flagged share one error, but the next
            # need not be flagged: each fails its call alone.
            flagged = provider_error(
                400,
                "Invalid prompt: your prompt was flagged as potentially violating "
                "our usage policy.",
            )
            replies[:] = [flagged] * 3 + ["ok"]
            self.assertEqual(
                outcomes(first, second, first, second), ["Rejected"] * 3 + ["ok"]
            )
            self.assertFalse(record.exists())
            # Timeouts, rate limits and server errors pass as before and
            # neither count nor end a streak; a different error starts anew.
            unavailable = provider_error(503)
            replies[:] = [
                provider_error(400),
                unavailable,
                provider_error(404, "No such route."),
                provider_error(400),
                provider_error(400),
                unavailable,
                "ok",
            ]
            self.assertEqual(
                outcomes(first, second, first, second, first, second, first),
                ["Rejected", "Exception", "Rejected"]
                + ["Rejected"] * 2
                + ["Exception", "ok"],
            )
            self.assertFalse(record.exists())
            # The same error on 3 requests in a row stops the run in every
            # worker, which sends nothing more.
            replies[:] = [provider_error(400)] * 3 + ["ok"]
            del sent[:]
            self.assertEqual(
                outcomes(first, second, first, second, first),
                ["Rejected", "Rejected", "Stopping", "Stopping", "Stopping"],
            )
            self.assertEqual(len(sent), 3)
            with self.assertRaises(Stopping) as caught:
                second.translateText("s", "u")
            self.assertEqual(
                str(caught.exception),
                "The provider rejected 3 requests in a row with the same error, so "
                "the run stopped without sending the rest: HTTP 400 - The model "
                "`gone` does not exist. Check the model and the connection in "
                "Settings, then start the run again. Rejected requests are not "
                "billed.",
            )
            # The next attempt starts without the stop; a stop an inner layer
            # raises, such as a refused effort, ends the run at the first.
            worker(frozen, root, coordinator=True)
            self.assertFalse(record.exists())
            replies[:] = [Stopping("Refused effort."), "ok"]
            del sent[:]
            self.assertEqual(outcomes(first, second), ["Stopping", "Stopping"])
            self.assertEqual(len(sent), 1)
            # A run frozen before the policy sends every request and gets each
            # error unchanged, for the engine to retry as before.
            older = worker({"smallKana": "small-kana-v1"}, root)
            self.assertFalse(older.RUN_STOPS)
            replies[:] = [rejected] * 3 + ["ok"]
            for _ in range(3):
                with self.assertRaises(Exception) as caught:
                    older.translateText("s", "u")
                self.assertIs(caught.exception, rejected)
            self.assertEqual(older.translateText("s", "u"), "ok")

    def test_a_live_call_the_engine_gave_up_on_fails_with_the_providers_error(self):
        # A file failing with an error the run-stop rule does not count, such
        # as an HTTP 500 after the engine's tries, or any error in a run frozen
        # before the rule, failed with the engine's wrapped text: "API server
        # error (500) - retrying... Error: Error code: 500 - {...}". Requests
        # and retries stay as the run sends them.
        from dazedtl.compatibility import run_stops
        from dazedtl.settings.preferences import RUN_STOPS

        class Stopping(RuntimeError):
            pass

        class Rejected(Exception):
            pass

        class StatusError(Exception):
            def __init__(self, status):
                super().__init__(f"Error code: {status}")
                self.status_code = status
                self.body = {"error": {"message": "The server failed"}}

        class APIConnectionError(Exception):
            pass

        class APITimeoutError(APIConnectionError):
            pass

        class Wrapped(Exception):
            """The engine's own error, raised inside its handler."""

        def wrapped(sdk, text):
            try:
                raise sdk
            except Exception as error:
                try:
                    raise Wrapped(f"{text} - retrying... Error: {error}")
                except Wrapped as outer:
                    return outer

        calls, replies, phase = [], [], None

        def engine(*_args, **_kwargs):
            calls.append(1)
            raise replies.pop(0)

        with TemporaryDirectory() as temporary:
            for policy in ({"runStops": RUN_STOPS}, None):
                translation = SimpleNamespace(
                    translateText=point(lambda *_args: "ok"),
                    translateAI=point(engine),
                    get_batch_phase=lambda: phase,
                    RunStoppingError=Stopping,
                    RequestRejectedError=Rejected,
                )
                run_stops.configure(translation, policy, temporary)
                for sdk, text, message in (
                    (
                        StatusError(500),
                        "API server error (500)",
                        (
                            "The provider failed the request: HTTP 500 - The "
                            "server failed."
                        ),
                    ),
                    (
                        StatusError(400),
                        "API status error (400)",
                        (
                            "The provider rejected the request: HTTP 400 - The "
                            "server failed."
                        ),
                    ),
                    (
                        APITimeoutError("Request timed out."),
                        "API connection/rate limit error",
                        "The provider could not be reached: Request timed out.",
                    ),
                ):
                    replies[:] = [wrapped(sdk, text)]
                    with self.assertRaises(Exception) as caught:
                        translation.translateAI("s", "u")
                    self.assertEqual(str(caught.exception), message, policy)
                # A stop, a rejection and an error from no provider pass as
                # they are.
                for error in (Stopping("Stop."), Rejected("No."), ValueError("x")):
                    replies[:] = [error]
                    with self.assertRaises(Exception) as caught:
                        translation.translateAI("s", "u")
                    self.assertIs(caught.exception, error)
                # A Batch phase sends nothing Live.
                phase = "consume"
                replies[:] = [wrapped(StatusError(500), "API server error (500)")]
                with self.assertRaises(Exception) as caught:
                    translation.translateAI("s", "u")
                self.assertIsInstance(caught.exception, Wrapped)
                phase = None
        self.assertEqual(len(calls), 14)

    def test_a_provider_error_without_a_message_reads_as_its_code(self):
        # A 400 whose body held no message read "HTTP 400 - Provider returned
        # HTTP 400.", and a prompt flagged only by its code lost the code.
        from dazedtl.compatibility.provider_responses import (
            error_evidence,
            provider_error,
        )

        class StatusError(Exception):
            def __init__(self, body):
                super().__init__("Error code: 400")
                self.status_code = 400
                self.body = body

        def reads(body):
            return provider_error(error_evidence(StatusError(body)))

        self.assertEqual(
            reads({"error": {"message": "The model `gone` does not exist"}}),
            "HTTP 400 - The model `gone` does not exist.",
        )
        self.assertEqual(
            reads({"error": {"code": "content_filter"}}), "HTTP 400 - content_filter."
        )
        self.assertEqual(reads({}), "HTTP 400 with no reason given.")
        self.assertEqual(reads(None), "HTTP 400 with no reason given.")
        # A Batch request's error as a fetch keeps it: the row's error object,
        # or a row of OpenAI's error file whole; anything else stays as it is.
        from dazedtl.compatibility.provider_responses import stored_reason

        for stored, reason in (
            ("{'code': 'invalid_request', 'message': 'Bad model'}", "Bad model."),
            (
                (
                    "{'id': 'batch_req_1', 'custom_id': 'req-1', 'response': "
                    "{'status_code': 400, 'request_id': 'r', 'body': {'error': "
                    "{'message': 'Bad model', 'type': 'invalid_request_error'}}}, "
                    "'error': None}"
                ),
                "HTTP 400 - Bad model.",
            ),
            ("{'code': 'invalid_request', 'mess", "{'code': 'invalid_request', 'mess"),
            ("expired: ", "expired: "),
        ):
            self.assertEqual(stored_reason(stored), reason)

    def test_claude_estimates_scale_from_claudes_own_count_of_a_spread_sample(self):
        # Claude's estimates once counted only the shared instructions with
        # Claude's tokenizer and the rest approximately, understating input.
        claude_tokens = engine_module("util/claude_tokens.py")
        calls = []

        def count_tokens(**fields):
            calls.append(fields)
            if fields["messages"][0]["content"] == "fail":
                raise RuntimeError("rate limited")
            system = "".join(block["text"] for block in fields["system"])
            message = "".join(item["content"] for item in fields["messages"])
            schema = json.dumps(fields.get("output_config", {}))
            return SimpleNamespace(
                input_tokens=2 * len(system) + 3 * len(message) + len(schema)
            )

        client = SimpleNamespace(messages=SimpleNamespace(count_tokens=count_tokens))
        requests = [
            {
                "model": "claude-fixture",
                "max_tokens": 4096,
                "system": [
                    {"type": "text", "text": "S" * 500, "cache_control": {}},
                    {"type": "text", "text": "G" * (index % 7 * 15)},
                ],
                "messages": [
                    {"role": "user", "content": "J" * (40 + index * 37 % 360)}
                ],
                # Anthropic caches the reply schema with the instructions.
                "output_config": {"format": {"lines": 1 + index % 2}},
            }
            for index in range(100)
        ]
        exact = sum(count_tokens(**params).input_tokens for params in requests)
        calls.clear()
        estimate = claude_tokens.input_tokens(client, requests, len)
        self.assertAlmostEqual(estimate.total / exact, 1, delta=0.01)
        # Each schema's prefix once, then whole requests from first to last.
        self.assertEqual(len(calls), 2 + claude_tokens.SAMPLES)
        self.assertFalse(any("max_tokens" in params for params in calls))
        counted = [params["messages"] for params in calls]
        self.assertIn(requests[0]["messages"], counted)
        self.assertIn(requests[-1]["messages"], counted)
        # A Batch's requests may each write their prefix instead of reading
        # it, and a run once cost twice the estimate that assumed reads.
        prefix = 1000 + len(json.dumps({"format": {"lines": 1}})) + 3
        self.assertEqual(sorted(estimate.prefixes.values())[1:], [prefix, prefix])
        cache = claude_tokens.cache(
            requests, "anthropic", "claude-opus-5-5", len, estimate
        )
        self.assertEqual((cache.cached, cache.writes), (100 * prefix, 2 * prefix))
        self.assertAlmostEqual(cache.reused, prefix * (2 * 1.25 + 98 * 0.05))
        self.assertAlmostEqual(cache.unreused, prefix * 100 * 1.25)
        # Assistant-led approves the most such a Batch costs.
        from dazedtl.translation.requests import quote

        cfg = {
            "mode": "batch",
            "model": "claude-opus-5-5",
            "provider": "anthropic",
            # Older runs froze a Batch discount; the provider's own decides.
            "rates": {"input": 4, "output": 20, "batch_factor": 0.25},
        }
        items = [{"params": params, "sources": {"1": "J"}} for params in requests]
        quoted = quote(items, cfg, "anthropic", len, estimate.total, cache)
        current = {**cfg, "rates": {"input": 4, "output": 20}}
        self.assertEqual(
            quote(items, current, "anthropic", len, estimate.total, cache)["cost"],
            quoted["cost"],
        )
        uncached, outputs = estimate.total - cache.cached, quoted["output_tokens"]
        self.assertAlmostEqual(
            quoted["cost"],
            ((uncached + cache.unreused) * 4 + outputs * 20) / 2_000_000,
        )
        self.assertAlmostEqual(
            quoted["batch_cost_reused"],
            ((uncached + cache.reused) * 4 + outputs * 20) / 2_000_000,
        )
        self.assertTrue(quoted["unestimated_thinking_tokens"])
        # Its spend is priced as Guided's receipts are: its requests write
        # five-minute caches, which Live usage doesn't say.
        from dazedtl.compatibility.estimate_prices import usage_cost

        usage = {
            "input_tokens": 1000,
            "output_tokens": 100,
            "cache_creation_input_tokens": 1000,
            "cache_read_input_tokens": 1000,
        }
        live = (1000 * 4 + 1000 * 4 * 1.25 + 1000 * 4 * 0.05 + 100 * 20) / 1e6
        self.assertAlmostEqual(
            usage_cost(usage, {**cfg, "mode": "live"}, "anthropic") or 0, live
        )
        self.assertAlmostEqual(usage_cost(usage, cfg, "anthropic") or 0, live / 2)
        self.assertEqual(
            usage_cost(usage, current, "anthropic"),
            usage_cost(usage, cfg, "anthropic"),
        )
        requests[-1]["messages"][0]["content"] = "fail"
        self.assertIsNone(claude_tokens.input_tokens(client, requests, len))

    def test_deepseek_usage_is_priced_at_the_price_of_the_hour_it_arrived(self):
        # DeepSeek bills half outside its weekday peak hours, but both
        # methods' recorded spend priced every request at peak.
        import os
        import threading
        from datetime import UTC, datetime

        from dazedtl.compatibility.translation import TranslationProvider
        from util import translation
        from util.provider_costs import (
            joined_received_at,
            received_at,
            time_price_factor,
            time_priced_route,
        )

        def at(day, hour, minute=0):
            return datetime(2026, 10, day, hour, minute, tzinfo=UTC)

        # Monday 26 October 2026 to Saturday the 31st; peak is 01:00-04:00
        # and 06:00-10:00 UTC on weekdays.
        for when, factor in (
            (at(26, 0, 59), 0.5),
            (at(26, 1), 1.0),
            (at(26, 3, 59), 1.0),
            (at(26, 4), 0.5),
            (at(27, 6), 1.0),
            (at(30, 9, 59), 1.0),
            (at(30, 10), 0.5),
            (at(31, 7), 0.5),
        ):
            self.assertEqual(
                time_price_factor("deepseek", when.isoformat()), factor, when
            )
        # 09:30 in Tokyo is 00:30 UTC; a time without a zone, or none, as
        # rows saved before times were, reads as peak.
        for when, factor in (
            ("2026-10-26T09:30:00+09:00", 0.5),
            ("2026-10-31T07:00:00", 1.0),
            ("not a time", 1.0),
            (None, 1.0),
        ):
            self.assertEqual(time_price_factor("deepseek", when), factor, when)
        # Only DeepSeek's own API bills by the hour, not a host serving its
        # models at its own prices.
        self.assertEqual(time_priced_route("https://api.deepseek.com"), "deepseek")
        self.assertIsNone(time_priced_route("https://openrouter.ai/api/v1"))
        self.assertEqual(time_price_factor(None, at(31, 7).isoformat()), 1.0)
        ten = at(26, 10).timestamp()
        self.assertEqual(received_at(ten), at(26, 10).isoformat())
        # A refused request and its clarification are priced together.
        self.assertEqual(
            joined_received_at("deepseek", received_at(ten), received_at(ten + 60)),
            received_at(ten + 60),
        )
        self.assertIsNone(
            joined_received_at("deepseek", received_at(ten - 1), received_at(ten))
        )
        # Assistant-led keeps the time the provider says it answered.
        body = {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        answer = SimpleNamespace(created=int(ten), model_dump=lambda: body)
        provider = TranslationProvider.__new__(TranslationProvider)
        provider.provider = "openai"
        provider.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: answer)
            )
        )
        sent = provider.live({"model": "deepseek-flash", "messages": []})
        self.assertEqual(sent["created"], int(ten))
        # Guided's receipts add up its Live responses one by one, the file's
        # and the run's TOTAL alike.
        usage = SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=1_000_000)
        with (
            patch.dict(os.environ, {"api": "https://api.deepseek.com"}),
            patch.object(
                translation,
                "getPricingConfig",
                return_value={"inputAPICost": 0.30, "outputAPICost": 1.20},
            ),
            patch.object(translation, "_thread_local", threading.local()),
            patch.object(translation, "_global_accurate_cost", 0.0),
        ):
            for created in (ten - 1, ten):
                translation._log_live_response(
                    "openai", {}, SimpleNamespace(created=created, usage=usage)
                )
                translation._record_live_cost(usage, "deepseek-flash")
            for _call in ("file", "TOTAL"):
                self.assertAlmostEqual(
                    translation.calculateCost(2_000_000, 2_000_000, "deepseek-flash"),
                    1.50 + 0.75,
                )

    def test_assistant_led_live_sends_extra_body_fields_in_the_request(self):
        # Assistant-led Live handed extra_body's fields to the real OpenAI SDK
        # as keyword arguments, which it refuses with a TypeError before
        # sending: DeepSeek or Kimi with thinking off, and every OpenRouter
        # request with its routing field, failed.
        import httpx2
        import openai
        from dazedtl.compatibility import request_parameters
        from util.batch_providers import execute_live_request

        sent = []

        def reply(request):
            sent.append(json.loads(request.content))
            return httpx2.Response(
                200,
                json={
                    "id": "fixture",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "fixture",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "{}"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )

        client = openai.OpenAI(
            api_key="fixture-key",
            base_url="https://stand-in.test/v1",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(reply)),
        )
        self.addCleanup(client.close)
        messages = [{"role": "user", "content": "薬"}]
        google = {"google": {"thinking_config": {"thinking_budget": 512}}}
        for provider, params, expected in (
            *(
                (
                    "openai",
                    request_parameters.thinking(
                        {"model": model, "messages": messages},
                        {"model": model, "thinkingEffort": "none"},
                        identity,
                    ),
                    {"thinking": {"type": "disabled"}},
                )
                for identity, model in (
                    ("deepseek", "deepseek-v4-flash"),
                    ("kimi", "kimi-k2.6"),
                )
            ),
            (
                "openai",
                request_parameters.structured_output(
                    {"model": "openai/gpt-6.1-sol", "messages": messages},
                    {"type": "object"},
                ),
                {"provider": {"require_parameters": True}},
            ),
            # Gemini takes its extensions under its own extra_body field,
            # never as a top-level google field.
            (
                "gemini",
                {
                    "model": "gemini-3-flash",
                    "messages": messages,
                    "extra_body": {"extra_body": google},
                },
                {"extra_body": google},
            ),
        ):
            with self.subTest(params["model"]):
                execute_live_request(provider, params, client=client)
                body = sent.pop()
                self.assertEqual({key: body[key] for key in expected}, expected)
                self.assertNotIn("google", body)

    def test_guided_live_spend_prices_cache_hits_as_assistant_led_spent_does(self):
        # Guided's recorded Live cost priced every prompt token at the full
        # input rate, so a run whose prompts mostly hit the provider's cache
        # read several times what DeepSeek, OpenAI or Kimi billed and what
        # Assistant-led's Spent says for the same work.
        import os
        import threading
        from datetime import UTC, datetime

        from dazedtl.compatibility.estimate_prices import usage_cost
        from openai.types import CompletionUsage
        from util import translation
        from util.batch_providers import execute_live_request
        from util.translation_task import _names_cost

        def hits(**extra):
            return CompletionUsage(
                prompt_tokens=1_000_000,
                completion_tokens=100_000,
                total_tokens=1_100_000,
                **extra,
            )

        # Monday 26 October 2026 at 12:00 UTC is off-peak on DeepSeek.
        noon = datetime(2026, 10, 26, 12, tzinfo=UTC).timestamp()
        # Each route's prompt of 1M tokens, 900k of them cache hits as it
        # reports them, and 100k output, at $0.30 and $1.20 per 1M.
        for provider, endpoint, model, usage, cost in (
            (
                "deepseek",
                "https://api.deepseek.com",
                "deepseek-v4-flash",
                hits(
                    prompt_cache_hit_tokens=900_000,
                    prompt_cache_miss_tokens=100_000,
                ),
                # Off-peak halves the cache-read price too.
                (0.03 + 0.9 * 0.006 + 0.12) / 2,
            ),
            (
                "openai",
                "https://api.openai.com/v1",
                "gpt-5.4-mini",
                hits(prompt_tokens_details={"cached_tokens": 900_000}),
                0.03 + 0.9 * 0.03 + 0.12,
            ),
            (
                # OpenAI reads GPT-4.1's cache at a quarter of its input
                # price, not the tenth GPT-5 models read at.
                "openai",
                "https://api.openai.com/v1",
                "gpt-4.1",
                hits(prompt_tokens_details={"cached_tokens": 900_000}),
                0.03 + 0.9 * 0.30 * 0.25 + 0.12,
            ),
            (
                # OpenRouter passes on OpenAI's own cache prices, so GPT-4.1
                # there reads at a quarter too, not at the default tenth.
                "openai",
                "https://openrouter.ai/api/v1",
                "openai/gpt-4.1",
                hits(prompt_tokens_details={"cached_tokens": 900_000}),
                0.03 + 0.9 * 0.30 * 0.25 + 0.12,
            ),
            (
                "kimi",
                "https://api.moonshot.ai/v1",
                "kimi-k2.6",
                hits(cached_tokens=900_000),
                0.03 + 0.9 * 0.30 * 0.16 / 0.95 + 0.12,
            ),
        ):
            with (
                self.subTest(model),
                patch.dict(os.environ, {"api": endpoint, "API_PROVIDER": "openai"}),
                patch.object(
                    translation,
                    "getPricingConfig",
                    return_value={"inputAPICost": 0.30, "outputAPICost": 1.20},
                ),
                patch.object(translation, "_thread_local", threading.local()),
                patch.object(translation, "_global_accurate_cost", 0.0),
            ):
                translation._log_live_response(
                    "openai", {}, SimpleNamespace(created=noon, usage=usage)
                )
                translation._record_live_cost(usage, model)
                for _call in ("file", "TOTAL"):
                    self.assertAlmostEqual(
                        translation.calculateCost(1_000_000, 100_000, model), cost
                    )
                # A file nothing was sent for cost nothing, though the run's
                # total has grown.
                self.assertEqual(translation.calculateCost(0, 0, model), 0)
                # A names step's receipt is what its own responses cost, not
                # the run's total, though its per-request lines have closed
                # the cost window.
                before = translation.priced_cost()
                translation._record_live_cost(usage, model)
                translation.calculateCost(1_000_000, 100_000, model)
                names = SimpleNamespace(
                    calculateCost=translation.calculateCost, MODEL=model
                )
                self.assertAlmostEqual(
                    _names_cost(names, 1_000_000, 100_000, before), cost
                )
                # Assistant-led's Spent for the same response.
                body = {
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": usage.model_dump(),
                }
                client = SimpleNamespace(
                    chat=SimpleNamespace(
                        completions=SimpleNamespace(
                            create=lambda body=body, **_kwargs: body
                        )
                    )
                )
                answer = execute_live_request(
                    "openai" if provider == "deepseek" else provider,
                    {"model": model, "messages": []},
                    client=client,
                )
                counts = {
                    "input_tokens": answer["prompt_tokens"]
                    - answer["cache_read_input_tokens"],
                    "output_tokens": answer["completion_tokens"],
                    "cache_read_input_tokens": answer["cache_read_input_tokens"],
                }
                spent = usage_cost(
                    counts,
                    {
                        "mode": "live",
                        "model": model,
                        "endpoint": endpoint,
                        "rates": {"input": 0.30, "output": 1.20},
                    },
                    provider,
                    [{**counts, "received_at": translation._thread_local.received_at}],
                )
                assert spent is not None
                self.assertAlmostEqual(spent, cost)

    def test_assistant_led_live_spent_takes_guided_live_price_route(self):
        # Assistant-led priced a Live run on its Batch provider or its
        # connection's provider, so Claude on OpenRouter or a Custom host
        # read its cache at 0.1x and wrote it at 1x, while Guided prices
        # Claude's Live cache at Anthropic's prices on any host.
        from dazedtl.compatibility.estimate_prices import usage_cost

        usage = {
            "input_tokens": 100_000,
            "output_tokens": 10_000,
            "cache_read_input_tokens": 900_000,
            "cache_creation_input_tokens": 50_000,
        }

        def spent(model, provider, endpoint, protocol="openai", batch=None, **extra):
            configuration = {
                "mode": "live",
                "model": model,
                "provider": provider,
                "endpoint": endpoint,
                "protocol": protocol,
                "rates": {"input": 3.0, "output": 15.0},
                **extra,
            }
            return usage_cost(usage, configuration, batch)

        uncached = 0.30 + 0.15
        claude = uncached + 0.9 * 3 * 0.05 + 0.05 * 3 * 1.25
        router = "https://openrouter.ai/api/v1"
        for batch in (None, "openrouter"):
            with self.subTest(batch=batch):
                self.assertAlmostEqual(
                    spent(
                        "anthropic/claude-sonnet-5-5", "openrouter", router, batch=batch
                    )
                    or 0,
                    claude,
                )
        self.assertAlmostEqual(
            spent("claude-sonnet-5-5", "custom", "https://proxy.example/v1") or 0,
            claude,
        )
        # OpenAI models read and write their cache at OpenAI's prices on any
        # host too: they read at 0.1x and wrote at 1x off OpenAI's API.
        writes = 0.05 * 3
        for model, provider, endpoint, cost in (
            ("openai/gpt-4o", "openrouter", router, uncached + 0.9 * 3 * 0.5 + writes),
            (
                "gpt-4.1",
                "custom",
                "http://localhost:8080/v1",
                uncached + 0.9 * 3 * 0.25 + writes,
            ),
            (
                # An OpenRouter variant reads as its model.
                "openai/o4-mini:nitro",
                "openrouter",
                router,
                uncached + 0.9 * 3 * 0.25 + writes,
            ),
            (
                "openai/gpt-6.1-sol",
                "openrouter",
                router,
                uncached + 0.9 * 3 * 0.05 + writes * 1.25,
            ),
            (
                "openai/gpt-5.6-terra",
                "openrouter",
                router,
                uncached + 0.9 * 3 * 0.10 + writes * 1.25,
            ),
        ):
            with self.subTest(model):
                self.assertAlmostEqual(spent(model, provider, endpoint) or 0, cost)
        # Every other route keeps its price to the cent.
        reads = uncached + 0.05 * 3
        for model, provider, endpoint, protocol, batch, cost in (
            (
                "openai/gpt-5.4-mini",
                "openrouter",
                router,
                "openai",
                None,
                reads + 0.9 * 3 * 0.10,
            ),
            (
                # Open-weight, not OpenAI's to price.
                "openai/gpt-oss-120b",
                "openrouter",
                router,
                "openai",
                None,
                reads + 0.9 * 3 * 0.10,
            ),
            (
                "claude-sonnet-5-5",
                "anthropic",
                "https://api.anthropic.com/v1",
                "anthropic",
                "anthropic",
                claude,
            ),
            (
                "gpt-5.4",
                "openai",
                "https://api.openai.com/v1",
                "openai",
                "openai",
                reads + 0.9 * 3 * 0.10,
            ),
            (
                "gpt-5.6-terra",
                "openai",
                "https://api.openai.com/v1",
                "openai",
                "openai",
                uncached + 0.9 * 3 * 0.10 + 0.05 * 3 * 1.25,
            ),
            (
                "kimi-k2.6",
                "kimi",
                "https://api.moonshot.ai/v1",
                "openai",
                "kimi",
                reads + 0.9 * 3 * 0.16 / 0.95,
            ),
            (
                "kimi-k3",
                "kimi",
                "https://api.moonshot.ai/v1",
                "openai",
                None,
                reads + 0.9 * 3 * 0.10,
            ),
            (
                "gemini-3.6-flash",
                "gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
                "gemini",
                "gemini",
                reads + 0.9 * 3 * 0.10,
            ),
            (
                "mistral-medium-3-5",
                "custom",
                "https://api.mistral.ai/v1/",
                "openai",
                None,
                reads + 0.9 * 3 * 0.10,
            ),
        ):
            with self.subTest(model):
                self.assertAlmostEqual(
                    spent(model, provider, endpoint, protocol, batch) or 0, cost
                )

    def test_each_claude_route_rule_routes_a_model_and_address_alike(self):
        # The Claude name test and the native-Anthropic route test were copied
        # into the Live send, the estimate, Batch detection, Live pricing,
        # per-token rates, default thinking and Settings' route check; each
        # copy must keep answering the same.
        import os

        from dazedtl.compatibility import openrouter_batch
        from dazedtl.compatibility.dazedmtl import ExistingBackend
        from dazedtl.settings import effort
        from dazedtl.settings.providers import own_api
        from util import translation
        from util.batch_providers import detect_batch_provider, live_price_route
        from util.provider_costs import (
            cache_read_multiplier,
            foreign_claude_name,
            on_anthropic_api,
        )

        addresses = (
            "",
            "https://api.anthropic.com",
            # A proxy path: sent Live natively, but Batches need Anthropic's
            # own API.
            "http://localhost:8080/anthropic",
            # Another host whose name holds Anthropic's.
            "https://anthropic.company.example/v1",
            "https://openrouter.ai/api/v1",
            "https://proxy.example/v1",
            "https://api.openai.com/v1",
            # The same own APIs without a scheme.
            "api.anthropic.com",
            "api.openai.com/v1",
        )
        # Per address: native Live send, Batch provider, Live price route,
        # Settings' engine route.
        claude = (
            (True, "anthropic", "anthropic", "anthropic"),
            (True, "anthropic", "anthropic", "anthropic"),
            (True, None, "anthropic", "anthropic"),
            (True, None, "anthropic", "anthropic"),
            (False, None, "anthropic", "openai"),
            (False, None, "anthropic", "openai"),
            (False, "openai", "anthropic", "openai"),
            (True, "anthropic", "anthropic", "anthropic"),
            (False, "openai", "anthropic", "openai"),
        )
        other = (
            (False, "openai", "openai", "openai"),
            (False, None, "", "openai"),
            (False, None, "", "openai"),
            (False, None, "", "openai"),
            (False, None, "", "openai"),
            (False, None, "", "openai"),
            (False, "openai", "openai", "openai"),
            (False, None, "", "openai"),
            (False, "openai", "openai", "openai"),
        )
        gpt = tuple((False, batch, "openai", "openai") for _n, batch, *_r in other)
        for model, routes in (
            ("claude-sonnet-5-5", claude),
            ("anthropic/claude-haiku-4-5", claude),
            ("Claude-Opus-5", claude),
            # Dated, versioned and other hosts' forms of Claude's names.
            ("claude-3-5-sonnet-20241022", claude),
            ("claude-3-5-sonnet-v2@20241022", claude),
            ("anthropic/claude-sonnet-4.5:beta", claude),
            ("~anthropic/claude-opus-latest", claude),
            ("us.anthropic.claude-sonnet-4-5-20250929-v1:0", claude),
            ("us-gov.anthropic.claude-3-5-sonnet-20240620-v1:0", claude),
            ("bedrock/anthropic.claude-3-haiku", claude),
            (
                (
                    "arn:aws:bedrock:us-east-1:123456789012:inference-profile/"
                    "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
                ),
                claude,
            ),
            ("vertex_ai/claude-sonnet-5-5", claude),
            ("publishers/anthropic/models/claude-opus-4-1", claude),
            ("databricks-claude-sonnet-4", claude),
            ("databricks/databricks-claude-3-7-sonnet", claude),
            # Other models whose names hold a Claude family word are not
            # Claude's.
            ("magnum-opus-72b", other),
            ("Helsinki-NLP/opus-mt-ja-en", other),
            ("sonnet-like", other),
            ("haiku-writer-8b", other),
            ("someone/claude-style-7b", other),
            ("someone/claude-opus-5-distill", other),
            ("someone/databricks-claude-style-7b", other),
            ("gpt-5.4", gpt),
            ("deepseek-v4-flash", other),
            ("", other),
        ):
            for address, expected in zip(addresses, routes, strict=True):
                with (
                    self.subTest(model=model, address=address),
                    patch.dict(os.environ, {"api": address}),
                    # A run's worker without an OpenRouter Batch policy, which
                    # an earlier test's worker left this process as or not;
                    # an unconfigured one reads OpenRouter as its Batch.
                    patch.multiple(
                        openrouter_batch,
                        _worker_policy=None,
                        _worker_configured=True,
                    ),
                ):
                    os.environ.pop("DAZEDTL_TEST_OPENAI_ENDPOINT", None)
                    self.assertEqual(
                        (
                            translation.isClaudeNative(model, address),
                            detect_batch_provider(model, address, "openai"),
                            live_price_route(model, address, "openai"),
                            ExistingBackend.engine_route(model, "openai", address)[0],
                        ),
                        expected,
                    )
                    # The Live send and the estimate read the address from
                    # the engine's settings.
                    self.assertEqual(translation.isClaudeNative(model), expected[0])
                    self.assertEqual(translation.isClaudeModel(model), routes is claude)
                    # Anthropic's own API, where its Batches go, takes only
                    # Claude's own IDs, so Settings refuses another host's.
                    self.assertEqual(
                        foreign_claude_name(model, address),
                        expected[1] == "anthropic" and not model.startswith("claude-"),
                    )
            # Pricing gives Claude's rates to a Claude name only: another
            # model, with no catalog price, takes the unknown model's
            # fallback, which a price lookup reads as unpriced.
            with (
                self.subTest(model=model, rule="price"),
                patch.object(translation, "_lookup_model_price", return_value=None),
                patch.dict(os.environ, {"input_cost": "-1", "output_cost": "-1"}),
            ):
                self.assertEqual(
                    translation.getPricingConfig(model)["inputAPICost"] == -1,
                    routes is other and not model.startswith("deepseek-"),
                )
            # An estimate reads a Claude 5 name with no effort table row as
            # thinking only when the name is Claude's.
            with self.subTest(model=model, rule="thinks"):
                self.assertEqual(
                    effort.thinks(None, model),
                    model
                    in {
                        "claude-sonnet-5-5",
                        "Claude-Opus-5",
                        "vertex_ai/claude-sonnet-5-5",
                        "deepseek-v4-flash",
                    },
                )
        # A test scenario's stand-in for Anthropic's API counts as its API.
        stand_in = "http://127.0.0.1:9/api.anthropic.com"
        with patch.dict(os.environ, {"DAZEDTL_TEST_ANTHROPIC_ENDPOINT": stand_in}):
            self.assertTrue(on_anthropic_api(stand_in + "/v1"))
            self.assertFalse(on_anthropic_api("http://127.0.0.1:9/other"))
        # Kimi's and DeepSeek's own APIs count without a scheme too.
        for identity, address in (
            ("kimi", "api.moonshot.ai/v1"),
            ("deepseek", "API.DeepSeek.com"),
        ):
            with self.subTest(identity=identity, address=address):
                self.assertTrue(own_api(identity, address))
                self.assertFalse(own_api(identity, "proxy.example/" + address))
        # Claude's cache reads take each model's rate in any host's form of
        # its name.
        for model, read in (
            ("claude-opus-5-5", 0.05),
            ("anthropic/claude-opus-5.5", 0.05),
            ("anthropic/claude-sonnet-5.5:beta", 0.05),
            ("claude-fable-5.1", 0.025),
            ("us.anthropic.claude-mythos-5-1-v1:0", 0.025),
            ("anthropic/claude-opus-4.5", 0.1),
            ("someone/claude-opus-5.5-distill", 0.1),
        ):
            with self.subTest(model=model, rule="cache reads"):
                self.assertEqual(cache_read_multiplier("anthropic", model), read)
        # With no catalog price, a Claude name takes its version's rates in
        # any host's form: OpenRouter writes versions with dots, Anthropic
        # dates its Claude 3 IDs.
        for model, rates in (
            ("anthropic/claude-opus-5.5", (4, 20)),
            ("claude-opus-5-5", (4, 20)),
            ("anthropic/claude-opus-4.5", (5, 25)),
            ("anthropic/claude-opus-4.1", (15, 75)),
            ("claude-3-opus-20240229", (15, 75)),
            ("anthropic/claude-3.5-haiku", (0.80, 4)),
            ("claude-3-5-haiku-20241022", (0.80, 4)),
            ("anthropic/claude-haiku-4.5", (1, 5)),
            ("vertex_ai/claude-sonnet-5-5", (2, 10)),
        ):
            with (
                self.subTest(model=model, rule="rates"),
                patch.object(translation, "_lookup_model_price", return_value=None),
            ):
                pricing = translation.getPricingConfig(model)
                self.assertEqual(
                    (pricing["inputAPICost"], pricing["outputAPICost"]), rates
                )

    def test_mistral_follows_the_json_mode_strict_and_retry_rules(self):
        # The JSON-mode downgrade spent a retry attempt, so a format rejection
        # on the last attempt, here after a rate limit, raised "failed after
        # N attempts" unsent.
        import httpx
        import openai
        from util import translation

        sent = []
        body = {"message": "response_format json_schema is not supported"}

        def create(**params):
            sent.append(params["response_format"]["type"])
            if len(sent) == 1:
                raise openai.RateLimitError(
                    "slow down",
                    response=httpx.Response(
                        429,
                        headers={"retry-after": "0"},
                        request=httpx.Request("POST", "https://api.mistral.ai"),
                    ),
                    body=None,
                )
            if params["response_format"]["type"] == "json_schema":
                raise openai.UnprocessableEntityError(
                    "rejected",
                    response=httpx.Response(
                        422, request=httpx.Request("POST", "https://api.mistral.ai")
                    ),
                    body=body,
                )
            return SimpleNamespace(
                parse=lambda: "reply", headers={"x-ratelimit-remaining-tokens": "9"}
            )

        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    with_raw_response=SimpleNamespace(create=create)
                )
            ),
            RateLimitError=openai.RateLimitError,
            APIStatusError=openai.APIStatusError,
            APIConnectionError=openai.APIConnectionError,
        )
        limiter = SimpleNamespace(acquire=lambda _tokens: None, update=lambda _h: None)
        for run_stops in (False, True):
            sent.clear()
            with (
                self.subTest(run_stops=run_stops),
                patch.object(translation, "openai", client),
                patch.object(translation, "_get_mistral_limiter", return_value=limiter),
                patch.object(translation, "RUN_STOPS", run_stops),
            ):
                params = {
                    "messages": [{"role": "user", "content": "薬"}],
                    "response_format": {"type": "json_schema"},
                }
                self.assertEqual(translation.callMistral(params, retries=1), "reply")
                self.assertEqual(sent, ["json_schema", "json_schema", "json_object"])

        # A strict structured run keeps the provider's error, as
        # translateText's OpenAI path does, instead of sending JSON mode.
        sent.clear()
        with (
            patch.object(translation, "openai", client),
            patch.object(translation, "_get_mistral_limiter", return_value=limiter),
            patch.object(translation, "RUN_STOPS", True),
            patch.object(translation, "STRICT_STRUCTURED_OUTPUTS", True),
            self.assertRaises(openai.UnprocessableEntityError),
        ):
            translation.callMistral(
                {"messages": [], "response_format": {"type": "json_schema"}},
                retries=1,
            )
        self.assertEqual(sent, ["json_schema", "json_schema"])

        # A rate limit on the last attempt raises at once instead of first
        # waiting out its Retry-After, with the provider's error under the
        # engine's, so the run reports the provider's status (run_stops).
        sent.clear()
        with (
            patch.object(translation, "openai", client),
            patch.object(translation, "_get_mistral_limiter", return_value=limiter),
            patch.object(translation.time, "sleep") as sleep,
            self.assertRaisesRegex(Exception, "failed after 1 attempts") as raised,
        ):
            translation.callMistral(
                {"messages": [], "response_format": {"type": "json_schema"}},
                retries=0,
            )
        sleep.assert_not_called()
        self.assertIsInstance(raised.exception.__cause__, openai.RateLimitError)
        # A strict run's last rate limit is the provider's own error too.
        sent.clear()
        with (
            patch.object(translation, "openai", client),
            patch.object(translation, "_get_mistral_limiter", return_value=limiter),
            patch.object(translation, "STRICT_STRUCTURED_OUTPUTS", True),
            self.assertRaises(openai.RateLimitError),
        ):
            translation.callMistral(
                {"messages": [], "response_format": {"type": "json_schema"}},
                retries=0,
            )

    def test_an_openai_batch_estimate_prices_cache_reads_at_the_models_price(self):
        # Every OpenAI Batch estimate priced cache reads at a tenth of input,
        # though GPT-6.1 Sol reads at a twentieth. The models OpenAI's Batch
        # doesn't cache, GPT-4.1 and the rest before GPT-5 and the -pro
        # models, once expected reads too, so the low end of their Batch
        # estimates and quotes read below anything they cost.
        from dazedtl.translation.requests import price
        from util.provider_costs import cache_read_multiplier
        from util.translation import openai_cache_prices

        # Live keeps each model's own read price.
        for model, read in (("gpt-4o", 0.5), ("o3-mini", 0.5), ("o4-mini", 0.25)):
            self.assertEqual(cache_read_multiplier("openai", model), read)

        # 1M input, 900k of it expected cache hits, and 100k output, at $2
        # and $8 per 1M; these models bill no cache writes.
        for model, read in (
            ("gpt-5.4", 0.1),
            ("gpt-5.5", 0.1),
            ("gpt-4o", None),
            ("gpt-4.1", None),
            ("o4-mini", None),
            ("o1-pro", None),
            ("gpt-4o-2024-05-13", None),
            ("gpt-5.5-pro", None),
            ("openai/gpt-4.1-mini", None),
        ):
            with self.subTest(model):
                value = openai_cache_prices(
                    1_000_000, 100_000, 900_000, 1_000_000, 0, model, 2e-6, 8e-6, 1.4
                )
                cached = value["batch_cached_cost"]
                self.assertEqual(value["uses_prompt_cache"], read is not None)
                self.assertAlmostEqual(cached, (0.2 + 1.8 * (read or 1) + 0.8) / 2)
                # Assistant-led's quote offers a reused figure only when the
                # Batch reads, and approves the same most either way.
                quoted = price(
                    {
                        "requests": 10,
                        "units": 10,
                        "input_tokens": 1_000_000,
                        "output_tokens": 100_000,
                        "cache_read_tokens": 900_000,
                        "cacheable_tokens": 1_000_000,
                    },
                    {
                        "mode": "batch",
                        "model": model,
                        "provider": "openai",
                        "rates": {"input": 2, "output": 8},
                    },
                    "openai",
                )
                self.assertAlmostEqual(quoted["cost"], 1.4)
                if read is None:
                    self.assertNotIn("batch_cost_reused", quoted)
                else:
                    self.assertAlmostEqual(quoted["batch_cost_reused"], cached)
        # GPT-6.1 Sol reads at a twentieth and writes the rest of its
        # cacheable input at 1.25 times.
        value = openai_cache_prices(
            1_000_000, 100_000, 800_000, 1_000_000, 0, "gpt-6.1-sol", 2e-6, 8e-6, 1.4
        )
        self.assertEqual(value["cache_write_tokens"], 200_000)
        self.assertAlmostEqual(value["batch_cached_cost"], (0.5 + 1.6 * 0.05 + 0.8) / 2)

    def test_an_openai_batch_that_only_writes_the_cache_shows_those_writes(self):
        # A GPT-5.6-or-later Batch whose cacheable prompts share no prefix
        # expects no reads, but OpenAI's Batch still bills each prompt's
        # cache write at 1.25 times input. Its Guided Batch price and the
        # whole-game estimate's once showed the price without a cache, below
        # the most the Batch costs.
        from dazedtl.compatibility.estimate_prices import prices
        from dazedtl.compatibility.full_estimate import prices as row_prices

        value = prices(
            {
                "input_tokens": 1_000_000,
                "output_tokens": 100_000,
                "cache_read_tokens": 0,
                "cacheable_tokens": 600_000,
                "dynamic_tokens": 1_000_000,
            },
            {"model": "gpt-6.1-sol", "rates": {"input": 2, "output": 8}},
            "openai",
        )
        most = (0.8 + 0.6 * 1.25 * 2 + 0.8) / 2
        self.assertEqual(
            (value["cache_write_tokens"], value["cache_kind"]), (600_000, "automatic")
        )
        self.assertAlmostEqual(value["batch_cost"], most)
        self.assertAlmostEqual(value["batch_max_cost"], most)
        self.assertEqual(
            {
                key: value
                for key, value in row_prices(value).items()
                if key in ("promptCache", "batchCost", "batchMaxCost")
            },
            {"promptCache": True, "batchCost": most, "batchMaxCost": most},
        )
        # A -pro model's Batch has no prompt cache, so it writes none either.
        pro = prices(
            {
                "input_tokens": 1_000_000,
                "output_tokens": 100_000,
                "cache_read_tokens": 0,
                "cacheable_tokens": 600_000,
                "dynamic_tokens": 1_000_000,
            },
            {"model": "gpt-6.1-pro", "rates": {"input": 2, "output": 8}},
            "openai",
        )
        self.assertEqual(
            (pro["cache_write_tokens"], pro["uses_prompt_cache"]), (0, False)
        )
        self.assertAlmostEqual(pro["batch_max_cost"], (2 + 0.8) / 2)

    def test_a_stopped_batch_records_its_cache_reads_as_a_completed_one_does(self):
        # A canceled Batch's paid rows once added their whole prompt to
        # uncached input, so its Spent priced cache reads at the full rate.
        from dazedtl.compatibility.translation import TranslationProvider
        from util.batch_providers import download_results

        body = {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "prompt_tokens_details": {"cached_tokens": 2},
            },
        }
        row = {"custom_id": "a", "response": {"status_code": 200, "body": body}}

        def client(status):
            return SimpleNamespace(
                batches=SimpleNamespace(
                    retrieve=lambda _: SimpleNamespace(
                        status=status, output_file_id="out", error_file_id=""
                    )
                ),
                files=SimpleNamespace(
                    content=lambda _: SimpleNamespace(text=json.dumps(row))
                ),
            )

        provider = TranslationProvider.__new__(TranslationProvider)
        provider.provider, provider.client = "openai", client("cancelled")
        provider.google = None
        results, errors, usage = provider.collect_terminal("b", {"a": "key"})
        self.assertEqual((list(results), errors), (["key"], {}))
        completed = download_results(
            "openai", "b", {"a": "key"}, client=client("completed")
        )[2]
        self.assertEqual(usage, completed)
        self.assertEqual(
            (usage["input_tokens"], usage["cache_read_input_tokens"]), (8, 2)
        )

    def test_openrouter_batch_lifts_the_frozen_host_and_rejects_mixed_routes_before_submission(
        self,
    ):
        # Batch routing belongs before the requests array in the batch header;
        # per-row routing must never be dropped or silently combined.
        from dazedtl.compatibility.openrouter_batch import Client
        from dazedtl.compatibility.request_parameters import host_routing
        from dazedtl.settings.openrouter import TRANSPORT

        providers = ModuleType("util.batch_providers")
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
        with replaced_modules({"util.batch_providers": providers}):
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

    def test_a_paid_attempt_replaces_a_files_receipt_and_a_failed_save_fails(self):
        # A later attempt can read and count the same Batch results again, as
        # after a Stop and resume, so an attempt that paid replaces the file's
        # receipt instead of adding to it; one that paid nothing, reading back
        # what an earlier attempt saved, keeps it. An RPG Maker file whose
        # save failed after validation mismatches read as a soft success, so
        # the run did not show it failed.
        from util.translation_task import TranslationTask, file_marker_result

        def worker(task, files, estimate_only, batch_phase, file_result_callback):
            saved = "TOTAL: [Input: 70][Output: 9][Cost: $0.5000][4.0s] ✓"
            unsaved = "Map002.json: [Input: 30][Output: 3][Cost: $0.2500][2.0s] ✗"
            # A retry reads back what an earlier attempt saved, paying nothing.
            replayed = "TOTAL: [Input: 0][Output: 0][Cost: $0.0000][0.1s] ✓"
            for name, payload, mismatches in (
                ("Map001.json", {"result": saved}, 0),
                ("Map002.json", {"result": "Fail", "receipt": unsaved}, 2),
                ("Map003.json", {"result": replayed}, 0),
            ):
                file_result_callback(
                    name, file_marker_result("FILE_RESULT", payload, mismatches)
                )
            return "Success"

        def figures(tokens_in, tokens_out, cost, seconds):
            return {
                "input": tokens_in,
                "output": tokens_out,
                "cost": cost,
                "seconds": seconds,
            }

        files = ["Map001.json", "Map002.json", "Map003.json"]
        expected = [
            ("Map001.json", figures(70, 9, 0.5, 4.0)),
            ("Map002.json", figures(30, 3, 0.25, 2.0)),
            ("Map003.json", figures(10, 1, 0.25, 1.0)),
        ]
        total = "TOTAL: [Input: 110][Output: 13][Cost: $1.0000][7.0s] ✓"
        with TemporaryDirectory() as directory:
            task = TranslationTask(
                Path(directory),
                ("RPG Maker MV/MZ", (".json",), None),
                receipts={
                    "Map001.json": figures(50, 5, 0.25, 3.0),
                    "Map003.json": figures(10, 1, 0.25, 1.0),
                },
            )
            errors, mismatched, receipts = [], [], []
            task.receipt_signal.connect(lambda *args: receipts.append(args))
            with patch.object(TranslationTask, "run_module_in_process", worker):
                # Batch collection only queues requests: nothing is paid.
                task._run_files(files, False, "collect")
                self.assertEqual(receipts, [])
                task.file_error_signal.connect(lambda *args: errors.append(args))
                task.file_mismatch_signal.connect(lambda *args: mismatched.append(args))
                result = task._run_files(files, False, "consume")
                self.assertEqual(result, "Fail")
                self.assertEqual([name for name, _ in errors], ["Map002.json"])
                self.assertEqual(mismatched, [])
                # The run's records keep what its TOTAL adds up.
                self.assertEqual(receipts, expected)
                self.assertEqual(task._run_total(result), total)
                # Stop lost the consume worker's cache writes, so the resumed
                # attempt reads the same Batch result and failed reply again:
                # each counts once.
                result = task._run_files(files, False, "consume")
        self.assertEqual(receipts, expected * 2)
        self.assertEqual(task._run_total(result), total)

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
            module.write_text(
                """import json, threading
from pathlib import Path
from tests.engine import point
launch_worker = point(lambda *_args, **_kwargs: None)
finish_estimate = point(lambda _directory, _plan, estimate, _stopped: estimate)
class ManualJobs:
    def __init__(self, workspace, lock, **kwargs):
        self.root = Path(workspace)/'manual'
        self.lock = lock
        self.stopping = threading.Event()
        self.jobs = {}
        self.load_saved()
    def folder(self, identity): return self.root/'jobs'/identity
    def load_saved(self):
        self.jobs['fixture'] = json.loads((self.folder('fixture')/'job.json').read_text(encoding='utf-8'))
    def _event(self, job, event):
        if event['event'] == 'log': return
        job.update(status='canceled' if job['phase']=='canceled' else 'complete' if event['args'][0] else 'failed', message=event['args'][1])
    def _launch(self, job, resume): job['status'] = 'running'
""",
                encoding="utf-8",
            )
            controller = manual_jobs(
                source, source / "profile", threading.RLock(), False
            )
            self.assertEqual(controller.jobs["fixture"]["status"], "canceled")
            self.assertEqual(
                json.loads((folder / "job.json").read_text(encoding="utf-8")), job
            )
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
            # Keep every receipt the run's worker reports after the native log
            # cap: a file's, and the names passes', which name no file.
            from dazedtl.compatibility.process_view import file_metrics

            metric_run = {
                "mode": "batch",
                "phase": "consume",
                "files": ["Items.json"],
                "log": [],
            }
            items = {"input": 120, "output": 20, "cost": 0.0042, "seconds": 12.5}
            names = {"input": 60, "output": 12, "cost": 0.02, "seconds": 3.0}
            for name, figures in (
                ("Items.json", items),
                ("speakers", names),
                ("Other.json", items),
            ):
                controller._event(
                    metric_run, {"event": "receipt", "args": [name, figures]}
                )
            self.assertEqual(
                file_metrics(metric_run),
                {"Items.json": {"cost": 0.0042, "seconds": 12.5}},
            )
            # A resumed attempt's TOTAL starts from the same receipts.
            self.assertEqual(
                controller.receipts(metric_run),
                {"Items.json": items, "speakers": names},
            )
            restored = json.loads(json.dumps(metric_run))
            self.assertEqual(file_metrics(restored), file_metrics(metric_run))
            # Live runs from before receipts were kept show the ones their
            # log retained.
            legacy = {
                "mode": "translate",
                "files": ["Items.json"],
                "log": [
                    "Items.json: [Input: 120] [Output: 20] [Cost: $0.0042] [12.5s] ✓"
                ],
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
            (root / "modules/rpgmakermvmz.py").write_text(
                """
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
""",
                encoding="utf-8",
            )
            rows = {row["key"]: row for row in catalog(root)["controls"]}
            self.assertEqual(rows["CODE357"]["builtins"], ["BuiltIn"])
            self.assertEqual(rows["CODE355655"]["builtins"], ["_Text"])
            self.assertEqual(
                rows["CODE356"]["builtins"], ["AlwaysCheckedChoice", "MessageCommand"]
            )
            self.assertEqual(rows["CODE357"]["choices"][0]["id"], "Case/Plugin")
            self.assertIn("message", rows["CODE357"]["choices"][0]["details"])
            self.assertEqual(rows["CODE356"]["choices"], [])
            # Engine fixes elsewhere in the module leave findings current; a
            # new registry entry does not.
            module = root / "modules/rpgmakermvmz.py"
            before = catalog(root)["fingerprint"]
            module.write_text(
                module.read_text(encoding="utf-8") + "\ndef fixed():\n    pass\n",
                encoding="utf-8",
            )
            self.assertEqual(catalog(root)["fingerprint"], before)
            module.write_text(
                module.read_text(encoding="utf-8").replace(
                    '"Case/Plugin"', '"Case/Plugin": (["message"], "font"), "New"'
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(catalog(root)["fingerprint"], before)

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

    def test_guided_patch_proposal_keeps_previously_tracked_runtime_assets(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            write_json(game / "data/Items.json", [None])
            (game / "img").mkdir()
            (game / "img/title.png").write_bytes(b"generated asset fixture")
            (game / "README.md").write_text("Repository metadata", encoding="utf-8")
            # A working GameUpdate config joins the proposal so the published
            # patch carries it.
            (game / "gameupdate").mkdir()
            (game / "gameupdate/patch-config.txt").write_text(
                "repo=fixture", encoding="utf-8"
            )
            preparation = ModuleType("util.project_preparation")
            preparation.rpgmaker_layout = lambda _: {
                "engine": "MVMZ",
                "data_path": game / "data",
                "plugins_js": None,
            }
            scope = ModuleType("util.len_patch_scope")
            scope.patch_manifest = lambda value: value
            scope.CONFIG = "gameupdate/patch-config.txt"
            scope.updater_config = lambda root: (root / scope.CONFIG).is_file()
            scope.dazedtl_files = lambda _root: {}
            git = ModuleType("util.version_update.git_workflow")
            git._run_git = lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0, stdout="img/title.png\0README.md\0"
            )
            with replaced_modules(
                {module.__name__: module for module in (preparation, scope, git)},
            ):
                self.assertEqual(
                    runtime_files(game),
                    [
                        "data/Items.json",
                        "gameupdate/patch-config.txt",
                        "img/title.png",
                    ],
                )

    def test_a_game_write_waits_for_an_unfinished_git_operation(self):
        # A file written during a game update's stopped merge leaves Versions
        # unable to cancel the update; Line widths, Plugin files, Images,
        # playtest fixes and the playtest tools each once wrote without it.
        from dazedtl import actions
        from dazedtl.compatibility.game_write import GameWrite, write_game

        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / ".git").mkdir()
            with patch(
                "util.version_update.git_workflow.read_checkout",
                return_value=checkout(game, "CHERRY_PICK_HEAD"),
            ) as read:
                with (
                    self.assertRaisesRegex(ValueError, "interrupted update"),
                    write_game(game),
                ):
                    self.fail("The write ran mid cherry-pick.")
                install = {"action": "inspector_install", "project": {"source": game}}
                engine = Mock()
                with self.assertRaisesRegex(ValueError, "interrupted update"):
                    actions.run(engine, install, print)
                engine.assert_not_called()
                read.return_value = checkout(game)
                game_write._statuses.clear()
                # A real repository's checkpoint is the checkpoint tests'.
                with (
                    patch("dazedtl.compatibility.checkpoint_commits.Checkpoint"),
                    write_game(game) as written,
                ):
                    written.put("data/Items.json", b"[]")
            self.assertEqual((game / "data/Items.json").read_bytes(), b"[]")
            # The suite fails app code that writes a game file any other way,
            # though DazedTL's own records may be written directly.
            GameWrite(game).put(".dazedtl/plugin-work/state.json", b"{}")
            with self.assertRaisesRegex(RuntimeError, "outside the game-write gateway"):
                GameWrite(game).put("data/Items.json", b"[{}]")

    def test_ace_packing_saves_a_receipt_only_when_every_export_was_packed(self):
        from dazedtl.compatibility.checkpoint_commits import _git
        from dazedtl.compatibility.game_write import write_game
        from dazedtl.translation import checkpoint_records
        from dazedtl.translation.release import packing_state
        from util.len_git import setup_git
        from util.len_translation import LenProject

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
            packed, calls = [], []

            def pack(_root, _action, _log, *, only=None):
                calls.append(only)
                names = [
                    name
                    for name in packed
                    if only is None or Path(name).stem.casefold() in only
                ]
                exports = {
                    path.stem.casefold(): path.read_bytes()
                    for path in (game / "ace_json").glob("*.json")
                }
                for name in names:
                    path = game / "Data" / name
                    path.parent.mkdir(exist_ok=True)
                    # Data holds what its export does, as the converter's.
                    export = exports.get(Path(name).stem.casefold(), b"")
                    path.write_bytes(b"\x04\x08" + export)
                return [game / "Data" / name for name in names]

            def archive_in_root(source, guided=False):
                return (
                    "Run Convert Ace data"
                    if (source / "Game.rgss3a").exists()
                    else None
                )

            converter = ModuleType("util.ace.actions")
            converter.run, converter.archive_in_root = pack, archive_in_root
            workflow = ModuleType("desktop.backend.workflow_actions")
            workflow.validate_plan = lambda _plan: None
            with replaced_modules(
                {
                    "util.ace.actions": converter,
                    "desktop.backend.workflow_actions": workflow,
                },
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

                # A write to the game's text packs the exports changed since
                # the receipt, and the receipt stays current.
                def write(name):
                    with write_game(game, folder) as written:
                        written.put(name, b'[null, {"name": "Potion"}]')

                calls.clear()
                write("ace_json/Items.json")
                self.assertEqual(calls, [{"items"}])
                self.assertTrue(packing_state(native, folder)["current"])
                # Without a current receipt, as after Data changed outside
                # the app, a write packs only what it touched and leaves the
                # rest of Data to an explicit pack of everything.
                (game / "Data/Items.rvdata2").write_bytes(b"edited")
                calls.clear()
                write("ace_json/CommonEvents.json")
                self.assertEqual(calls, [{"commonevents"}])
                self.assertFalse(packing_state(native, folder)["current"])
                run_ace(plan, lambda _line: None)
                self.assertEqual(calls, [{"commonevents"}, None])
                self.assertTrue(packing_state(native, folder)["current"])
                # Undoing a write, as History and Checkpoints do, packs
                # through the receipt too, so Release takes the game as it is.
                setup_git(LenProject(game), version="1.0", current_is_untranslated=True)
                with write_game(game, folder) as written:
                    written.put("ace_json/Items.json", b'[null, {"name": "Ether"}]')
                commit = _git(game, "rev-parse", "HEAD").stdout.strip()
                records = checkpoint_records.Records(game, publications=folder)
                checkpoint_records.undo(records, commit)
                self.assertTrue(packing_state(native, folder)["current"])
                # Data an assistant edited itself, which packing ace_json would
                # not give, stays as an undo puts it back, and Release asks to
                # Pack outside edits rather than overwriting it.
                items = game / "Data/Items.rvdata2"
                with write_game(game, folder) as written:
                    written.put("Data/Items.rvdata2", b"assistant's edit")
                with write_game(game, folder) as written:
                    written.put("ace_json/Items.json", b'[null, {"name": "Elixir"}]')
                commit = _git(game, "rev-parse", "HEAD").stdout.strip()
                checkpoint_records.undo(records, commit)
                self.assertEqual(items.read_bytes(), b"assistant's edit")
                self.assertFalse(packing_state(native, folder)["current"])
                # An archive the game still reads refuses before the write.
                (game / "Game.rgss3a").write_bytes(b"RGSSAD")
                with (
                    self.assertRaisesRegex(ValueError, "Convert Ace data"),
                    write_game(game, folder),
                ):
                    self.fail("The write ran beside the archive.")

    def test_game_update_writes_its_config_only_once_git_can_take_it(self):
        # The Project page syncs GameUpdate's config as it polls; a config
        # written during a game update's stopped merge left Versions unable
        # to cancel the update.
        with TemporaryDirectory() as temporary:
            game = Path(temporary)
            for folder in ("data", "gameupdate", ".git"):
                (game / folder).mkdir()
            (game / "gameupdate/patch.ps1").write_text(
                "# GameUpdate\n", encoding="utf-8"
            )
            defaults = {
                "forge": "gitlab",
                "host": "gitgud.io",
                "username": "dazed-translations",
                "branch": "main",
            }
            engine = TranslationEngine.__new__(TranslationEngine)
            with (
                patch(
                    "util.version_update.git_workflow.read_checkout",
                    return_value=checkout(game, "MERGE_HEAD"),
                ) as read,
                patch("util.gameupdate_config.remote_urls", return_value={}),
                patch("dazedtl.compatibility.checkpoint_commits.Checkpoint"),
            ):
                with self.assertRaisesRegex(ValueError, "unfinished Git merge"):
                    engine.game_update(game, defaults, "save", "fixture-patch")
                self.assertEqual(
                    sorted(path.name for path in game.rglob("*")),
                    [".git", "data", "gameupdate", "patch.ps1"],
                )
                read.return_value = checkout(game)
                game_write._statuses.clear()
                saved = engine.game_update(game, defaults, "save", "fixture-patch")
            self.assertEqual(saved["state"], "ready")
            self.assertIn(
                "repo=fixture-patch",
                (game / "gameupdate/patch-config.txt").read_text(encoding="utf-8"),
            )

    def test_assistant_led_writes_to_ace_json_pack_the_games_data(self):
        # The game reads only Data: Assistant-led's preparation, writes and
        # Line widths refits once left it as it was while ace_json and the
        # patch moved on. Preparing converts the game, which has no Set up:
        # an encrypted game read only its archive, so writes refused.
        def events(document):
            # The JSON lists a map's events, Ruby's Hash maps them by ID.
            found = document["events"]
            return [*filter(None, getattr(found, "values", lambda: found)())]

        def messages(document):
            return [
                command["parameters"][0]
                for event in events(document)
                for page in event["pages"]
                for command in page["list"]
                if command["code"] == 401
            ]

        with TemporaryDirectory() as temporary:
            from tests.rgssad_archives import archive_v3

            game = Path(temporary) / "game"
            fixture = Path(__file__).resolve().parent / "fixtures/ace"
            game.mkdir()
            (game / "Game.rgss3a").write_bytes(
                archive_v3(
                    [
                        ("Data\\" + path.name, path.read_bytes())
                        for path in sorted((fixture / "Data").iterdir())
                    ],
                    seed=7,
                )
            )
            engine = TranslationEngine.__new__(TranslationEngine)
            engine.profile = Path(temporary) / "profile"
            engine.profile.mkdir()
            options = {
                "mode": "agent",
                "include_images": False,
                "instructions": "",
                "include_glossary_base": False,
                "install_forge": False,
            }
            engine.rpgmaker_prepare(game, options)
            self.assertEqual(sorted(path.name for path in game.glob("Game.rgss*")), [])
            self.assertTrue((game / ".dazedtl/ace/Game.rgss3a").is_file())
            exports = game / "ace_json/Map001.json"
            document = json.loads(exports.read_text(encoding="utf-8"))
            for event in events(document):
                for command in event["pages"][0]["list"]:
                    if command["code"] == 401:
                        command["parameters"][0] = "Lovely weather today, isn't it?"
            staged = game / ".dazedtl/len-method/work/Map001.json"
            write_json(staged, document)

            def played():
                data = TranslationEngine.ace_data(game, ["Data/Map001.rvdata2"])
                return messages(data["Data/Map001.rvdata2"])

            engine.write_rpgmaker(game, exports, staged, exports)
            self.assertEqual(played(), ["Lovely weather today, isn't it?"])
            narrow = {
                "width": 20,
                "faceWidth": 20,
                "listWidth": 40,
                "noteWidth": 40,
                "messageRows": 4,
            }
            engine.line_widths(game, narrow)
            written = messages(json.loads(exports.read_text(encoding="utf-8")))
            self.assertEqual(played(), written)
            self.assertEqual(written, ["Lovely weather\ntoday, isn't it?"])

            # Rebasing onto a new original, whose bytes Git holds.
            def git(_root, *arguments, **_options):
                answers = {"rev-parse": "original", "hash-object": "blob"}
                if arguments[:2] == ("rev-parse", "original:ace_json/Map001.json"):
                    return SimpleNamespace(stdout="blob\n")
                return SimpleNamespace(stdout=answers[arguments[0]] + "\n")

            for event in events(document):
                for command in event["pages"][0]["list"]:
                    if command["code"] == 401:
                        command["parameters"][0] = "Fine day."
            write_json(staged, document)
            with patch("util.version_update.git_workflow._run_git", git):
                engine.rebase_rpgmaker(
                    game, fixture / "ace_json/Map001.json", staged, exports, "original"
                )
            self.assertEqual(played(), ["Fine day."])

    def test_every_action_handler_is_a_worker_function(self):
        # A misspelt handler would fail only once a user runs the action.
        for row in ROWS:
            if row.handler:
                self.assertTrue(callable(handler(row.name)), row.name)

    def test_phased_worker_launcher_preserves_pipe_controls_and_isolates_the_child(
        self,
    ):
        # A substituted subprocess namespace once dropped PIPE before launch; the
        # launch layer must keep the native pipe controls.
        with TemporaryDirectory() as temporary:
            source = Path(temporary)
            module = source / "desktop/backend/manual.py"
            module.parent.mkdir(parents=True)
            module.write_text(
                """import subprocess, sys, threading
from pathlib import Path
from tests.engine import point
@point
def launch_worker(arguments, **kwargs):
    return subprocess.Popen(arguments, **kwargs)
finish_estimate = point(lambda _directory, _plan, estimate, _stopped: estimate)
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
""",
                encoding="utf-8",
            )
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
                def __init__(self, workspace, lock, operations, manual, _locate):
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
            with replaced_modules({workflow.__name__: workflow}):
                operations = SimpleNamespace(jobs={})
                phases = phased_workflows(
                    source / "phases", None, operations, controller, {}.get
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
                        (phases.folder("owner") / "translated/System.json").read_text(
                            encoding="utf-8"
                        )
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
        with replaced_modules({actions.__name__: actions}):
            validate_publication(plan)
            actions.validate_plan.assert_not_called()
            current["translated"] = "different output"
            with self.assertRaises(ValueError):
                validate_publication(plan)

    def test_line_metadata_reaches_both_provider_payloads_without_changing_the_legacy_batch_contract(
        self,
    ):
        context_module, provider_module = (
            ModuleType(name) for name in ("util.len_translation", "util.translation")
        )
        note = "Check whether the visitor or guard left."
        source_context = "門に二人がいる。"

        compiled = []

        def contexts(_project, batches, _language, **_options):
            compiled.append(batches)
            self.assertEqual(
                set(batches[0]) - {"glossary_names"},
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
            module.__name__: module for module in (context_module, provider_module)
        }
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.project = lambda *_args: None
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
        with (
            patch("util.skills.ctx", lambda *_args, **_kwargs: "Field guidance"),
            replaced_modules(modules),
            TemporaryDirectory() as folder,
        ):
            # A release that only changes the engine's code keeps saved plans.
            engine.source = Path(folder)
            util = engine.source / "util"
            (util / "skills").mkdir(parents=True)
            for name in (
                *("len_api", "len_translation", "paths", "translation", "vocab"),
                *("sfx_reference", "reference_games", "skills/__init__"),
                *("skills/contexts", "skills/system"),
            ):
                (util / (name + ".py")).write_text("", encoding="utf-8")
            rows, compiler = compile_requests(engine, "unused", {}, plan, "English")
            Path(folder, "util/vocab.py").write_text("# changed", encoding="utf-8")
            self.assertEqual(
                compile_requests(engine, "unused", {}, plan, "English")[1], compiler
            )
            row = rows[0]
            self.assertEqual(row["context"]["line_kinds"], {"line": "dialogue"})
            self.assertEqual(row["context"]["qa_notes"], {"line": note})
            # The response format follows the one rule Guided's builder asks
            # (engine_runtime): JSON mode only for DeepSeek, which has no strict
            # schemas, so a route never gets a schema in only one method.
            for provider, protocol, mode, response_format in (
                ("openai", "openai", "live", "json_schema"),
                ("anthropic", "anthropic", "batch", None),
                ("openrouter", "openai", "live", "json_schema"),
                ("gemini", "gemini", "batch", "json_schema"),
                ("mistral", "mistral", "live", "json_schema"),
                ("deepseek", "openai", "live", "json_object"),
                ("custom", "openai", "live", "json_schema"),
            ):
                with self.subTest(provider=provider):
                    payload = engine.payload(
                        row,
                        {
                            "protocol": protocol,
                            "provider": provider,
                            "mode": mode,
                            "model": "fixture",
                            "endpoint": PROVIDERS[provider]["endpoint"]
                            or "https://provider.invalid/v1",
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
                    self.assertEqual(
                        payload.get("response_format", {}).get("type"),
                        response_format,
                    )
                    if provider == "openrouter":
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

            # Under the line-key policy the provider reads lines keyed 1 to N,
            # notes included; a scene note written another way keeps unit IDs
            # so it still names its lines.
            from dazedtl.translation.requests import LINE_KEYS, scene_list

            keyed_settings = {
                "protocol": "openai",
                "provider": "openai",
                "mode": "live",
                "model": "fixture",
                "endpoint": "https://provider.invalid/v1",
                "lineKeys": LINE_KEYS,
            }
            self.assertEqual(
                engine.payload(row, keyed_settings)["captured"]["user"],
                row["context"]["user"],
            )
            organized = {
                "batches": [
                    {
                        **plan["batches"][0],
                        "scene_context": scene_list([("gate", ["line"])]),
                    }
                ]
            }
            keyed, _compiler = compile_requests(
                engine, "unused", {}, organized, "English"
            )
            payload = engine.payload(keyed[0], keyed_settings)
            self.assertIn('{"1": "行った。"}', payload["captured"]["user"])
            self.assertIn(json.dumps({"1": note}), payload["captured"]["user"])
            self.assertIn("- gate: line 1", payload["captured"]["request_instructions"])
            # A partly translated scene's stretch follows the scene note.
            stretched, _compiler = compile_requests(
                engine,
                "unused",
                {},
                {
                    "batches": [
                        {
                            **organized["batches"][0],
                            "stretches": [
                                {
                                    "first": "line",
                                    "last": "line",
                                    "before": [["来た。", "They came."]],
                                }
                            ],
                        }
                    ]
                },
                "English",
            )
            self.assertTrue(
                engine.payload(stretched[0], keyed_settings)["captured"][
                    "request_instructions"
                ].endswith(
                    "- gate: line 1\n\nSome of these lines continue a scene whose "
                    "other lines were translated earlier. Each stretch of them below "
                    "lists the lines just before it, with their earlier English after "
                    "→; continue the scene from them. The stretches:\n- line 1\n"
                    "  来た。 → They came."
                )
            )
            self.assertEqual(
                payload["response_format"]["json_schema"]["schema"]["required"], ["1"]
            )
            # A battle message's skill users join its request, and their names
            # bring their glossary entries (translation/skill_users).
            from dazedtl.translation.requests import SKILL_USERS

            noted, _compiler = compile_requests(
                engine,
                "unused",
                {},
                organized,
                "English",
                {"line": ("actor リリ; enemy スライム", ["リリ", "スライム"])},
            )
            self.assertEqual(compiled[-1][0]["glossary_names"], ["リリ", "スライム"])
            self.assertNotIn("glossary_names", compiled[-2][0])
            self.assertIn(
                SKILL_USERS + "\n1: actor リリ; enemy スライム\n",
                engine.payload(noted[0], keyed_settings)["captured"]["user"],
            )

            # New OpenRouter plans require the exact source-ID schema on both
            # transports; a legacy plan without the policy sends its saved
            # requests as they were.
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

        engine = TranslationEngine.__new__(TranslationEngine)
        for result in (Update("saved"), Update(None, ("data/Items.json",))):
            with (
                self.subTest(result=result),
                patch(
                    "util.version_update.continue_with_official",
                    lambda _source, _release: result,
                ),
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

    def test_an_empty_request_is_refused_by_name_live_or_batch(self):
        # translateAI builds a Claude Batch row with buildClaudeRequest, which
        # did not check its text, so only OpenAI rows and Live requests were
        # refused. The refusal names what was empty, never the prompt, which
        # logs and run evidence keep.
        from util import translation

        for build, args in (
            (translation.buildClaudeRequest, ("json", "claude-opus-5-5", 1)),
            (translation.buildOpenAIRequest, (0, "json", "gpt-4.1", 1)),
        ):
            for system, user, role in (
                ("Private prompt", " ", "user"),
                ("", "Private prompt", "system"),
            ):
                with (
                    self.subTest(build=build.__name__, role=role),
                    self.assertRaisesRegex(ValueError, role) as raised,
                ):
                    build(system, user, [], *args)
                self.assertNotIn("Private prompt", str(raised.exception))
        with self.assertRaises(ValueError) as raised:
            translation._check_message_content(
                [
                    {"role": "user", "content": "Private prompt"},
                    {"role": "assistant", "content": "", "note": "Private prompt"},
                ]
            )
        self.assertRegex(str(raised.exception), r"\b1\b.*assistant")
        self.assertNotIn("Private prompt", str(raised.exception))

    def test_progress_reports_leave_a_checkpointed_gitignore_unchanged(self):
        # A checkpoint after an image apply leaves the image rules between
        # Len's work block and its patch block. Moving the work block again
        # dirtied the committed .gitignore, so packaging refused. A new work
        # block goes above the patch rules, leaving the portable-settings
        # allowlist last: below the work block's rules, it hid the glossary.
        # Rescoping the patch block left its blank lines behind, so every
        # version committed a .gitignore with 3 more, whichever block came first,
        # and rules written after the block gained a blank line above them.
        # A game recorded before Git setup has the allowlist alone, and a work
        # block after it hid the glossary from Git.
        stdout = finished(gitignore)
        self.assertEqual(stdout.split(), ["True"] * 6)

    def test_git_setup_accepts_declared_files_the_patch_will_add(self):
        # A Unity mod patch delivers only files the original lacks, such as
        # BepInEx; Git setup refused them because they didn't exist yet.
        self.assertIn("lacks or ignores: winhttp.dll", finished(patch_files))

    def test_images_are_a_progress_phase_of_their_own(self):
        # Translation could not complete while images remained, so a run that
        # finished its text showed it in progress beside the next phase. Saved
        # reports from before the Images phase must still read.
        self.assertEqual(
            json.loads(finished(images_phase)),
            [
                "active",
                (
                    "Images cannot be complete while 0 of 1 images units count as translated; "
                    "a unit counts once it has its translation and the translated_from_sha256 of its current source."
                ),
                "active",
                "out_of_scope",
                True,
                2,
                "Unit a appears in more than one part.",
                "Only a text export can list parts, in place of its units list.",
            ],
        )

    def test_the_update_check_speaks_the_games_target_language(self):
        # The update check showed players its English text whatever language
        # the game was translated into. A game without a recorded pair is
        # translated into English, and a value written in plugins.js by hand
        # stays.
        self.assertEqual(
            json.loads(finished(update_check_text)),
            [{}, "翻訳の更新があります", "つづく", {"continueButton": "つづく"}, 1],
        )

    def test_bundled_forge_accepts_the_install_patches(self):
        # Upstream refreshes rename Forge's minified identifiers; patches pinned
        # to the old names made every Forge install fail.
        patches = engine_module("util/forge/modern_patches.py")
        bundle = ENGINE / "util/forge/upstream/Forge_MZ.js"
        text = patches.apply_modern_forge_patches(
            bundle.read_text(encoding="utf-8"), "Ctrl+F9"
        )
        self.assertIn("keyStr:`ctrl f9`", text)
