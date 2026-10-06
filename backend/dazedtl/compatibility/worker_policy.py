"""Restore frozen rates and generation parameters in private native workers."""

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, cast

from dazedtl.settings.preferences import (
    CHOICE_COLLECTION,
    GENERATION_PARAMETERS,
    SPEAKER_CONTEXT,
    batch_input_tokens,
    output_tokens,
)
from dazedtl.settings.providers import infer_provider, openrouter_host
from dazedtl.storage import write_json
from dazedtl.translation.refusals import POLICY as REFUSAL_POLICY

from . import (
    batch_pricing,
    choice_requests,
    state_requests,
)
from .request_parameters import configure_builders
from .run_evidence import Evidence


def configure_batch_allowance(translation, policy):
    native = getattr(
        translation._openai_batch_token_limit,
        "_dazedtl_native",
        translation._openai_batch_token_limit,
    )
    allowance = batch_input_tokens((policy or {}).get("batchInputTokens"))
    if allowance is None:
        translation._openai_batch_token_limit = native
    else:

        def limit():
            return allowance

        limit._dazedtl_native = native
        translation._openai_batch_token_limit = limit


def configure_states(plan, root, policy):
    module = sys.modules.get("modules.rpgmakermvmz")
    if module is not None and plan.get("engine") in {"MVMZ", "RPG Maker MV/MZ"}:
        cast(Any, module).SPEAKER_CONTEXT = bool(
            policy and policy.get("speakerContext") == SPEAKER_CONTEXT
        )
        choice_requests.configure(
            module, bool(policy and policy.get("choiceCollection") == CHOICE_COLLECTION)
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

    native_prepare = manual_environment.prepare

    def prepare(root):
        plan = json.loads((Path(root) / "plan.json").read_text(encoding="utf-8"))
        policy = plan.get("dazedtl_request_policy")
        grouping_root = root
        if plan.get("batch_link"):
            from desktop.backend.batches import batch_root

            grouping_root = batch_root(root, plan)
            original_plan = Path(grouping_root) / "plan.json"
            policy = (
                json.loads(original_plan.read_text(encoding="utf-8")).get(
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
            batch_pricing.configure(translation, False)
            configure_builders(translation, None)
            translation.STRICT_STRUCTURED_OUTPUTS = False
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
        host = openrouter_host(policy.get("openrouterHost", ""))
        strict_router = policy.get("openrouterStructuredOutputs") == STRUCTURED_OUTPUTS
        if (host or strict_router) and infer_provider(
            plan["settings"].get("API_PROVIDER"), plan["settings"].get("api", "")
        ) != "openrouter":
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

        openrouter_pricing.configure(translation, router_policy)
        configure_batch_allowance(translation, policy)

        # Long-running batches must retain these rates after the normal cache TTL.
        translation._load_litellm_pricing = lambda: prices
        batch_pricing.configure(translation, True)
        translation.STRICT_STRUCTURED_OUTPUTS = bool(strict_router)
        record = None
        if policy.get("generationParameters") and plan.get("mode") in {
            "estimate",
            "batch",
            "translate",
            "offline",
        }:
            evidence = Evidence(root, plan["mode"], plan)
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
        )
        configure_states(plan, grouping_root, policy)
        checkpoint_reader()
        from .batch_refusals import install_worker

        install_worker(grouping_root, {**plan, "dazedtl_request_policy": policy})
        return result

    manual_environment.prepare = prepare
