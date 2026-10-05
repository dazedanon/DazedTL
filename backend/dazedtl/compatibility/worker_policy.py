"""Restore frozen rates and generation parameters in private native workers."""

import json
import math
from pathlib import Path
import time
import sys

from dazedtl.storage import write_json
from dazedtl.settings.preferences import GENERATION_PARAMETERS
from .request_parameters import configure_builders
from . import state_requests, batch_pricing
from .run_evidence import Evidence


def configure_states(plan, root, policy):
    module = sys.modules.get("modules.rpgmakermvmz")
    if module is not None and plan.get("engine") in {"MVMZ", "RPG Maker MV/MZ"}:
        if policy and policy.get("stateGrouping") == state_requests.POLICY:
            state_requests.configure(module, sys.modules["util.translation"], root, policy["entriesPerRequest"])
        else:
            state_requests.restore(module)


def install():
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
            policy = (json.loads(original_plan.read_text(encoding="utf-8")).get("dazedtl_request_policy")
                      if original_plan.is_file() and not original_plan.is_symlink() else None)
        def checkpoint_reader():
            from .checkpoints import install as install_checkpoints
            from .batch_evidence import install as install_batch_evidence
            from .speaker_results import install as install_speaker_results
            install_checkpoints(sys.modules.get("modules.rpgmakermvmz"), root, plan)
            install_batch_evidence(sys.modules["util.translation"], root, plan)
            install_speaker_results(sys.modules.get("modules.rpgmakermvmz"), root)

        if policy is None:
            result = native_prepare(root)
            import util.translation as translation
            batch_pricing.configure(translation, False)
            configure_builders(translation, None)
            configure_states(plan, grouping_root, None)
            checkpoint_reader()
            return result
        if (
            not isinstance(policy, dict)
            or policy.get("version") != 1
            or policy.get("model") != plan["settings"]["model"]
            or policy.get("generationParameters") not in (None, GENERATION_PARAMETERS)
            or policy.get("stateGrouping") not in (None, state_requests.POLICY)
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
        import util.translation as translation

        # Long-running batches must retain these rates after the normal cache TTL.
        translation._load_litellm_pricing = lambda: prices
        batch_pricing.configure(translation, True)
        record = None
        if policy.get("generationParameters") and plan.get('mode') in {'estimate', 'batch', 'translate', 'offline'}:
            evidence = Evidence(root, plan["mode"], plan)
            evidence.install(translation, sys.modules.get("modules.rpgmakermvmz"))
            record = evidence.record
        configure_builders(translation, policy.get("generationParameters"), record)
        configure_states(plan, grouping_root, policy)
        checkpoint_reader()
        return result

    manual_environment.prepare = prepare
