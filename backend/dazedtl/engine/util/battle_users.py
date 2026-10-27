"""Who uses each RPG Maker skill in battle, for the note its battle messages
carry in both methods: Guided's MV/MZ parser and Assistant-led's requests.

The model reads a message like "%1 casts..." with the battler's name in
place, so naming the skill's users lets it choose the subject's pronouns,
and their names bring their glossary entries, such as a character's gender.
Both read MV/MZ-shaped data through a reader of their own: Guided its run's
files, Assistant-led the original game's.
"""

import re
from collections.abc import Callable, Iterable
from typing import Any

# Enemies a note names before it only counts the rest.
NOTE_ENEMIES = 6
_ADD_ACTOR = re.compile(r"addActor\s*\(\s*(\d+)\s*\)")

# Each skill's (actors, enemies) by skill ID, and the party's one actor.
Users = tuple[dict[int, tuple[list[str], list[str]]], str | None]


def _event_commands(value, codes: frozenset[int]):
    """Every event command with one of these codes in a map, common-event or
    troop file."""
    if isinstance(value, dict):
        if value.get("code") in codes:
            yield value
        for child in value.values():
            yield from _event_commands(child, codes)
    elif isinstance(value, list):
        for child in value:
            yield from _event_commands(child, codes)


def _field(entry: dict, field: str) -> str:
    value = entry.get(field)
    return "" if value is None else str(value)


def battle_users(
    read: Callable[[str], Any],
    maps: Iterable[str],
    text: Callable[[dict, str], str] = _field,
) -> Users:
    """Each skill's actors and enemies by their source names, and the party's
    actor when the game shows the party can only ever hold that one.

    read(name) is a data file, such as "Actors.json", as parsed JSON or None,
    maps the game's Map files by name, and text(entry, field) a database
    entry's source text for a field.

    An actor learns a skill from its starting class's learnings, an Add Skill
    trait on the actor or that class, or a Change Skill command naming it; an
    enemy uses the skills its action patterns list. A skill granted any other
    way, such as by a plugin, has no users here. The party holds System's
    starting members and every actor a Change Party Member command or an
    addActor script adds; a script that names its actor any other way leaves
    the party unknown.
    """

    def entries(name):
        data = read(name)
        if not isinstance(data, list):
            return []
        return [entry for entry in data if isinstance(entry, dict)]

    def added_skills(entry):
        return {
            trait.get("dataId")
            for trait in entry.get("traits") or []
            if isinstance(trait, dict) and trait.get("code") == 43
        }

    classes = {entry.get("id"): entry for entry in entries("Classes.json")}
    actor_names: dict[int, str] = {}
    actor_ids: dict[int, set[int]] = {}
    for actor in entries("Actors.json"):
        name = text(actor, "name").strip()
        # A player-named actor's slot says nothing about who it is.
        if not name or not isinstance(actor.get("id"), int):
            continue
        actor_names[actor["id"]] = name
        start = classes.get(actor.get("classId")) or {}
        learned = added_skills(actor) | added_skills(start) | {
            learning.get("skillId")
            for learning in start.get("learnings") or []
            if isinstance(learning, dict)
        }
        for skill in learned:
            actor_ids.setdefault(skill, set()).add(actor["id"])
    system = read("System.json")
    party_known = isinstance(system, dict) and isinstance(
        system.get("partyMembers"), list
    )
    party = set(system["partyMembers"]) if party_known else set()
    for name in [*maps, "CommonEvents.json", "Troops.json"]:
        for command in _event_commands(read(name), frozenset({129, 318, 355, 655})):
            parameters = command.get("parameters") or []
            if command["code"] == 318:
                # [fixed actor (0) or variable, actor (0 is the whole
                #  party), learn (0) or forget, skill]
                if (
                    len(parameters) >= 4
                    and parameters[0] == 0
                    and parameters[2] == 0
                    and parameters[1] in actor_names
                ):
                    actor_ids.setdefault(parameters[3], set()).add(parameters[1])
            elif command["code"] == 129:
                # [actor, add (0) or remove, initialize]
                if len(parameters) >= 2 and parameters[1] == 0:
                    party.add(parameters[0])
            else:
                script = " ".join(
                    value for value in parameters if isinstance(value, str)
                )
                added = _ADD_ACTOR.findall(script)
                party.update(int(actor) for actor in added)
                if script.count("addActor") > len(added):
                    party_known = False
    enemy_names: dict[int, list[str]] = {}
    for enemy in entries("Enemies.json"):
        name = text(enemy, "name").strip()
        if not name:
            continue
        for action in enemy.get("actions") or []:
            if isinstance(action, dict):
                users = enemy_names.setdefault(action.get("skillId"), [])
                if name not in users:
                    users.append(name)
    skills = {
        skill: (
            list(
                dict.fromkeys(
                    actor_names[actor] for actor in sorted(actor_ids.get(skill, ()))
                )
            ),
            enemy_names.get(skill, []),
        )
        for skill in set(actor_ids) | set(enemy_names)
        if isinstance(skill, int)
    }
    only = next(iter(party)) if party_known and len(party) == 1 else None
    return skills, actor_names.get(only)


def line_users(
    users: Users, skill, party: bool
) -> tuple[list[str], list[str]]:
    """The actors and enemies a line of this skill's message names; with
    *party*, a party that can only hold one actor counts as that actor."""
    skills, party_actor = users
    actors, enemies = skills.get(skill, ([], []))
    if party and party_actor:
        # Only the party's one actor fights: a skill no enemy uses is that
        # actor's, and other actors never use theirs.
        actors = [party_actor] if party_actor in actors or not enemies else []
    return actors, enemies


def note(actors: list[str], enemies: list[str]) -> str:
    """The note on a line's skill users, such as "actor Arina; enemy Slime"."""
    parts = []
    if actors:
        parts.append(("actor " if len(actors) == 1 else "actors ") + ", ".join(actors))
    if enemies:
        named = ", ".join(enemies[:NOTE_ENEMIES])
        more = len(enemies) - NOTE_ENEMIES
        parts.append(
            ("enemy " if len(enemies) == 1 else "enemies ")
            + named
            + (f" and {more} more" if more > 0 else "")
        )
    return "; ".join(parts)


def glossary_names(actors: list[str], enemies: list[str]) -> list[str]:
    """The names a note names, whose glossary entries join its request."""
    return [*actors, *enemies[:NOTE_ENEMIES]]
