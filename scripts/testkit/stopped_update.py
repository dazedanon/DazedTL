"""Applies a previewed official update to a game as the app's Apply does,
recording the prepared release first, and stops at Git's first conflict,
leaving the cherry-pick unfinished as an apply the app closed during leaves
it; the app's own apply resolves conflicts at once. Prints the conflicted
files.

    python scripts/testkit/stopped_update.py ROOT WORKSPACE PREVIEW

ROOT is the checkout whose engine applies it, WORKSPACE the scenario's
workspace and PREVIEW the completed preview's run ID.
"""

import json
import sys
from functools import partial
from pathlib import Path


def main() -> None:
    root, workspace, preview = sys.argv[1:4]
    sys.path[:0] = [
        str(Path(root) / "backend/dazedtl/engine"),
        str(Path(root) / "backend"),
    ]
    from dazedtl.compatibility.translation import TranslationEngine
    from dazedtl.projects import location
    from dazedtl.translation.jobs import RunStore
    from dazedtl.translation.operations import execute
    from util import version_update

    workspace = Path(workspace).resolve()
    location.use(workspace)
    job, plan = RunStore(workspace).load(preview)
    engine = TranslationEngine(workspace / "engine")
    # The one difference from the app's Apply.
    version_update.apply_official_update = partial(
        version_update.apply_official_update, auto_resolve=False
    )
    with engine.context():
        result = execute(
            engine,
            workspace,
            {"project_id": job["project_id"]},
            {
                **plan,
                "action": "version_apply",
                "arguments": {**plan["arguments"], "preview": job["result"]},
            },
            lambda: False,
        )
    if result.get("complete") or not result.get("pending_conflicts"):
        sys.exit("The update applied without stopping at a conflict.")
    print(json.dumps(list(result["pending_conflicts"])))


if __name__ == "__main__":
    main()
