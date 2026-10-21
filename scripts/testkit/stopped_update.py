"""Applies a previewed official update to a game and stops at Git's first
conflict, leaving the cherry-pick unfinished as an apply the app closed during
leaves it; the app's own apply resolves conflicts at once. Prints the
conflicted files.

    python scripts/testkit/stopped_update.py ROOT GAME OFFICIAL VERSION PREVIEW

ROOT is the checkout whose engine applies it, OFFICIAL the staged release copy
and PREVIEW the completed preview's result as JSON.
"""

import json
import sys
from pathlib import Path


def main() -> None:
    root, game, official, version, preview = sys.argv[1:6]
    sys.path[:0] = [
        str(Path(root) / "backend/dazedtl/engine"),
        str(Path(root) / "backend"),
    ]
    from util.version_update import apply_official_update

    expected = json.loads(preview)
    result = apply_official_update(
        game,
        official,
        version,
        expected_tree=expected["proposed_tree"],
        expected_original_commit=expected["original_commit"],
        expected_translation_commit=expected["translation_commit"],
        expected_asset_manifest=expected["proposed_asset_manifest"],
        expected_baseline_asset_manifest=expected["baseline_asset_manifest"],
        patch_overlay=expected["patch_overlay"],
        auto_resolve=False,
    )
    if result.complete or not result.pending_conflicts:
        sys.exit("The update applied without stopping at a conflict.")
    print(json.dumps(list(result.pending_conflicts)))


if __name__ == "__main__":
    main()
