"""RPG Maker VX Ace data to JSON and back, without Ruby.

A port of Sinflower's RV2JSON 1.2.1 (MIT, https://github.com/Sinflower/RV2JSON)
that writes the same ``ace_json`` folder: each data file as pretty-printed
JSON with RV2JSON's keys and order, and each script as an ``.rb`` file.
Updating merges edited JSON back with RV2JSON's rules and writes the data as
Ruby 3.4's Marshal would, so a game reads exactly what RV2JSON would give it.
A few differences keep games working where RV2JSON did not: data files are
found without regard to case, as on Windows, a Change Vehicle BGM command
keeps its BGM object instead of becoming a Hash the game cannot play, and
System.json carries the equipment type names as ``equipTypes`` so they can
be translated.

Usage mirrors RV2JSON: ``python -m util.ace.rv2json -c -d Data -j ace_json``
creates the JSON and ``-u`` updates the data from it.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import struct
import sys
import zlib
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from . import ruby_marshal as rm
from .ruby_marshal import RHash, RObject, RString, RUserDef, Symbol

DATA_FILES = (
    "CommonEvents",
    "System",
    "MapInfos",
    "Actors",
    "Animations",
    "Armors",
    "Classes",
    "Enemies",
    "Items",
    "Skills",
    "States",
    "Tilesets",
    "Troops",
    "Weapons",
)
MAP_FILE = re.compile(r"Map\d\d\d")
# Characters RV2JSON removes from script names before using them as files.
SCRIPT_NAME_UNSAFE = re.compile(rb'[<>:"/\\|?*]')

Log = Callable[[str], None]


class ConversionError(ValueError):
    """The data or JSON cannot be converted; the message says which file."""


# ---------------------------------------------------------------------------
# JSON text, as Ruby's JSON.pretty_generate writes it


class Pairs(list):
    """A JSON object as ordered (key, value) pairs."""


_RUBY_CODECS = {
    "UTF-8": "utf-8",
    "US-ASCII": "ascii",
    "Shift_JIS": "shift_jis",
    "Windows-31J": "cp932",
    "CP932": "cp932",
    "EUC-JP": "euc_jp",
    "Windows-1252": "cp1252",
    "ISO-8859-1": "latin-1",
}


def _codec(encoding: str | None) -> str:
    if encoding is None:
        return "utf-8"
    codec = _RUBY_CODECS.get(encoding, encoding)
    try:
        import codecs

        return codecs.lookup(codec).name
    except LookupError:
        raise ConversionError("Unsupported Ruby string encoding: " + encoding) from None


def text(value: RString) -> str:
    """A Ruby string's text, as Ruby's JSON generator converts it to UTF-8."""
    try:
        return value.data.decode(_codec(value.encoding))
    except UnicodeDecodeError:
        raise ConversionError(
            "A string is not valid " + (value.encoding or "UTF-8") + " text."
        ) from None


def ruby_float_to_s(value: float) -> str:
    """Ruby's Float#to_s, which its JSON generator uses for floats."""
    if math.isnan(value) or math.isinf(value):
        raise ConversionError("NaN and Infinity are not allowed in JSON.")
    digits, decpt, negative = rm.ruby_float_digits(value)
    if value == 0.0:
        digits, decpt = "0", 1
    sign = "-" if negative else ""
    count = len(digits)
    if 0 < decpt < count:
        body = digits[:decpt] + "." + digits[decpt:]
    elif 0 < decpt <= 15:
        body = digits + "0" * (decpt - count) + ".0"
    elif -4 < decpt <= 0:
        body = "0." + "0" * -decpt + digits
    else:
        mantissa = digits[0] + "." + (digits[1:] or "0")
        exponent = decpt - 1
        body = mantissa + "e" + ("+" if exponent >= 0 else "-") + f"{abs(exponent):02d}"
    return sign + body


def generate(value: Any, depth: int = 0) -> str:
    """JSON.pretty_generate for the tree built by ``to_tree``."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return ruby_float_to_s(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    indent = "  " * (depth + 1)
    if isinstance(value, Pairs):
        if not value:
            return "{}"
        items = ",\n".join(
            indent
            + json.dumps(key, ensure_ascii=False)
            + ": "
            + generate(item, depth + 1)
            for key, item in value
        )
        return "{\n" + items + "\n" + "  " * depth + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        items = ",\n".join(indent + generate(item, depth + 1) for item in value)
        return "[\n" + items + "\n" + "  " * depth + "]"
    raise ConversionError("Cannot write " + type(value).__name__ + " as JSON.")


# ---------------------------------------------------------------------------
# Ruby data to the JSON tree, with RV2JSON's to_json for each class


def _key_text(key: Any) -> str:
    if key is None:
        return ""
    if isinstance(key, RString):
        return text(key)
    if isinstance(key, Symbol):
        return key.text
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, float):
        return ruby_float_to_s(key)
    if isinstance(key, int):
        return str(key)
    raise ConversionError("Unsupported Hash key " + type(key).__name__ + ".")


def _clamp(value: float, low: int, high: int) -> float:
    """Ruby's [[low, value].max, high].min. Array#max and #min return the
    first of equal elements, so a value equal to a bound becomes the bound's
    Integer."""
    bounded = value if value > low else low
    return bounded if bounded <= high else high


def table_values(table: RUserDef) -> tuple[int, int, int, list[int]]:
    """A Table's sizes and its unsigned 16-bit data, as RV2JSON reads it."""
    header = [
        int.from_bytes(table.data[i : i + 4], "little")
        if len(table.data) >= i + 4
        else None
        for i in range(0, 20, 4)
    ]
    body = table.data[20:]
    data = [
        int.from_bytes(body[i : i + 2], "little") for i in range(0, len(body) - 1, 2)
    ]
    return header[1], header[2], header[3], data  # type: ignore[return-value]


