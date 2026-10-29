"""Restore frozen rates and generation parameters in private native workers."""

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, cast

from dazedtl import system
from dazedtl.settings import effort
from dazedtl.settings.preferences import (
    BATTLE_MESSAGE_USERS_LEVELS,
    CHOICE_COLLECTION,
    CODE_NAMEPLATES,
    GENERATION_PARAMETERS,
    MAP_NAME_IDENTITIES,
    PAGE_PACKING,
    REUSE_STRETCHES,
    RUN_STOPS,
    SAME_LINE_SPEAKERS,
    SHORT_OUTPUTS,
    SMALL_KANA,
    SOURCE_TEXT_LEVELS,
    SPEAKER_CONTEXT,
    STRETCH_NEIGHBOURS,
    batch_input_tokens,
    output_tokens,
)
from dazedtl.settings.providers import infer_provider, openrouter_host
from dazedtl.storage import write_json
from dazedtl.translation.refusals import POLICY as REFUSAL_POLICY

from . import run_stops, state_requests
from .request_parameters import configure_builders
from .run_evidence import Evidence


def configure_batch_allowance(translation, policy):
    allowance = batch_input_tokens((policy or {}).get("batchInputTokens"))
    if allowance is None:
        translation._openai_batch_token_limit.remove("allowance")
    else:
        translation._openai_batch_token_limit.layer(
            "allowance", lambda _native: allowance
        )


def configure_prices(translation, prices):
    """Frozen rates replace the catalog, including after its normal cache TTL."""
    if prices is None:
        translation._load_litellm_pricing.remove("frozen-prices")
    else:
        translation._load_litellm_pricing.layer("frozen-prices", lambda _native: prices)


def configure_short_outputs(translation, policy):
    """Runs frozen before the short-outputs policy measure short outputs
    with their codes, as their estimate did, so they reuse what it counted."""
    translation.CONTENT_TEXT = bool(
        policy and policy.get("shortOutputs") == SHORT_OUTPUTS
    )


def configure_small_kana(translation, policy):
    """Runs frozen before the small-kana policy keep the small kana a reply
    leaves, as they did when approved."""
    translation.SMALL_KANA = bool(policy and policy.get("smallKana") == SMALL_KANA)


def configure_states(plan, root, policy):
    module = sys.modules.get("modules.rpgmakermvmz")
    if module is not None and plan.get("engine") in {"MVMZ", "RPG Maker MV/MZ"}:
        cast(Any, module).SPEAKER_CONTEXT = bool(
            policy and policy.get("speakerContext") == SPEAKER_CONTEXT
        )
        cast(Any, module).SAME_LINE_SPEAKERS = bool(
            policy and policy.get("sameLineSpeakers") == SAME_LINE_SPEAKERS
        )
        cast(Any, module).CODE_NAMEPLATES = bool(
            policy and policy.get("codeNameplates") == CODE_NAMEPLATES
        )
        cast(Any, module).PAGE_PACKING = bool(
            policy and policy.get("pagePacking") == PAGE_PACKING
        )
        cast(Any, module).CHOICE_COLLECTION = bool(
            policy and policy.get("choiceCollection") == CHOICE_COLLECTION
        )
        source_text = (policy or {}).get("sourceText")
        cast(Any, module).SOURCE_TEXT = (
            SOURCE_TEXT_LEVELS.get(source_text, 0)
            if isinstance(source_text, str)
            else 0
        )
        users = (policy or {}).get("battleMessageUsers")
        cast(Any, module).BATTLE_MESSAGE_USERS = (
            BATTLE_MESSAGE_USERS_LEVELS.get(users, 0) if isinstance(users, str) else 0
        )
        if policy and policy.get("stateGrouping") == state_requests.POLICY:
            state_requests.configure(
                module,
                sys.modules["util.translation"],
                root,
                policy["entriesPerRequest"],
            )
        else:
            state_requests.restore(module)


