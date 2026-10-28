"""Actors' names in place of the name codes of Assistant-led RPG Maker
requests, as Guided shows them.

A run under POLICY compiles a line's ``\\N[n]`` as the English name the
glossary's "actor ID n" rows give actor n, and a ``\\V[n]`` as that of the
actor a Control Variables script (code 122) of the original game sets
variable n to, read from its MV/MZ event data (a VX Ace original keeps its
data in Ruby Marshal, so its ``\\V[n]`` stays a code); a code with no named
actor stays as it is (engine util/actor_names). The request's context keeps
each such line's shown text and codes: the payload shows the names
(requests.shown_sources) and each reply's codes are put back before it is
checked (requests.restored), so receipts and the export hold the game's
codes.

A run freezes the policy in its configuration (KEY), so runs compiled before
it keep the requests they were approved with.
"""

import json
import re
from pathlib import Path, PurePosixPath

from dazedtl.freshness import Digests

from . import originals

KEY = "actorNames"
POLICY = "actor-names-v1"
_EVENTS = re.compile(r"Map\d+\.json|CommonEvents\.json")
_VARIABLE_CODE = re.compile(r"\\v\[\d+\]", re.IGNORECASE)
# Each game's variables set to actors' names, by its original's ID.
_VARIABLES = Digests(limit=8)


def _scanned(snapshot):
    """Variable ID -> actor ID from the code-122 actor-name scripts of every
    MV/MZ data folder the original holds."""
    from util.actor_names import scan_variable_actors

    by_folder = {}
    for name in snapshot.files:
        path = PurePosixPath(name)
        by_folder.setdefault(path.parent, []).append(path)
    mapping = {}
    for _folder, paths in sorted(by_folder.items()):
        if not any(path.name == "System.json" for path in paths):
            continue
        events = sorted(
            path.as_posix() for path in paths if _EVENTS.fullmatch(path.name)
        )
        with snapshot.materialized(events) as root:
            for name in events:
                try:
                    data = json.loads(
                        (Path(root) / name).read_text(encoding="utf-8-sig")
                    )
                except OSError, ValueError:
                    continue
                scan_variable_actors(data, mapping)
    return mapping


def variables(engine, workspace, project_id, root, configuration, sources):
    """None unless the run froze POLICY for an RPG Maker game; else each
    variable a code-122 script of its original sets to an actor's name, with
    that actor, read only when one of *sources* (unit ID to source text)
    shows a variable."""
    if configuration.get(KEY) != POLICY:
        return None
    engine_name = engine.detect(root)
    if engine_name not in {"MVMZ", "ACE"}:
        return None
    if engine_name == "ACE" or not any(
        _VARIABLE_CODE.search(text) for text in sources.values()
    ):
        return {}
    current = originals.prepared_id(workspace, project_id, Path(root))
    if current is None:
        return {}
    key = str(Path(root))
    mapping = _VARIABLES.get(key, current)
    if mapping is None:
        snapshot = originals.prepared(workspace, project_id, Path(root))
        if snapshot is None:
            return {}
        mapping = _scanned(snapshot)
        _VARIABLES.put(key, current, mapping)
    return mapping