def _doubles(data: bytes) -> list[float]:
    return [
        rm.ruby_float(item)
        for item in struct.unpack(f"<{len(data) // 8}d", data[: len(data) // 8 * 8])
    ]


def _userdef_tree(value: RUserDef) -> Any:
    if value.cls == "Table":
        xsize, ysize, zsize, data = table_values(value)
        return Pairs(
            [("xsize", xsize), ("ysize", ysize), ("zsize", zsize), ("data", data)]
        )
    if value.cls == "Color":
        red, green, blue, alpha = color_values(value)
        return Pairs([("red", red), ("green", green), ("blue", blue), ("alpha", alpha)])
    if value.cls == "Tone":
        red, green, blue, gray = tone_values(value)
        return Pairs([("red", red), ("green", green), ("blue", blue), ("gray", gray)])
    raise ConversionError("Unsupported user-defined class " + value.cls + ".")


def color_values(value: RUserDef) -> list[float]:
    values = _doubles(value.data)
    return (values + [None] * 4)[:4]  # type: ignore[list-item]


def tone_values(value: RUserDef) -> list[float]:
    values = (_doubles(value.data) + [0.0] * 4)[:4]
    return [
        _clamp(values[0], -255, 255),
        _clamp(values[1], -255, 255),
        _clamp(values[2], -255, 255),
        _clamp(values[3], 0, 255),
    ]


def _fields(*pairs: tuple[str, str]) -> Callable[[RObject], Pairs]:
    """A to_json that writes ``ivar`` values under ``key`` names, in order."""

    def write(obj: RObject) -> Pairs:
        return Pairs((key, to_tree(obj.get(ivar))) for key, ivar in pairs)

    return write


def _drop_item(obj: RObject) -> Pairs:
    kind, data_id, denominator = (
        obj.get("@kind"),
        obj.get("@data_id"),
        obj.get("@denominator"),
    )
    # RV2JSON's own order rule, kept so the JSON matches it.
    if denominator != 1 or (denominator == 1 and kind <= 1 and data_id != 1):
        keys = (("kind", kind), ("dataId", data_id), ("denominator", denominator))
    else:
        keys = (("dataId", data_id), ("denominator", denominator), ("kind", kind))
    return Pairs((key, to_tree(value)) for key, value in keys)


def _state(obj: RObject) -> Pairs:
    out = Pairs(
        [
            ("id", obj.get("@id")),
            ("autoRemovalTiming", obj.get("@auto_removal_timing")),
            ("chanceByDamage", obj.get("@chance_by_damage")),
        ]
    )
    if obj.get("@description") is not None:
        out.append(("description", obj.get("@description")))
    out.extend(
        [
            ("iconIndex", obj.get("@icon_index")),
            ("maxTurns", obj.get("@max_turns")),
            ("message1", obj.get("@message1")),
            ("message2", obj.get("@message2")),
            ("message3", obj.get("@message3")),
            ("message4", obj.get("@message4")),
            ("minTurns", obj.get("@min_turns")),
            ("motion", obj.get("@motion")),
            ("overlay", obj.get("@overlay")),
            ("name", obj.get("@name")),
            ("note", obj.get("@note")),
            ("priority", obj.get("@priority")),
        ]
    )
    if obj.get("@releaseByDamage") is not None:
        out.append(("releaseByDamage", obj.get("@releaseByDamage")))
    out.extend(
        [
            ("removeAtBattleEnd", obj.get("@remove_at_battle_end")),
            ("removeByDamage", obj.get("@remove_by_damage")),
            ("removeByRestriction", obj.get("@remove_by_restriction")),
            ("removeByWalking", obj.get("@remove_by_walking")),
            ("restriction", obj.get("@restriction")),
            ("stepsToRemove", obj.get("@steps_to_remove")),
            ("traits", obj.get("@features")),
        ]
    )
    return Pairs((key, to_tree(value)) for key, value in out)


def _move_command_json(obj: RObject) -> Pairs:
    out = Pairs([("code", to_tree(obj.get("@code")))])
    if _truthy(obj.get("@parameters")):
        out.append(("parameters", to_tree(obj.get("@parameters"))))
    return out


def _encounter(obj: RObject) -> Pairs:
    if not _truthy(obj.get("@troop_id")):
        raise ConversionError("A map encounter has no troop.")
    return _fields(
        ("regionSet", "@region_set"), ("troopId", "@troop_id"), ("weight", "@weight")
    )(obj)


def _frame(obj: RObject) -> Any:
    return to_tree(obj.get("@cell_data"))


def _timing(obj: RObject) -> Pairs:
    out = Pairs()
    if _truthy(obj.get("@conditions")):
        out.append(("conditions", to_tree(obj.get("@conditions"))))
    color = obj.get("@flash_color")
    out.extend(
        [
            (
                "flashColor",
                to_tree(color_values(color) if isinstance(color, RUserDef) else None),
            ),
            ("flashDuration", to_tree(obj.get("@flash_duration"))),
            ("flashScope", to_tree(obj.get("@flash_scope"))),
            ("frame", to_tree(obj.get("@frame"))),
            ("se", to_tree(obj.get("@se"))),
        ]
    )
    return out


def _system(obj: RObject) -> Pairs:
    tone = obj.get("@window_tone")
    out = _fields(
        ("airship", "@airship"),
        ("armorTypes", "@armor_types"),
        ("battleBgm", "@battle_bgm"),
        ("battleback1Name", "@battleback1_name"),
        ("battleback2Name", "@battleback2_name"),
        ("battlerHue", "@battler_hue"),
        ("battlerName", "@battler_name"),
        ("boat", "@boat"),
        ("currencyUnit", "@currency_unit"),
        ("editMapId", "@edit_map_id"),
        ("elements", "@elements"),
        ("gameTitle", "@game_title"),
        ("gameoverMe", "@gameover_me"),
        ("optDisplayTp", "@opt_display_tp"),
        ("optDrawTitle", "@opt_draw_title"),
        ("optExtraExp", "@opt_extra_exp"),
        ("optFloorDeath", "@opt_floor_death"),
        ("optFollowers", "@opt_followers"),
        ("optSlipDeath", "@opt_slip_death"),
        ("optTransparent", "@opt_transparent"),
        ("partyMembers", "@party_members"),
        ("ship", "@ship"),
        ("skillTypes", "@skill_types"),
        ("sounds", "@sounds"),
        ("startMapId", "@start_map_id"),
        ("startX", "@start_x"),
        ("startY", "@start_y"),
        ("switches", "@switches"),
        ("terms", "@terms"),
        ("testBattlers", "@test_battlers"),
        ("testTroopId", "@test_troop_id"),
        ("title1Name", "@title1_name"),
        ("title2Name", "@title2_name"),
        ("titleBgm", "@title_bgm"),
        ("variables", "@variables"),
        ("versionId", "@version_id"),
        ("victoryMe", "@battle_end_me"),
        ("weaponTypes", "@weapon_types"),
    )(obj)
    if not isinstance(tone, RUserDef):
        raise ConversionError("The system window tone is missing.")
    out.append(("windowTone", to_tree(tone_values(tone))))
    # RV2JSON leaves out the equipment type names; MV's key for them lets
    # the translation engine translate them like the other type lists.
    terms = obj.get("@terms")
    etypes = terms.get("@etypes") if isinstance(terms, RObject) else None
    out.insert(
        [key for key, _ in out].index("elements") + 1, ("equipTypes", to_tree(etypes))
    )
    return out


def _map(obj: RObject) -> Pairs:
    out = _fields(
        ("autoplayBgm", "@autoplay_bgm"),
        ("autoplayBgs", "@autoplay_bgs"),
        ("battleback1Name", "@battleback_floor_name"),
        ("battleback2Name", "@battleback_wall_name"),
        ("bgm", "@bgm"),
        ("bgs", "@bgs"),
        ("disableDashing", "@disable_dashing"),
        ("displayName", "@display_name"),
        ("encounterList", "@encounter_list"),
        ("encounterStep", "@encounter_step"),
        ("height", "@height"),
        ("note", "@note"),
        ("parallaxLoopX", "@parallax_loop_x"),
        ("parallaxLoopY", "@parallax_loop_y"),
        ("parallaxName", "@parallax_name"),
        ("parallaxShow", "@parallax_show"),
        ("parallaxSx", "@parallax_sx"),
        ("parallaxSy", "@parallax_sy"),
        ("scrollType", "@scroll_type"),
        ("specifyBattleback", "@specify_battleback"),
        ("tilesetId", "@tileset_id"),
        ("width", "@width"),
    )(obj)
    events = obj.get("@events")
    out.append(
        (
            "events",
            to_tree(
                [value for _key, value in events.pairs]
                if isinstance(events, RHash)
                else None
            ),
        )
    )
    return out


_AUDIO = _fields(
    ("name", "@name"), ("pan", "@pan"), ("pitch", "@pitch"), ("volume", "@volume")
)
_FEATURE = _fields(("code", "@code"), ("dataId", "@data_id"), ("value", "@value"))

SERIALIZERS: dict[str, Callable[[RObject], Any]] = {
    "RPG::AudioFile": _AUDIO,
    "RPG::BGM": _AUDIO,
    "RPG::BGS": _AUDIO,
    "RPG::ME": _AUDIO,
    "RPG::SE": _AUDIO,
    "RPG::BaseItem::Feature": _FEATURE,
    "RPG::Actor": _fields(
        ("id", "@id"),
        ("characterIndex", "@character_index"),
        ("characterName", "@character_name"),
        ("classId", "@class_id"),
        ("equips", "@equips"),
        ("faceIndex", "@face_index"),
        ("faceName", "@face_name"),
        ("traits", "@features"),
        ("initialLevel", "@initial_level"),
        ("maxLevel", "@max_level"),
        ("name", "@name"),
        ("nickname", "@nickname"),
        ("note", "@note"),
        ("profile", "@description"),
    ),
    "RPG::Class": _fields(
        ("id", "@id"),
        ("expParams", "@exp_params"),
        ("traits", "@features"),
        ("learnings", "@learnings"),
        ("name", "@name"),
        ("note", "@note"),
        ("params", "@params"),
    ),
    "RPG::Class::Learning": _fields(
        ("level", "@level"), ("note", "@note"), ("skillId", "@skill_id")
    ),
    "RPG::Item": _fields(
        ("id", "@id"),
        ("animationId", "@animation_id"),
        ("consumable", "@consumable"),
        ("damage", "@damage"),
        ("description", "@description"),
        ("effects", "@effects"),
        ("hitType", "@hit_type"),
        ("iconIndex", "@icon_index"),
        ("itypeId", "@itype_id"),
        ("name", "@name"),
        ("note", "@note"),
        ("occasion", "@occasion"),
        ("price", "@price"),
        ("repeats", "@repeats"),
        ("scope", "@scope"),
        ("speed", "@speed"),
        ("successRate", "@success_rate"),
        ("tpGain", "@tp_gain"),
    ),
    "RPG::Skill": _fields(
        ("id", "@id"),
        ("animationId", "@animation_id"),
        ("damage", "@damage"),
        ("description", "@description"),
        ("effects", "@effects"),
        ("hitType", "@hit_type"),
        ("iconIndex", "@icon_index"),
        ("message1", "@message1"),
        ("message2", "@message2"),
        ("mpCost", "@mp_cost"),
        ("name", "@name"),
        ("note", "@note"),
        ("occasion", "@occasion"),
        ("repeats", "@repeats"),
        ("requiredWtypeId1", "@required_wtype_id1"),
        ("requiredWtypeId2", "@required_wtype_id2"),
        ("scope", "@scope"),
        ("speed", "@speed"),
        ("stypeId", "@stype_id"),
        ("successRate", "@success_rate"),
        ("tpCost", "@tp_cost"),
        ("tpGain", "@tp_gain"),
    ),
    "RPG::UsableItem::Effect": _fields(
        ("code", "@code"),
        ("dataId", "@data_id"),
        ("value1", "@value1"),
        ("value2", "@value2"),
    ),
    "RPG::UsableItem::Damage": _fields(
        ("critical", "@critical"),
        ("elementId", "@element_id"),
        ("formula", "@formula"),
        ("type", "@type"),
        ("variance", "@variance"),
    ),
    "RPG::Weapon": _fields(
        ("id", "@id"),
        ("animationId", "@animation_id"),
        ("description", "@description"),
        ("etypeId", "@etype_id"),
        ("traits", "@features"),
        ("iconIndex", "@icon_index"),
        ("name", "@name"),
        ("note", "@note"),
        ("params", "@params"),
        ("price", "@price"),
        ("wtypeId", "@wtype_id"),
    ),
    "RPG::Armor": _fields(
        ("id", "@id"),
        ("atypeId", "@atype_id"),
        ("description", "@description"),
        ("etypeId", "@etype_id"),
        ("traits", "@features"),
        ("iconIndex", "@icon_index"),
        ("name", "@name"),
        ("note", "@note"),
        ("params", "@params"),
        ("price", "@price"),
    ),
    "RPG::Enemy": _fields(
        ("id", "@id"),
        ("actions", "@actions"),
        ("battlerHue", "@battler_hue"),
        ("battlerName", "@battler_name"),
        ("dropItems", "@drop_items"),
        ("exp", "@exp"),
        ("traits", "@features"),
        ("gold", "@gold"),
        ("name", "@name"),
        ("note", "@note"),
        ("params", "@params"),
    ),
    "RPG::Enemy::DropItem": _drop_item,
    "RPG::Enemy::Action": _fields(
        ("conditionParam1", "@condition_param1"),
        ("conditionParam2", "@condition_param2"),
        ("conditionType", "@condition_type"),
        ("rating", "@rating"),
        ("skillId", "@skill_id"),
    ),
    "RPG::State": _state,
    "RPG::Tileset": _fields(
        ("id", "@id"),
        ("flags", "@flags"),
        ("mode", "@mode"),
        ("name", "@name"),
        ("note", "@note"),
        ("tilesetNames", "@tileset_names"),
    ),
    "RPG::Animation": _fields(
        ("id", "@id"),
        ("animation1Hue", "@animation1_hue"),
        ("animation1Name", "@animation1_name"),
        ("animation2Hue", "@animation2_hue"),
        ("animation2Name", "@animation2_name"),
        ("frames", "@frames"),
        ("name", "@name"),
        ("position", "@position"),
        ("timings", "@timings"),
    ),
    "RPG::Animation::Frame": _frame,
    "RPG::Animation::Timing": _timing,
    "RPG::CommonEvent": _fields(
        ("id", "@id"),
        ("list", "@list"),
        ("name", "@name"),
        ("switchId", "@switch_id"),
        ("trigger", "@trigger"),
    ),
    "RPG::EventCommand": _fields(
        ("code", "@code"), ("indent", "@indent"), ("parameters", "@parameters")
    ),
    "RPG::MoveRoute": _fields(
        ("list", "@list"),
        ("repeat", "@repeat"),
        ("skippable", "@skippable"),
        ("wait", "@wait"),
    ),
    "RPG::MoveCommand": _move_command_json,
    "RPG::Event": _fields(
        ("id", "@id"),
        ("name", "@name"),
        ("note", "@note"),
        ("pages", "@pages"),
        ("x", "@x"),
        ("y", "@y"),
    ),
    "RPG::Event::Page": _fields(
        ("conditions", "@condition"),
        ("directionFix", "@direction_fix"),
        ("image", "@graphic"),
        ("list", "@list"),
        ("moveFrequency", "@move_frequency"),
        ("moveRoute", "@move_route"),
        ("moveSpeed", "@move_speed"),
        ("moveType", "@move_type"),
        ("priorityType", "@priority_type"),
        ("stepAnime", "@step_anime"),
        ("through", "@through"),
        ("trigger", "@trigger"),
        ("walkAnime", "@walk_anime"),
    ),
    "RPG::Event::Page::Graphic": _fields(
        ("tileId", "@tile_id"),
        ("characterName", "@character_name"),
        ("direction", "@direction"),
        ("pattern", "@pattern"),
        ("characterIndex", "@character_index"),
    ),
    "RPG::Event::Page::Condition": _fields(
        ("actorId", "@actor_id"),
        ("actorValid", "@actor_valid"),
        ("itemId", "@item_id"),
        ("itemValid", "@item_valid"),
        ("selfSwitchCh", "@self_switch_ch"),
        ("selfSwitchValid", "@self_switch_valid"),
        ("switch1Id", "@switch1_id"),
        ("switch1Valid", "@switch1_valid"),
        ("switch2Id", "@switch2_id"),
        ("switch2Valid", "@switch2_valid"),
        ("variableId", "@variable_id"),
        ("variableValid", "@variable_valid"),
        ("variableValue", "@variable_value"),
    ),
    "RPG::Troop": _fields(
        ("id", "@id"), ("members", "@members"), ("name", "@name"), ("pages", "@pages")
    ),
    "RPG::Troop::Member": _fields(
        ("enemyId", "@enemy_id"), ("x", "@x"), ("y", "@y"), ("hidden", "@hidden")
    ),
    "RPG::Troop::Page": _fields(
        ("conditions", "@condition"), ("list", "@list"), ("span", "@span")
    ),
    "RPG::Troop::Page::Condition": _fields(
        ("actorHp", "@actor_hp"),
        ("actorId", "@actor_id"),
        ("actorValid", "@actor_valid"),
        ("enemyHp", "@enemy_hp"),
        ("enemyIndex", "@enemy_index"),
        ("enemyValid", "@enemy_valid"),
        ("switchId", "@switch_id"),
        ("switchValid", "@switch_valid"),
        ("turnA", "@turn_a"),
        ("turnB", "@turn_b"),
        ("turnEnding", "@turn_ending"),
        ("turnValid", "@turn_valid"),
    ),
    "RPG::Map": _map,
    "RPG::Map::Encounter": _encounter,
    "RPG::MapInfo": _fields(
        ("id", "@id"),
        ("expanded", "@expanded"),
        ("name", "@name"),
        ("order", "@order"),
        ("parentId", "@parent_id"),
        ("scrollX", "@scroll_x"),
        ("scrollY", "@scroll_y"),
    ),
    "RPG::System": _system,
    "RPG::System::Vehicle": _fields(
        ("bgm", "@bgm"),
        ("characterIndex", "@character_index"),
        ("characterName", "@character_name"),
        ("startMapId", "@start_map_id"),
        ("startX", "@start_x"),
        ("startY", "@start_y"),
    ),
    "RPG::System::Terms": _fields(
        ("basic", "@basic"),
        ("commands", "@commands"),
        ("params", "@params"),
        ("messages", "@messages"),
    ),
    "RPG::System::TestBattler": _fields(
        ("actorId", "@actor_id"), ("equips", "@equips"), ("level", "@level")
    ),
}


def to_tree(value: Any) -> Any:
    """A Ruby value as the JSON tree RV2JSON's to_json would produce."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, RString):
        return text(value)
    if isinstance(value, Symbol):
        return value.text
    if isinstance(value, list):
        return [to_tree(item) for item in value]
    if isinstance(value, RHash):
        return Pairs((_key_text(key), to_tree(item)) for key, item in value.pairs)
    if isinstance(value, RUserDef):
        return _userdef_tree(value)
    if isinstance(value, Pairs):
        return value
    if isinstance(value, RObject):
        write = SERIALIZERS.get(value.cls)
        if write is None:
            raise ConversionError("RV2JSON has no JSON form for " + value.cls + ".")
        return write(value)
    raise ConversionError("Cannot convert " + type(value).__name__ + " to JSON.")


# ---------------------------------------------------------------------------
# JSON back into Ruby data, with RV2JSON's updateFromJson for each class


def _json_index(values: Any, index: int) -> Any:
    """``values[index]`` of a JSON array, or None as Ruby's Array#[] gives."""
    if isinstance(values, list) and -len(values) <= index < len(values):
        return values[index]
    return None


def _truthy(value: Any) -> bool:
    """Ruby truthiness: only nil and false are false."""
    return value is not None and value is not False


def rubify(value: Any) -> Any:
    """A parsed JSON value as Ruby's JSON.parse gives it."""
    if isinstance(value, str):
        return RString.utf8(value)
    if isinstance(value, list):
        return [rubify(item) for item in value]
    if isinstance(value, dict):
        return RHash(
            [
                (rm.hash_key(RString.utf8(key)), rubify(item))
                for key, item in value.items()
            ]
        )
    return value


def encode_like(value: Any, original: Any) -> RString:
    """JSON text in the original string's encoding, as String#encode gives it."""
    if not isinstance(value, str):
        raise ConversionError("A text field in the JSON is not text.")
    if not isinstance(original, RString):
        raise ConversionError("A text field replaced a value that was not text.")
    try:
        return RString(value.encode(_codec(original.encoding)), original.encoding)
    except UnicodeEncodeError:
        raise ConversionError(
            "Text cannot be stored in its field's "
            + (original.encoding or "binary")
            + " encoding: "
            + value[:60]
        ) from None


class _Updater:
    """Merges JSON into loaded data. Choices and move routes carry across
    commands the way RV2JSON's globals do."""

    def __init__(self) -> None:
        self.choices: list[Any] = []
        self.move_route: RObject | None = None
        self.move_index = 0

    # Helpers mirroring RV2JSON's utils.rb

    def assign(self, obj: RObject, ivar: str, json_value: Any) -> None:
        if _truthy(json_value):
            obj.ivars[ivar] = rubify(json_value)

    def assign_text(self, obj: RObject, ivar: str, json_value: Any) -> None:
        if _truthy(json_value):
            obj.ivars[ivar] = encode_like(json_value, obj.get(ivar))

    def list_update(self, items: Any, json_list: Any) -> None:
        if not _truthy(json_list) or not isinstance(items, list):
            return
        for index, item in enumerate(items):
            if index < len(json_list) and _truthy(json_list[index]):
                self.update(item, json_list[index])

    def parameters_update(self, params: list[Any], json_list: Any) -> None:
        for index, item in enumerate(params):
            json_value = _json_index(json_list, index)
            if _responds_to_update(item) and _truthy(json_value):
                self.update(item, json_value)
            elif _truthy(json_value):
                params[index] = (
                    encode_like(json_value, item)
                    if isinstance(item, RString)
                    else rubify(json_value)
                )

    # Class updates

    def update(self, obj: Any, json_value: Any) -> None:
        if isinstance(obj, RUserDef):
            return  # Table, Color and Tone keep their data.
        if not isinstance(obj, RObject):
            raise ConversionError("Cannot update " + type(obj).__name__ + " from JSON.")
        method = _UPDATES.get(obj.cls)
        if method is None:
            raise ConversionError("RV2JSON cannot update " + obj.cls + " from JSON.")
        method(self, obj, json_value)

    def base_item(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@id", j.get("id"))
        self.assign_text(obj, "@name", j.get("name"))
        self.assign(obj, "@icon_index", j.get("iconIndex"))
        self.assign_text(obj, "@description", j.get("description"))
        self.assign_text(obj, "@note", j.get("note"))

    def actor(self, obj: RObject, j: dict) -> None:
        self.base_item(obj, j)
        self.assign(obj, "@character_index", j.get("characterIndex"))
        self.assign_text(obj, "@character_name", j.get("characterName"))
        self.assign(obj, "@class_id", j.get("classId"))
        equips = obj.get("@equips")
        if isinstance(equips, list):
            for index in range(len(equips)):
                value = _json_index(j.get("equips"), index)
                if _truthy(value):
                    equips[index] = rubify(value)
        self.assign(obj, "@face_index", j.get("faceIndex"))
        self.assign_text(obj, "@face_name", j.get("faceName"))
        self.assign(obj, "@initial_level", j.get("initialLevel"))
        self.assign(obj, "@max_level", j.get("maxLevel"))
        self.assign_text(obj, "@nickname", j.get("nickname"))
        self.assign_text(obj, "@description", j.get("profile"))

    def feature(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@code", j.get("code"))
        self.assign(obj, "@data_id", j.get("dataId"))
        self.assign(obj, "@value", j.get("value"))

    def class_(self, obj: RObject, j: dict) -> None:
        self.base_item(obj, j)
        self.assign(obj, "@exp_params", j.get("expParams"))
        self.list_update(obj.get("@learnings"), j.get("learnings"))

    def learning(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@level", j.get("level"))
        self.assign(obj, "@skill_id", j.get("skillId"))
        self.assign_text(obj, "@note", j.get("note"))

    def usable_item(self, obj: RObject, j: dict) -> None:
        self.base_item(obj, j)
        for ivar, key in (
            ("@scope", "scope"),
            ("@occasion", "occasion"),
            ("@speed", "speed"),
            ("@success_rate", "successRate"),
            ("@repeats", "repeats"),
            ("@tp_gain", "tpGain"),
            ("@hit_type", "hitType"),
            ("@animation_id", "animationId"),
        ):
            self.assign(obj, ivar, j.get(key))
        if _truthy(j.get("damage")):
            self.update(obj.get("@damage"), j["damage"])
        self.list_update(obj.get("@effects"), j.get("effects"))

    def item(self, obj: RObject, j: dict) -> None:
        self.usable_item(obj, j)
        self.assign(obj, "@itype_id", j.get("itypeId"))
        self.assign(obj, "@price", j.get("price"))
        self.assign(obj, "@consumable", j.get("consumable"))

    def skill(self, obj: RObject, j: dict) -> None:
        self.usable_item(obj, j)
        self.assign(obj, "@scope", j.get("scope"))
        self.assign(obj, "@stype_id", j.get("stypeId"))
        self.assign(obj, "@mp_cost", j.get("mpCost"))
        self.assign(obj, "@tp_cost", j.get("tpCost"))
        self.assign_text(obj, "@message1", j.get("message1"))
        self.assign_text(obj, "@message2", j.get("message2"))
        self.assign(obj, "@required_wtype_id1", j.get("requiredWtypeId1"))
        self.assign(obj, "@required_wtype_id2", j.get("requiredWtypeId2"))

    def effect(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@code", j.get("code"))
        self.assign(obj, "@data_id", j.get("dataId"))
        self.assign(obj, "@value1", j.get("value1"))
        self.assign(obj, "@value2", j.get("value2"))

    def damage(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@type", j.get("type"))
        self.assign(obj, "@element_id", j.get("elementId"))
        self.assign_text(obj, "@formula", j.get("formula"))
        self.assign(obj, "@variance", j.get("variance"))
        self.assign(obj, "@critical", j.get("critical"))

    def equip_item(self, obj: RObject, j: dict) -> None:
        self.base_item(obj, j)
        self.assign(obj, "@price", j.get("price"))
        self.assign(obj, "@etype_id", j.get("etypeId"))

    def weapon(self, obj: RObject, j: dict) -> None:
        self.equip_item(obj, j)
        self.assign(obj, "@wtype_id", j.get("wtypeId"))
        self.assign(obj, "@animation_id", j.get("animationId"))

    def armor(self, obj: RObject, j: dict) -> None:
        self.equip_item(obj, j)
        self.assign(obj, "@atype_id", j.get("atypeId"))
        self.assign(obj, "@etype_id", j.get("etypeId"))

    def enemy(self, obj: RObject, j: dict) -> None:
        self.base_item(obj, j)
        self.assign_text(obj, "@battler_name", j.get("battlerName"))
        self.assign(obj, "@battler_hue", j.get("battlerHue"))
        params = obj.get("@params")
        if isinstance(params, list):
            for index in range(len(params)):
                value = _json_index(j.get("params"), index)
                if _truthy(value):
                    params[index] = rubify(value)
        self.assign(obj, "@exp", j.get("exp"))
        self.assign(obj, "@gold", j.get("gold"))
        self.list_update(obj.get("@drop_items"), j.get("dropItems"))
        self.list_update(obj.get("@actions"), j.get("actions"))

    def drop_item(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@kind", j.get("kind"))
        self.assign(obj, "@data_id", j.get("dataId"))
        self.assign(obj, "@denominator", j.get("denominator"))

    def action(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@skill_id", j.get("skillId"))
        self.assign(obj, "@condition_type", j.get("conditionType"))
        self.assign(obj, "@condition_param1", j.get("conditionParam1"))
        self.assign(obj, "@condition_param2", j.get("conditionParam2"))
        self.assign(obj, "@rating", j.get("rating"))

    def state(self, obj: RObject, j: dict) -> None:
        self.base_item(obj, j)
        for ivar, key in (
            ("@restriction", "restriction"),
            ("@priority", "priority"),
            ("@remove_at_battle_end", "removeAtBattleEnd"),
            ("@remove_by_restriction", "removeByRestriction"),
            ("@auto_removal_timing", "autoRemovalTiming"),
            ("@min_turns", "minTurns"),
            ("@max_turns", "maxTurns"),
            ("@remove_by_damage", "removeByDamage"),
            ("@chance_by_damage", "chanceByDamage"),
            ("@remove_by_walking", "removeByWalking"),
            ("@steps_to_remove", "stepsToRemove"),
        ):
            self.assign(obj, ivar, j.get(key))
        for number in "1234":
            self.assign_text(obj, "@message" + number, j.get("message" + number))

    def no_update(self, obj: RObject, j: Any) -> None:
        return

    def audio(self, obj: RObject, j: dict) -> None:
        self.assign_text(obj, "@name", j.get("name"))
        self.assign(obj, "@pitch", j.get("pitch"))
        self.assign(obj, "@volume", j.get("volume"))

    def common_event(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@id", j.get("id"))
        self.assign_text(obj, "@name", j.get("name"))
        self.assign(obj, "@trigger", j.get("trigger"))
        self.assign(obj, "@switch_id", j.get("switchId"))
        obj.ivars["@list"] = self.commands(j.get("list"))

    def commands(self, json_list: Any) -> list[RObject]:
        if not isinstance(json_list, list):
            raise ConversionError("An event's command list is missing from the JSON.")
        return [self.command(item) for item in json_list]

    def command(self, j: dict) -> RObject:
        """RV2JSON's EventCommand.new followed by makeFromJson."""
        command = RObject(
            "RPG::EventCommand", {"@indent": 0, "@code": 0, "@parameters": []}
        )
        self.assign(command, "@code", j.get("code"))
        self.assign(command, "@indent", j.get("indent"))
        params = command.ivars["@parameters"]
        code = command.ivars["@code"]
        if not _truthy(j.get("parameters")):
            return command
        for index, raw in enumerate(j["parameters"]):
            value = rubify(raw)
            if code == 102:
                if isinstance(value, list):
                    self.choices.append(value)
                params.append(value)
            elif code in (132, 140, 241):
                params.append(
                    _new_audio("RPG::BGM", raw) if isinstance(raw, dict) else value
                )
            elif code in (133, 249):
                params.append(
                    _new_audio("RPG::ME", raw) if isinstance(raw, dict) else value
                )
            elif code == 245:
                params.append(
                    _new_audio("RPG::BGS", raw) if isinstance(raw, dict) else value
                )
            elif code == 250:
                params.append(
                    _new_audio("RPG::SE", raw) if isinstance(raw, dict) else value
                )
            elif code in (138, 223, 234):
                params.append(_new_tone(raw) if isinstance(raw, dict) else value)
            elif code == 224:
                params.append(_new_color(raw) if isinstance(raw, dict) else value)
            elif code == 205:
                if isinstance(raw, dict) and _truthy(raw.get("list")):
                    self.move_route = _new_move_route(raw)
                    self.move_index = 0
                    params.append(self.move_route)
                else:
                    params.append(value)
            elif code == 236:
                params.append(_to_sym(value) if index == 0 else value)
            elif code == 402:
                # The choice's text becomes the same object as in its menu.
                current = self.choices[-1] if self.choices else None
                if isinstance(current, list):
                    match = next(
                        (item for item in current if _ruby_equal(item, value)),
                        None,
                    )
                    if match is not None:
                        value = match
                params.append(value)
            elif code == 404:
                if self.choices:
                    self.choices.pop()
                params.append(value)
            elif code == 505:
                if isinstance(raw, dict) and _truthy(raw.get("code")):
                    if self.move_route is None:
                        raise ConversionError(
                            "A move command appears before its move route."
                        )
                    route = self.move_route.ivars["@list"]
                    params.append(
                        route[self.move_index] if self.move_index < len(route) else None
                    )
                    self.move_index += 1
                else:
                    params.append(value)
            else:
                params.append(value)
        return command

    def move_route_update(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@repeat", j.get("repeat"))
        self.assign(obj, "@skippable", j.get("skippable"))
        self.assign(obj, "@wait", j.get("wait"))
        self.list_update(obj.get("@list"), j.get("list"))

    def move_command_update(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@code", j.get("code"))
        params = obj.get("@parameters")
        json_params = j.get("parameters")
        if isinstance(params, list):
            self.parameters_update(
                params, json_params if isinstance(json_params, list) else []
            )

    def event(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@id", j.get("id"))
        self.assign_text(obj, "@name", j.get("name"))
        self.assign(obj, "@x", j.get("x"))
        self.assign(obj, "@y", j.get("y"))
        self.list_update(obj.get("@pages"), j.get("pages"))

    def page(self, obj: RObject, j: dict) -> None:
        if _truthy(j.get("conditions")):
            self.update(obj.get("@condition"), j["conditions"])
        if _truthy(j.get("image")):
            self.update(obj.get("@graphic"), j["image"])
        self.assign(obj, "@move_type", j.get("moveType"))
        self.assign(obj, "@move_speed", j.get("moveSpeed"))
        self.assign(obj, "@move_frequency", j.get("moveFrequency"))
        if _truthy(j.get("moveRoute")):
            self.update(obj.get("@move_route"), j["moveRoute"])
        for ivar, key in (
            ("@walk_anime", "walkAnime"),
            ("@step_anime", "stepAnime"),
            ("@direction_fix", "directionFix"),
            ("@through", "through"),
            ("@priority_type", "priorityType"),
            ("@trigger", "trigger"),
        ):
            self.assign(obj, ivar, j.get(key))
        obj.ivars["@list"] = self.commands(j.get("list"))

    def graphic(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@tile_id", j.get("tileId"))
        self.assign_text(obj, "@character_name", j.get("characterName"))
        self.assign(obj, "@character_index", j.get("characterIndex"))
        self.assign(obj, "@direction", j.get("direction"))
        self.assign(obj, "@pattern", j.get("pattern"))

    def event_condition(self, obj: RObject, j: dict) -> None:
        for ivar, key in (
            ("@switch1_valid", "switch1Valid"),
            ("@switch2_valid", "switch2Valid"),
            ("@variable_valid", "variableValid"),
            ("@self_switch_valid", "selfSwitchValid"),
            ("@item_valid", "itemValid"),
            ("@actor_valid", "actorValid"),
            ("@switch1_id", "switch1Id"),
            ("@switch2_id", "switch2Id"),
            ("@variable_id", "variableId"),
            ("@variable_value", "variableValue"),
        ):
            self.assign(obj, ivar, j.get(key))
        self.assign_text(obj, "@self_switch_ch", j.get("selfSwitchCh"))
        self.assign(obj, "@item_id", j.get("itemId"))
        self.assign(obj, "@actor_id", j.get("actorId"))

    def troop(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@id", j.get("id"))
        self.assign_text(obj, "@name", j.get("name"))
        self.list_update(obj.get("@members"), j.get("members"))
        self.list_update(obj.get("@pages"), j.get("pages"))

    def member(self, obj: RObject, j: dict) -> None:
        for ivar, key in (
            ("@enemy_id", "enemyId"),
            ("@x", "x"),
            ("@y", "y"),
            ("@hidden", "hidden"),
        ):
            self.assign(obj, ivar, j.get(key))

    def troop_page(self, obj: RObject, j: dict) -> None:
        if _truthy(j.get("conditions")):
            self.update(obj.get("@condition"), j["conditions"])
        self.assign(obj, "@span", j.get("span"))
        obj.ivars["@list"] = self.commands(j.get("list"))

    def troop_condition(self, obj: RObject, j: dict) -> None:
        for ivar, key in (
            ("@turn_ending", "turnEnding"),
            ("@turn_valid", "turnValid"),
            ("@enemy_valid", "enemyValid"),
            ("@actor_valid", "actorValid"),
            ("@switch_valid", "switchValid"),
            ("@turn_a", "turnA"),
            ("@turn_b", "turnB"),
            ("@enemy_index", "enemyIndex"),
            ("@enemy_hp", "enemyHp"),
            ("@actor_id", "actorId"),
            ("@actor_hp", "actorHp"),
            ("@switch_id", "switchId"),
        ):
            self.assign(obj, ivar, j.get(key))

    def map(self, obj: RObject, j: dict) -> None:
        self.assign_text(obj, "@display_name", j.get("displayName"))
        self.assign(obj, "@tileset_id", j.get("tilesetId"))
        self.assign(obj, "@width", j.get("width"))
        self.assign(obj, "@height", j.get("height"))
        self.assign(obj, "@scroll_type", j.get("scrollType"))
        self.assign(obj, "@specify_battleback", j.get("specifyBattleback"))
        self.assign_text(obj, "@battleback_floor_name", j.get("battleback1Name"))
        self.assign_text(obj, "@battleback_wall_name", j.get("battleback2Name"))
        self.assign(obj, "@autoplay_bgm", j.get("autoplayBgm"))
        if _truthy(j.get("bgm")):
            self.update(obj.get("@bgm"), j["bgm"])
        self.assign(obj, "@autoplay_bgs", j.get("autoplayBgs"))
        if _truthy(j.get("bgs")):
            self.update(obj.get("@bgs"), j["bgs"])
        self.assign(obj, "@disable_dashing", j.get("disableDashing"))
        self.assign(obj, "@encounter_step", j.get("encounterStep"))
        self.assign_text(obj, "@parallax_name", j.get("parallaxName"))
        self.assign(obj, "@parallax_loop_x", j.get("parallaxLoopX"))
        self.assign(obj, "@parallax_loop_y", j.get("parallaxLoopY"))
        self.assign(obj, "@parallax_sx", j.get("parallaxSx"))
        self.assign(obj, "@parallax_sy", j.get("parallaxSy"))
        self.assign(obj, "@parallax_show", j.get("parallaxShow"))
        self.assign_text(obj, "@note", j.get("note"))
        events = obj.get("@events")
        json_events = j.get("events")
        if isinstance(events, RHash):
            for key, event in events.pairs:
                match = next(
                    (
                        item
                        for item in (json_events or [])
                        if isinstance(item, dict) and item.get("id") == key
                    ),
                    None,
                )
                if _truthy(match):
                    self.update(event, match)

    def map_info(self, obj: RObject, j: dict) -> None:
        self.assign_text(obj, "@name", j.get("name"))
        self.assign(obj, "@id", j.get("id"))
        self.assign(obj, "@parent_id", j.get("parentId"))
        self.assign(obj, "@order", j.get("order"))
        self.assign(obj, "@expanded", j.get("expanded"))
        self.assign(obj, "@scroll_x", j.get("scrollX"))
        self.assign(obj, "@scroll_y", j.get("scrollY"))

    def encounter(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@troop_id", j.get("troopId"))
        self.assign(obj, "@weight", j.get("weight"))
        self.assign(obj, "@region_set", j.get("regionSet"))

    def system(self, obj: RObject, j: dict) -> None:
        self.assign_text(obj, "@game_title", j.get("gameTitle"))
        self.assign(obj, "@version_id", j.get("versionId"))
        self.assign(obj, "@party_members", j.get("partyMembers"))
        self.assign_text(obj, "@currency_unit", j.get("currencyUnit"))
        for ivar, key in (
            ("@elements", "elements"),
            ("@skill_types", "skillTypes"),
            ("@weapon_types", "weaponTypes"),
            ("@armor_types", "armorTypes"),
            ("@switches", "switches"),
            ("@variables", "variables"),
        ):
            self.assign(obj, ivar, j.get(key))
        for ivar, key in (
            ("@boat", "boat"),
            ("@ship", "ship"),
            ("@airship", "airship"),
        ):
            if _truthy(j.get(key)):
                self.update(obj.get(ivar), j[key])
        self.assign_text(obj, "@title1_name", j.get("title1Name"))
        self.assign_text(obj, "@title2_name", j.get("title2Name"))
        for ivar, key in (
            ("@opt_draw_title", "optDrawTitle"),
            ("@opt_use_midi", "optUseMidi"),
            ("@opt_transparent", "optTransparent"),
            ("@opt_followers", "optFollowers"),
            ("@opt_slip_death", "optSlipDeath"),
            ("@opt_floor_death", "optFloorDeath"),
            ("@opt_display_tp", "optDisplayTp"),
            ("@opt_extra_exp", "optExtraExp"),
        ):
            self.assign(obj, ivar, j.get(key))
        for ivar, key in (
            ("@title_bgm", "titleBgm"),
            ("@battle_bgm", "battleBgm"),
            ("@battle_end_me", "victoryMe"),
            ("@gameover_me", "gameoverMe"),
        ):
            if _truthy(j.get(key)):
                self.update(obj.get(ivar), j[key])
        self.list_update(obj.get("@sounds"), j.get("sounds"))
        self.list_update(obj.get("@test_battlers"), j.get("testBattlers"))
        self.assign(obj, "@test_troop_id", j.get("testTroopId"))
        self.assign(obj, "@start_map_id", j.get("startMapId"))
        self.assign(obj, "@start_x", j.get("startX"))
        self.assign(obj, "@start_y", j.get("startY"))
        if _truthy(j.get("terms")):
            self.update(obj.get("@terms"), j["terms"])
        terms = obj.get("@terms")
        if isinstance(terms, RObject):
            self.assign(terms, "@etypes", j.get("equipTypes"))
        self.assign_text(obj, "@battleback1_name", j.get("battleback1Name"))
        self.assign_text(obj, "@battleback2_name", j.get("battleback2Name"))
        self.assign_text(obj, "@battler_name", j.get("battlerName"))
        self.assign(obj, "@battler_hue", j.get("battlerHue"))
        self.assign(obj, "@edit_map_id", j.get("editMapId"))

    def vehicle(self, obj: RObject, j: dict) -> None:
        self.assign_text(obj, "@character_name", j.get("characterName"))
        self.assign(obj, "@character_index", j.get("characterIndex"))
        if _truthy(j.get("bgm")):
            self.update(obj.get("@bgm"), j["bgm"])
        self.assign(obj, "@start_map_id", j.get("startMapId"))
        self.assign(obj, "@start_x", j.get("startX"))
        self.assign(obj, "@start_y", j.get("startY"))

    def terms(self, obj: RObject, j: dict) -> None:
        for key in ("basic", "params", "etypes", "commands"):
            self.assign(obj, "@" + key, j.get(key))

    def test_battler(self, obj: RObject, j: dict) -> None:
        self.assign(obj, "@actor_id", j.get("actorId"))
        self.assign(obj, "@level", j.get("level"))
        self.assign(obj, "@equips", j.get("equips"))


_UPDATES: dict[str, Callable[[_Updater, RObject, Any], None]] = {
    "RPG::AudioFile": _Updater.audio,
    "RPG::BGM": _Updater.audio,
    "RPG::BGS": _Updater.audio,
    "RPG::ME": _Updater.audio,
    "RPG::SE": _Updater.audio,
    "RPG::BaseItem": _Updater.base_item,
    "RPG::BaseItem::Feature": _Updater.feature,
    "RPG::Actor": _Updater.actor,
    "RPG::Class": _Updater.class_,
    "RPG::Class::Learning": _Updater.learning,
    "RPG::UsableItem": _Updater.usable_item,
    "RPG::Item": _Updater.item,
    "RPG::Skill": _Updater.skill,
    "RPG::UsableItem::Effect": _Updater.effect,
    "RPG::UsableItem::Damage": _Updater.damage,
    "RPG::EquipItem": _Updater.equip_item,
    "RPG::Weapon": _Updater.weapon,
    "RPG::Armor": _Updater.armor,
    "RPG::Enemy": _Updater.enemy,
    "RPG::Enemy::DropItem": _Updater.drop_item,
    "RPG::Enemy::Action": _Updater.action,
    "RPG::State": _Updater.state,
    "RPG::Tileset": _Updater.no_update,
    "RPG::Animation": _Updater.no_update,
    "RPG::CommonEvent": _Updater.common_event,
    "RPG::MoveRoute": _Updater.move_route_update,
    "RPG::MoveCommand": _Updater.move_command_update,
    "RPG::Event": _Updater.event,
    "RPG::Event::Page": _Updater.page,
    "RPG::Event::Page::Graphic": _Updater.graphic,
    "RPG::Event::Page::Condition": _Updater.event_condition,
    "RPG::Troop": _Updater.troop,
    "RPG::Troop::Member": _Updater.member,
    "RPG::Troop::Page": _Updater.troop_page,
    "RPG::Troop::Page::Condition": _Updater.troop_condition,
    "RPG::Map": _Updater.map,
    "RPG::Map::Encounter": _Updater.encounter,
    "RPG::MapInfo": _Updater.map_info,
    "RPG::System": _Updater.system,
    "RPG::System::Vehicle": _Updater.vehicle,
    "RPG::System::Terms": _Updater.terms,
    "RPG::System::TestBattler": _Updater.test_battler,
}


def _responds_to_update(value: Any) -> bool:
    """Whether RV2JSON's class for this value defines updateFromJson."""
    if isinstance(value, RUserDef):
        return value.cls in ("Table", "Color", "Tone")
    return isinstance(value, RObject) and value.cls in _UPDATES


def _ruby_equal(left: Any, right: Any) -> bool:
    if isinstance(left, RString) or isinstance(right, RString):
        return isinstance(left, RString) and left.same_text(right)
    if isinstance(left, (bool, type(None))) or isinstance(right, (bool, type(None))):
        return left is right
    return type(left) is type(right) and left == right


def _to_sym(value: Any) -> Any:
    if isinstance(value, RString):
        return Symbol(value.data, not value.data.isascii())
    if isinstance(value, Symbol):
        return value
    raise ConversionError("A weather command's type is not text.")


def _new_audio(cls: str, j: dict) -> RObject:
    """RPG::<cls>.new(name, pitch, volume): SE sets its fields in its own order."""
    name, pitch, volume = rubify(j.get("name")), j.get("pitch"), j.get("volume")
    if cls == "RPG::SE":
        ivars = {"@name": name, "@pitch": pitch, "@volume": volume}
    else:
        ivars = {"@name": name, "@volume": volume, "@pitch": pitch}
    return RObject(cls, ivars)


def _numbers(j: dict, keys: tuple[str, ...], what: str) -> list[float]:
    values = [j.get(key) for key in keys]
    if any(
        not isinstance(item, (int, float)) or isinstance(item, bool) for item in values
    ):
        raise ConversionError(what + " needs " + ", ".join(keys) + " values.")
    # Packing writes doubles, so integers become the same floats Ruby packs.
    return [float(item) for item in values]  # type: ignore[arg-type]


def _new_tone(j: dict) -> RUserDef:
    red, green, blue, gray = _numbers(j, ("red", "green", "blue", "gray"), "A tone")
    return RUserDef("Tone", rm.tone_bytes(red, green, blue, gray))


def _new_color(j: dict) -> RUserDef:
    red, green, blue, alpha = _numbers(j, ("red", "green", "blue", "alpha"), "A color")
    return RUserDef("Color", rm.color_bytes(red, green, blue, alpha))


def _new_move_route(j: dict) -> RObject:
    """RPG::MoveRoute.new followed by initFromJson."""
    route = RObject(
        "RPG::MoveRoute",
        {"@repeat": False, "@skippable": False, "@wait": False, "@list": []},
    )
    for key in ("repeat", "skippable", "wait"):
        if _truthy(j.get(key)):
            route.ivars["@" + key] = rubify(j[key])
    if _truthy(j.get("list")):
        route.ivars["@list"] = [_new_move_command(item) for item in j["list"]]
    return route


def _new_move_command(j: dict) -> RObject:
    """RPG::MoveCommand.new followed by initFromJson."""
    command = RObject("RPG::MoveCommand", {"@code": 0, "@parameters": []})
    if _truthy(j.get("code")):
        command.ivars["@code"] = j["code"]
    params = j.get("parameters")
    if command.ivars["@code"] == 44 and _truthy(params):
        sound = _json_index(params, 0)
        if not isinstance(sound, dict):
            raise ConversionError("A move route's sound command has no sound.")
        command.ivars["@parameters"] = [_new_audio("RPG::SE", sound)]
    elif _truthy(params):
        command.ivars["@parameters"] = rubify(params)
    return command


# ---------------------------------------------------------------------------
# Files


def data_dir(root: Path, name: str | None = None) -> Path:
    """The game's data folder, found without regard to case."""
    if name:
        path = Path(name)
        path = path if path.is_absolute() else root / path
        if path.is_dir():
            return path
    for candidate in ("Data", "data"):
        if (root / candidate).is_dir():
            return root / candidate
    for entry in root.iterdir() if root.is_dir() else ():
        if entry.is_dir() and entry.name.lower() == "data":
            return entry
    raise ConversionError("The game's Data folder was not found.")


def data_files(folder: Path) -> list[str]:
    """RV2JSON's data files: the standard ones and every MapNNN file."""
    names: list[str] = list(DATA_FILES)
    for entry in os.listdir(folder):
        if MAP_FILE.search(entry):
            names.append(entry.rsplit(".", 1)[0] if "." in entry[1:] else entry)
    return names


def data_path(folder: Path, name: str) -> Path:
    """``name``.rvdata2 in the data folder, matched without regard to case as
    on Windows, where RV2JSON and the game itself both find it."""
    path = folder / (name + ".rvdata2")
    if path.exists():
        return path
    wanted = path.name.lower()
    for entry in os.listdir(folder):
        if entry.lower() == wanted:
            return folder / entry
    return path


def load_data(path: Path) -> Any:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        return rm.load(path.read_bytes())
    except rm.MarshalError as exc:
        raise ConversionError(path.name + ": " + str(exc)) from None


def _script_file(scripts: Path, script: list) -> Path:
    index, name = script[0], script[1]
    if isinstance(name, RString):
        name.data = SCRIPT_NAME_UNSAFE.sub(b"", name.data)
    return scripts / f"{_interpolated(index)}_{_interpolated(name)}.rb"


def _interpolated(value: Any) -> str:
    """A value as Ruby's string interpolation writes it."""
    if isinstance(value, RString):
        return value.data.decode("utf-8", "surrogateescape")
    if isinstance(value, Symbol):
        return value.text
    if value is None:
        return ""
    return str(value)


def create(
    root: Path, *, data: str | None = None, json_dir: str = "ace_json", log: Log = print
) -> Path:
    """Writes the JSON folder from the data, as ``RV2JSON -c`` does."""
    folder = data_dir(root, data)
    out = root / json_dir
    out.mkdir(parents=True, exist_ok=True)
    for name in data_files(folder):
        path = data_path(folder, name)
        value = load_data(path)
        if value is None:
            log("Data file " + name + " does not exist, skipping ...")
        try:
            text = generate(to_tree(value))
        except ConversionError as exc:
            raise ConversionError(path.name + ": " + str(exc)) from None
        (out / (name + ".json")).write_text(text, encoding="utf-8", newline="\n")
    scripts = load_data(data_path(folder, "Scripts"))
    if isinstance(scripts, list):
        target = out / "scripts"
        target.mkdir(exist_ok=True)
        count = 0
        for script in scripts:
            if not (
                isinstance(script, list)
                and len(script) >= 3
                and isinstance(script[2], RString)
            ):
                continue
            _script_file(target, script).write_bytes(zlib.decompress(script[2].data))
            count += 1
        log(f"Dumping of {count} scripts done")
    return out


def _backup(path: Path, backups: Path, log: Log) -> None:
    if not path.is_file():
        return
    backups.mkdir(exist_ok=True)
    target = backups / path.name
    if not target.exists():
        shutil.copy2(path, target)
        log("Created backup for " + path.name)


def update(
    root: Path,
    *,
    data: str | None = None,
    json_dir: str = "ace_json",
    out: str | None = None,
    skip_backup: bool = False,
    log: Log = print,
) -> list[Path]:
    """Writes the data from the JSON folder, as ``RV2JSON -u`` does.

    Without ``out`` the data is updated in place, and each replaced file is
    first copied to ``backups`` inside the data folder unless a copy exists.
    """
    folder = data_dir(root, data)
    source = root / json_dir
    if not source.is_dir():
        raise ConversionError("The " + json_dir + " folder was not found.")
    target = Path(out) if out else folder
    target = target if target.is_absolute() else root / target
    in_place = target.resolve() == folder.resolve()
    target.mkdir(parents=True, exist_ok=True)
    updater = _Updater()
    written = []
    for name in data_files(folder):
        path = data_path(folder, name)
        if in_place and not skip_backup:
            _backup(path, target / "backups", log)
        json_path = source / (name + ".json")
        if not json_path.is_file():
            continue
        value = load_data(path)
        if value is None:
            log("Data file " + name + " does not exist, skipping ...")
            continue
        try:
            edited = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ConversionError(
                f"{json_path.name} is not valid JSON ({exc})."
            ) from None
        try:
            update_value(updater, value, edited)
        except ConversionError as exc:
            raise ConversionError(json_path.name + ": " + str(exc)) from None
        except (TypeError, AttributeError, IndexError, KeyError) as exc:
            raise ConversionError(
                f"{json_path.name} does not match the data ({exc})."
            ) from None
        # The file's own name, so an in-place update replaces it.
        output = target / path.name
        output.write_bytes(rm.dump(value))
        written.append(output)
    written.extend(
        _update_scripts(
            folder, source / "scripts", target, in_place and not skip_backup, log
        )
    )
    return written


def update_value(updater: _Updater, value: Any, json_value: Any) -> None:
    """RV2JSON's updateDataFromJson for one file's loaded data."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(json_value, list) or index >= len(json_value):
                continue
            if _truthy(json_value[index]) and _truthy(item):
                updater.update(item, json_value[index])
    elif isinstance(value, RHash):
        # RV2JSON looks JSON objects up by the data's own keys; for MapInfos
        # those are integers, which never match the JSON's string keys, so
        # map infos keep their data, as with RV2JSON.
        for key, item in value.pairs:
            if isinstance(key, RString) and isinstance(json_value, dict):
                match = json_value.get(text(key))
                if _truthy(match) and _truthy(item):
                    updater.update(item, match)
    else:
        updater.update(value, json_value)


def _update_scripts(
    folder: Path, dump_dir: Path, target: Path, backup: bool, log: Log
) -> list[Path]:
    script_file = data_path(folder, "Scripts")
    if not dump_dir.is_dir():
        log(
            "WARNING: Unable to update scripts. Directory "
            + str(dump_dir)
            + " does not exist."
        )
        return []
    scripts = load_data(script_file)
    if not isinstance(scripts, list):
        return []
    if backup:
        _backup(script_file, target / "backups", log)
    count = 0
    for script in scripts:
        if not (isinstance(script, list) and len(script) >= 3):
            continue
        path = _script_file(dump_dir, script)
        if path.is_file():
            code = path.read_bytes()
            # Windows RV2JSON writes in text mode, doubling CRs; reading in
            # text mode undoes that, so do the same here.
            code = code.replace(b"\r\r\n", b"\r\n")
            script[2] = RString(zlib.compress(code), None)
            count += 1
    output = target / script_file.name
    output.write_bytes(rm.dump(scripts))
    log(f"Updating of {count} scripts done")
    return [output]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Converts RPG Maker VX Ace data to JSON and back, like RV2JSON."
    )
    parser.add_argument("-c", "--create", action="store_true", help="Create JSON dumps")
    parser.add_argument(
        "-u", "--update", action="store_true", help="Update data from JSON"
    )
    parser.add_argument("-d", "--data-dir", dest="data")
    parser.add_argument("-j", "--json-dir", dest="json_dir", default="ace_json")
    parser.add_argument("-o", "--out-dir", dest="out")
    parser.add_argument("-s", "--skip-backup", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.create and not args.update:
        print(
            "ERROR: No action specified. Use -c to create JSON dumps or -u to update from JSON"
        )
        return 1
    root = Path.cwd()
    try:
        if args.create:
            create(root, data=args.data, json_dir=args.json_dir)
        if args.update:
            update(
                root,
                data=args.data,
                json_dir=args.json_dir,
                out=args.out,
                skip_backup=args.skip_backup,
            )
    except ConversionError as exc:
        print("ERROR: " + str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
