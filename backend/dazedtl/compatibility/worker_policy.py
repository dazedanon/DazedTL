"""Restore frozen base rates through the native engine's pricing-cache boundary."""

import json
import math
from pathlib import Path
import time

from dazedtl.storage import write_json


def install():
    from desktop.backend import manual_environment

    native_prepare = manual_environment.prepare

    def prepare(root):
        plan = json.loads((Path(root) / "plan.json").read_text(encoding="utf-8"))
        policy = plan.get("dazedtl_request_policy")
        if policy is None:
            return native_prepare(root)
        if (
            not isinstance(policy, dict)
            or policy.get("version") != 1
            or policy.get("model") != plan["settings"]["model"]
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
        return result

    manual_environment.prepare = prepare