def install(*, coordinator=False):
    from desktop.backend import manual_environment

    def prepare(native_prepare, root):
        plan = json.loads(system.read_text(Path(root) / "plan.json"))
        policy = plan.get("dazedtl_request_policy")
        grouping_root = root
        if plan.get("batch_link"):
            from desktop.backend.batches import batch_root

            grouping_root = batch_root(root, plan)
            original_plan = Path(grouping_root) / "plan.json"
            policy = (
                json.loads(system.read_text(original_plan)).get(
                    "dazedtl_request_policy"
                )
                if original_plan.is_file() and not original_plan.is_symlink()
                else None
            )
        from dazedtl.settings.openrouter import STRUCTURED_OUTPUTS, validate_policy

        from . import openrouter_batch, openrouter_pricing

        if policy is not None and not isinstance(policy, dict):
            raise ValueError(
                "This run's saved model options are invalid or unsupported."
            )
        router_policy = (policy or {}).get("openrouterBatch")
        if router_policy is not None:
            validate_policy(router_policy, plan["settings"]["model"])
            if not openrouter_batch.is_route(plan["settings"].get("api")):
                raise ValueError(
                    "This frozen OpenRouter Batch policy belongs to a different connection."
                )
        openrouter_batch.configure(router_policy, grouping_root)

        def checkpoint_reader():
            from .batch_evidence import install as install_batch_evidence
            from .checkpoints import install as install_checkpoints
            from .speaker_results import install as install_speaker_results

            install_checkpoints(sys.modules.get("modules.rpgmakermvmz"), root, plan)
            install_batch_evidence(sys.modules["util.translation"], root, plan)
            install_speaker_results(sys.modules.get("modules.rpgmakermvmz"), root)
            if coordinator:
                from .batch_continuation import (
                    install_worker as install_batch_continuation,
                )

                install_batch_continuation(root, plan)

        if policy is None:
            result = native_prepare(root)
            from util import translation

            openrouter_pricing.configure(translation, None)
            configure_batch_allowance(translation, None)
            configure_prices(translation, None)
            configure_builders(translation, None)
            translation.STRICT_STRUCTURED_OUTPUTS = False
            configure_short_outputs(translation, None)
            configure_small_kana(translation, None)
            run_stops.configure(translation, None, root)
            configure_states(plan, grouping_root, None)
            checkpoint_reader()
            return result
        if (
            not isinstance(policy, dict)
            or policy.get("version") != 1
            or policy.get("model") != plan["settings"]["model"]
            or policy.get("generationParameters") not in (None, GENERATION_PARAMETERS)
            or policy.get("refusalRetry") not in (None, REFUSAL_POLICY)
            or policy.get("stateGrouping") not in (None, state_requests.POLICY)
            or policy.get("choiceCollection") not in (None, CHOICE_COLLECTION)
            or policy.get("speakerContext") not in (None, SPEAKER_CONTEXT)
            or policy.get("sameLineSpeakers") not in (None, SAME_LINE_SPEAKERS)
            or policy.get("codeNameplates") not in (None, CODE_NAMEPLATES)
            or policy.get("pagePacking") not in (None, PAGE_PACKING)
            or policy.get("reuseStretches") not in (None, REUSE_STRETCHES)
            or policy.get("stretchNeighbours") not in (None, STRETCH_NEIGHBOURS)
            or policy.get("mapNameIdentities") not in (None, MAP_NAME_IDENTITIES)
            or policy.get("sourceText") not in (None, *SOURCE_TEXT_LEVELS)
            or policy.get("shortOutputs") not in (None, SHORT_OUTPUTS)
            or policy.get("smallKana") not in (None, SMALL_KANA)
            or policy.get("runStops") not in (None, RUN_STOPS)
            or policy.get("thinkingEffortRefusals") not in (None, effort.REFUSALS)
            or policy.get("battleMessageUsers")
            not in (None, *BATTLE_MESSAGE_USERS_LEVELS)
            or policy.get("openrouterStructuredOutputs")
            not in (None, STRUCTURED_OUTPUTS)
            or type(policy.get("entriesPerRequest")) is not int
            or not 1 <= policy["entriesPerRequest"] <= 100
            or plan["settings"]["batchsize"] != policy["entriesPerRequest"]
            or any(
                type(policy.get(key)) not in (int, float)
                or not math.isfinite(policy[key])
                or policy[key] < 0
                for key in ("inputRate", "outputRate")
            )
        ):
            raise ValueError(
                "This run's saved model options are invalid or unsupported."
            )
        batch_input_tokens(policy.get("batchInputTokens"))
        output_allowance = output_tokens(policy.get("maxOutputTokens"))
        thinking_effort = effort.checked(policy.get("thinkingEffort"))
        thinking_listed = policy.get("thinkingEffortListed")
        provider = infer_provider(
            plan["settings"].get("API_PROVIDER"), plan["settings"].get("api", "")
        )
        host = openrouter_host(policy.get("openrouterHost", ""))
        strict_router = policy.get("openrouterStructuredOutputs") == STRUCTURED_OUTPUTS
        if (host or strict_router) and provider != "openrouter":
            raise ValueError(
                "This run's selected host requires an OpenRouter connection."
            )
        model = policy["model"].strip().lower().removeprefix("models/")
        prices = {
            model: {
                "input_cost_per_token": policy["inputRate"] / 1_000_000,
                "output_cost_per_token": policy["outputRate"] / 1_000_000,
            }
        }
        cache = Path(root) / "log/litellm_pricing.json"
        if cache.is_symlink() or cache.parent.is_symlink():
            raise ValueError(
                "The run's derived pricing cache must stay inside its workspace."
            )
        # Seed before native preparation, so the engine's first import sees these
        # rates without fetching a catalog. Preserve native context/import ordering.
        write_json(cache, {"fetched_at": time.time(), "prices": prices})
        result = native_prepare(root)
        from util import translation

        openrouter_pricing.configure(
            translation, router_policy, thinking_effort=thinking_effort
        )
        configure_batch_allowance(translation, policy)
        configure_prices(translation, prices)
        translation.STRICT_STRUCTURED_OUTPUTS = bool(strict_router)
        configure_short_outputs(translation, policy)
        configure_small_kana(translation, policy)
        record = None
        if policy.get("generationParameters") and plan.get("mode") in {
            "estimate",
            "batch",
            "translate",
        }:
            evidence = Evidence(
                root,
                plan["mode"],
                plan,
                share_stretches=policy.get("reuseStretches") == REUSE_STRETCHES,
                stretch_neighbours=policy.get("stretchNeighbours")
                == STRETCH_NEIGHBOURS,
                map_name_identities=policy.get("mapNameIdentities")
                == MAP_NAME_IDENTITIES,
                source_aware=SOURCE_TEXT_LEVELS.get(str(policy.get("sourceText")), 0)
                >= 2,
            )
            evidence.install(translation, sys.modules.get("modules.rpgmakermvmz"))
            record = evidence.record
        configure_builders(
            translation,
            policy.get("generationParameters"),
            record,
            openrouter_host=host,
            max_output_tokens=output_allowance,
            structured_outputs=strict_router,
            batch=plan.get("mode") == "batch" or bool(plan.get("batch_link")),
            openrouter_batch=router_policy,
            provider=provider,
            thinking_effort=thinking_effort,
            thinking_listed=thinking_listed,
            thinking_refusals=policy.get("thinkingEffortRefusals"),
        )
        run_stops.configure(translation, policy, root, coordinator=coordinator)
        configure_states(plan, grouping_root, policy)
        checkpoint_reader()
        from .batch_refusals import install_worker

        install_worker(grouping_root, {**plan, "dazedtl_request_policy": policy})
        return result

    manual_environment.prepare.layer("request-policy", prepare)
