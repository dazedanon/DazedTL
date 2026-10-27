"""The note on who uses a skill, for the Assistant-led units that hold its
battle message, as Guided's MV/MZ parser adds it to the same lines.

The tool derives it from the original game's database (engine
util/battle_users), never from what the assistant wrote: a unit holds a
skill's battle message when its source text covers that message as the
census counts it, by its runs of source-language text, in the original
game's Skills data. A unit covering several skills' messages, as when they
share a text, names every one's users, as Guided names each line's. RPG
Maker MV/MZ only; a VX Ace original keeps its data in Ruby Marshal with its
own field names, which the shared reader does not read.

A run freezes the policy in its configuration (BATTLE_USERS_KEY), so runs
compiled before it keep the requests they were approved with.
"""

import json
import re
from functools import partial
from pathlib import Path, PurePosixPath

from dazedtl.freshness import Digests
from dazedtl.settings import language_pair
from dazedtl.settings.preferences import BATTLE_MESSAGE_USERS_LEVELS

from . import census, originals

# The configuration key of the frozen policy, Guided's plan key for it.
BATTLE_USERS_KEY = "battleMessageUsers"
_DATABASE = {
    name + ".json"
    for name in ("Actors", "Classes", "Enemies", "System", "CommonEvents", "Troops")
}
_MAP = re.compile(r"Map\d+\.json")
_MESSAGE = re.compile(r"(\d+)/message[1-4]")
_SKILLS_KIND = "rpgmaker:database:Skills"
# Each game's (users, skills by message runs) by its original's ID.
_TABLES = Digests(limit=8)


def level(configuration):
    """The battle-message-users level a run froze, 0 for none."""
    return BATTLE_MESSAGE_USERS_LEVELS.get(configuration.get(BATTLE_USERS_KEY), 0)


def _read(folder, name):
    try:
        return json.loads((Path(folder) / name).read_text(encoding="utf-8-sig"))
    except OSError, ValueError:
        return None


def _messages(snapshot, skills, language):
    """The skills whose battle messages hold each tuple of runs in one
    Skills.json of the original, as the census counts its occurrences."""
    with snapshot.materialized([skills]) as root:
        data = _read(root, skills)
    # The census's own reader, so a message is the occurrence it counts.
    rows = census.read_json(skills, json.dumps(data, ensure_ascii=False))
    found = {}
    for entry in census.entries(rows, skills, "tool", language):
        match = _MESSAGE.fullmatch(entry["location"])
        record = (
            data[int(match[1])]
            if match and isinstance(data, list) and int(match[1]) < len(data)
            else None
        )
        if entry["kind"] == _SKILLS_KIND and isinstance(record, dict):
            found.setdefault(tuple(entry["runs"]), []).append(record.get("id"))
    return found


def _table(snapshot, language):
    """Each skill's users and the skills whose battle messages hold each
    tuple of runs, by every MV/MZ data folder the original holds."""
    from util import battle_users

    by_folder = {}
    for name in snapshot.files:
        path = PurePosixPath(name)
        by_folder.setdefault(path.parent, []).append(path)
    users, messages = {}, {}
    for folder, paths in sorted(by_folder.items()):
        if not any(path.name == "Skills.json" for path in paths):
            continue
        found = _messages(snapshot, (folder / "Skills.json").as_posix(), language)
        if not found:
            continue
        maps = sorted(path.name for path in paths if _MAP.fullmatch(path.name))
        database = [path.name for path in paths if path.name in _DATABASE]
        with snapshot.materialized(
            [(folder / name).as_posix() for name in (*database, *maps)]
        ) as root:
            table = battle_users.battle_users(partial(_read, Path(root) / folder), maps)
        users[folder.as_posix()] = table
        messages[folder.as_posix()] = found
    return users, messages


def notes(workspace, project_id, root, configuration, sources):
    """{unit ID: (note, glossary names)} for the units of *sources* (unit ID
    to source text) holding a skill's battle message with known users, under
    the run's frozen policy; {} without it or an original to read."""
    from util import battle_users

    enabled = level(configuration)
    if not enabled:
        return {}
    root = Path(root)
    current = originals.prepared_id(workspace, project_id, root)
    if current is None:
        return {}
    language = language_pair.run_source(configuration)
    key = f"{root}\0{language}"
    table = _TABLES.get(key, current)
    if table is None:
        snapshot = originals.prepared(workspace, project_id, root)
        if snapshot is None:
            return {}
        table = _table(snapshot, language)
        _TABLES.put(key, current, table)
    users, messages = table
    result = {}
    for identity, text in sources.items():
        found = tuple(census.runs(text, language))
        actors, enemies = [], []
        for folder, skills in messages.items():
            for skill in skills.get(found, ()) if found else ():
                named = battle_users.line_users(users[folder], skill, enabled >= 2)
                actors += named[0]
                enemies += named[1]
        actors, enemies = list(dict.fromkeys(actors)), list(dict.fromkeys(enemies))
        if actors or enemies:
            result[identity] = (
                battle_users.note(actors, enemies),
                battle_users.glossary_names(actors, enemies),
            )
    return result


def for_batch(skill_users, sources):
    """The notes of a request's units, by unit ID, and the names whose
    glossary entries join it, from what notes() gave its plan."""
    noted = [identity for identity in sources if identity in skill_users]
    names = [name for identity in noted for name in skill_users[identity][1]]
    return (
        {identity: skill_users[identity][0] for identity in noted},
        list(dict.fromkeys(names)),
    )
