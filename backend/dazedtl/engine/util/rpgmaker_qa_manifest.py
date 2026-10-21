"""Deterministic inventory builder for post-export RPG Maker translation QA.

This module deliberately contains no semantic review logic.  It freezes the
mechanical source/live universe so a reviewer cannot silently change scope,
ordering, speaker state, or identities while deciding whether text is correct.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from util import system
from util import rpgmaker_blocks as blocks
from util.qa import mechanical

SCHEMA = "rpgmaker-qa-manifest-v1"
EXTRACTOR = "dazedtl-rpgmaker-qa-extractor-v1"
PATH_GRAMMAR = "rfc6901-json-pointer-v1"
ORDERING = "sha256-rpgmaker-qa-focus-v1"
NORMALIZATION = "exact-utf8-no-normalization-v1"
LENGTH_THRESHOLDS = {"short_max": 20, "medium_max": 60}
FOCUSES = frozenset({"database", "risky-codes", "dialogue", "release"})
DIALOGUE_CODES = frozenset({101, 102, 401, 405})
RISKY_CODES = frozenset({108, 111, 122, 320, 324, 325, 355, 356, 357, 408, 655, 657})
DATABASE_FILES = frozenset(
    {
        "Actors.json",
        "Armors.json",
        "Classes.json",
        "Enemies.json",
        "Items.json",
        "MapInfos.json",
        "Skills.json",
        "States.json",
        "System.json",
        "Weapons.json",
    }
)
TOOL_MANAGED_QA_EXCLUSIONS = frozenset({
    ("System.json", "/_original/gameTitle"),
})
# A record's text is its value ("identity") or the text between a code 122
# operand's quote marks, named by the mark that opens it: translation writes
# MV/MZ's JavaScript template literal between backticks and VX Ace's Ruby
# string between double quotes, and QA writes corrections there with the same
# escapes. Between other quote marks no escapes are known ("quoted-string").
SCRIPT_STRINGS = {"`": "template-literal", '"': "double-quoted-string"}
QUOTED_TRANSFORMS = frozenset({"quoted-string", *SCRIPT_STRINGS.values()})
SCALAR_PARAMETER = {
    108: 0,
    122: 4,
    320: 1,
    324: 1,
    325: 1,
    355: 0,
    356: 0,
    408: 0,
    655: 0,
    657: 0,
}
CODE357_TEXT_ARGUMENTS = {
    "LL_InfoPopupWIndow": ("messageText",),
    "QuestSystem": ("DetailNote",),
    "BalloonInBattle": ("text",),
    "MNKR_CommonPopupCoreMZ": ("text",),
    "DestinationWindow": ("destination",),
    "_TMLogWindowMZ": ("text",),
    "TorigoyaMZ_NotifyMessage": ("message",),
    "SoR_GabWindow": ("arg1",),
    "DarkPlasma_CharacterText": ("text",),
    "DTextPicture": ("text",),
    "MM_UltimateTextAnimation": ("text",),
    "TextButtonPicture": ("text",),
    "TextPlacer": ("text",),
    "TextPicture": ("text",),
    "TRP_SkitMZ": ("name",),
    "LogMessage": ("text",),
    "LogWindow": ("text",),
    "BattleLogOutput": ("message",),
    "TorigoyaMZ_NotifyMessage_CommandMessage": ("message",),
    "NUUN_SaveScreen": ("AnyName",),
    "build/ARPG_Core": ("Text", "SkillByName"),
    "EventLabel": ("text",),
    "KN_MapBattle": ("enemyName",),
    "KN_Shop": ("goodsType",),
    "KN_StillManager": ("label",),
    "Mano_CurrencyUnit": ("unit",),
    "SceneGlossary": ("category",),
}
def _sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _escape(part: object) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def pointer(parts: tuple[object, ...]) -> str:
    return "" if not parts else "/" + "/".join(_escape(part) for part in parts)


def resolve_pointer(document: Any, json_pointer: str) -> Any:
    current = document
    if not json_pointer:
        return current
    if not json_pointer.startswith("/"):
        raise KeyError(json_pointer)
    for encoded in json_pointer[1:].split("/"):
        part = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def string_leaves(value: Any, path: tuple[object, ...] = ()):
    if isinstance(value, str):
        if value.strip():
            yield path, value
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from string_leaves(child, path + (index,))
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from string_leaves(value[key], path + (key,))


def _classification(filename: str, code: int | None) -> str:
    event_file = filename in {"CommonEvents.json", "Troops.json"} or bool(
        re.fullmatch(r"Map\d+\.json", filename)
    )
    if event_file and code in DIALOGUE_CODES:
        return "dialogue"
    if event_file and code in RISKY_CODES:
        return "risky-codes"
    if filename in DATABASE_FILES and code is None:
        return "database"
    return "other"


def _visible_name(command: dict[str, Any]) -> tuple[str, str]:
    params = command.get("parameters")
    if not isinstance(params, list):
        return "", ""
    if len(params) > 4:
        display = params[4] if isinstance(params[4], str) else ""
        face = params[0] if params and isinstance(params[0], str) else ""
    elif 0 < len(params) < 4:
        display = params[0] if isinstance(params[0], str) else ""
        face = ""
    else:
        display = ""
        face = params[0] if params and isinstance(params[0], str) else ""
    raw = display.strip()
    raw = re.sub(r"^(?:[\\]+[cC]\[\d+\]\s*)+", "", raw)
    match = re.match(r"^【\s*([^】]+?)\s*】", raw)
    if match:
        raw = match.group(1).strip()
    else:
        raw = re.split(r"[\\]", raw, maxsplit=1)[0].strip()
    return raw, face


def _speaker(command_list: list[Any], index: int, code: int) -> dict[str, str]:
    """Resolve speaker from raw adjacency; never retain state across commands."""
    owner = blocks.show_text(command_list, index) if code in (101, 401, 102) else None
    if owner is None:
        return {"display_name": "", "face_name": "", "provenance": "none"}
    display, face = _visible_name(command_list[owner])
    provenance = "adjacent-code-101" if owner != index else "code-101"
    return {"display_name": display, "face_name": face, "provenance": provenance}


def _choice_help(record: dict[str, Any], command_list: list[Any], index: int) -> None:
    """Mark a comment line (408) that is a choice's help, which shows in the
    message window beside the face of the choice's message, with the rest of
    its comment, which the window shows with it."""
    if blocks.help_branch(command_list, index) is not None:
        record["choice_help"] = {
            "face": blocks.help_face(command_list, index),
            "comment": blocks.help_layout(command_list, index),
        }


_ROW_MAPPINGS = {
    401: "joined-contiguous-401",
    405: "joined-contiguous-405",
    408: "joined-contiguous-408",
    108: "joined-comment-108-408",
}


def live_mapping(
    owner: dict[str, Any],
    owner_path: tuple[object, ...],
    original_path: tuple[object, ...],
    code: int | None,
    command_list: list[Any] | None,
    command_index: int | None,
) -> tuple[list[tuple[object, ...]], str] | None:
    if isinstance(owner.get("_original"), (dict, list)):
        if code == 102 and original_path:
            live = owner_path + ("parameters", 0, original_path[0])
        elif code == 357 and (not original_path or original_path[0] != "parameters"):
            live = owner_path + ("parameters", 3) + original_path
        else:
            relative = original_path
            if relative and relative[0] == "parameters":
                relative = relative[1:]
                live = owner_path + ("parameters",) + relative
            else:
                live = owner_path + relative
        return [live], "direct"

    if code == 101:
        params = owner.get("parameters") or []
        if len(params) > 4 and isinstance(params[4], str):
            index = 4
        elif 0 < len(params) < 4 and isinstance(params[0], str):
            index = 0
        else:
            return None
        return [owner_path + ("parameters", index)], "direct"
    if code in blocks.ROW_CODES:
        # The rows the translation owns (see rpgmaker_blocks.owned).
        if command_list is None or command_index is None:
            return [owner_path + ("parameters", 0)], _ROW_MAPPINGS[code]
        rows = blocks.part_rows(command_list, command_index)
        return [
            owner_path[:-1] + (cursor, "parameters", 0) for cursor in rows
        ], _ROW_MAPPINGS[code]
    if code == 355:
        paths = [owner_path + ("parameters", 0)]
        if command_list is not None and command_index is not None:
            cursor = command_index + 1
            while cursor < len(command_list):
                following = command_list[cursor]
                if not isinstance(following, dict) or following.get("code") != 655:
                    break
                if "_original" in following:
                    break
                paths.append(owner_path[:-1] + (cursor, "parameters", 0))
                cursor += 1
        return paths, "joined-script-355-655"
    if code == 357:
        params = owner.get("parameters") or []
        header = params[0] if params and isinstance(params[0], str) else ""
        arguments = params[3] if len(params) > 3 and isinstance(params[3], dict) else {}
        candidates = []
        for plugin, keys in CODE357_TEXT_ARGUMENTS.items():
            if plugin in header:
                candidates.extend(key for key in keys if isinstance(arguments.get(key), str))
        candidates = sorted(set(candidates))
        if len(candidates) == 1:
            return [owner_path + ("parameters", 3, candidates[0])], "code-357-argument"
        return None
    if code in SCALAR_PARAMETER:
        return [owner_path + ("parameters", SCALAR_PARAMETER[code])], "direct"
    return None


def read_live(
    document: Any, paths: list[tuple[object, ...]], code: int | None
) -> tuple[str, str]:
    values = [resolve_pointer(document, pointer(path)) for path in paths]
    if not all(isinstance(value, str) for value in values):
        raise TypeError("live counterpart is not a string")
    live = "\n".join(values)
    if code == 122:
        match = re.search(r"(['\"`])(.*)['\"`]", live)
        if not match:
            raise ValueError("code 122 live parameter has no quoted string")
        return match.group(2), SCRIPT_STRINGS.get(match.group(1), "quoted-string")
    return live, "identity"


def _record_identity(filename: str, source_pointer: str, source_hash: str) -> str:
    return f"{filename}#{source_pointer}@{source_hash}"


def _length_band(text: str) -> str:
    length = len(text)
    if length <= LENGTH_THRESHOLDS["short_max"]:
        return "short"
    if length <= LENGTH_THRESHOLDS["medium_max"]:
        return "medium"
    return "long"


def _display_shape(code: int | None, classification: str) -> str:
    return {
        101: "name-box",
        102: "choice",
        401: "message",
        405: "scrolling-text",
    }.get(code, "event-command" if code is not None else classification)


def build_manifest(data_root: str | Path, focus: str) -> dict[str, Any]:
    """Return a deterministic, side-effect-free QA inventory manifest."""
    if focus not in FOCUSES:
        raise ValueError(f"unknown focus: {focus!r}")
    root = Path(data_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"data folder does not exist: {root}")

    files: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    json_paths = sorted(
        (item for item in root.rglob("*.json") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for path in json_paths:
        filename = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        files.append({"path": filename, "sha256": _sha256(raw)})
        try:
            document = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            unresolved.append(
                {"file": filename, "source_pointer": None, "reason": f"parse-error: {exc}"}
            )
            continue

        def walk(
            value: Any,
            path_parts: tuple[object, ...],
            command_list: list[Any] | None = None,
            command_index: int | None = None,
        ) -> None:
            if isinstance(value, dict):
                code = value.get("code") if isinstance(value.get("code"), int) else None
                original = value.get("_original")
                if original is not None:
                    classification = _classification(path.name, code)
                    include = focus == "release" or focus == classification
                    if include:
                        leaves = list(string_leaves(original))
                        if not leaves:
                            unresolved.append(
                                {
                                    "file": filename,
                                    "source_pointer": pointer(path_parts + ("_original",)),
                                    "classification": classification,
                                    "reason": "empty-or-non-string-original",
                                }
                            )
                        for original_path, source in leaves:
                            source_path = path_parts + ("_original",) + original_path
                            if (
                                filename,
                                pointer(source_path),
                            ) in TOOL_MANAGED_QA_EXCLUSIONS:
                                continue
                            mapping = live_mapping(
                                value,
                                path_parts,
                                original_path,
                                code,
                                command_list,
                                command_index,
                            )
                            if mapping is None:
                                unresolved.append(
                                    {
                                        "file": filename,
                                        "source_pointer": pointer(source_path),
                                        "classification": classification,
                                        "reason": "unsupported-scalar-original-shape",
                                    }
                                )
                                continue
                            live_paths, mapping_kind = mapping
                            try:
                                live, live_transform = read_live(document, live_paths, code)
                            except (KeyError, IndexError, TypeError, ValueError) as exc:
                                unresolved.append(
                                    {
                                        "file": filename,
                                        "source_pointer": pointer(source_path),
                                        "classification": classification,
                                        "reason": f"unresolvable-live-counterpart: {exc}",
                                    }
                                )
                                continue
                            source_hash = _sha256(source)
                            record = {
                                "identity": _record_identity(
                                    filename, pointer(source_path), source_hash
                                ),
                                "file": filename,
                                "source_pointer": pointer(source_path),
                                "live_pointers": [pointer(item) for item in live_paths],
                                "source_sha256": source_hash,
                                "source": source,
                                "live": live,
                                "classification": classification,
                                "mapping": mapping_kind,
                                "live_transform": live_transform,
                                "event_code": code,
                                "display_shape": _display_shape(code, classification),
                                "source_char_length": len(source),
                                "live_char_length": len(live),
                                "length_band": _length_band(live),
                                "mechanical": mechanical.evidence(source, live, code),
                            }
                            if code == 408 and command_list is not None:
                                _choice_help(record, command_list, int(command_index))
                            if code in DIALOGUE_CODES and command_list is not None:
                                record["speaker"] = _speaker(
                                    command_list, int(command_index), code
                                )
                                if code == 102:
                                    params = value.get("parameters") or []
                                    indent = value.get("indent")
                                    branches = []
                                    cursor = int(command_index) + 1
                                    while cursor < len(command_list):
                                        branch = command_list[cursor]
                                        if not isinstance(branch, dict):
                                            cursor += 1
                                            continue
                                        if branch.get("code") == 404 and branch.get("indent") == indent:
                                            break
                                        if branch.get("code") == 402 and branch.get("indent") == indent:
                                            branch_params = branch.get("parameters") or []
                                            branches.append(
                                                {
                                                    "index": branch_params[0] if branch_params else None,
                                                    "label": branch_params[1] if len(branch_params) > 1 else None,
                                                }
                                            )
                                        cursor += 1
                                    record["choice_context"] = {
                                        "cancel_type": params[1] if len(params) > 1 else None,
                                        "default_type": params[2] if len(params) > 2 else None,
                                        "position_type": params[3] if len(params) > 3 else None,
                                        "background": params[4] if len(params) > 4 else None,
                                        "branches": branches,
                                    }
                            if classification == "database":
                                record["database_entity"] = {
                                    "id": value.get("id"),
                                    "name": value.get("name") if isinstance(value.get("name"), str) else None,
                                    "field": "/".join(str(item) for item in original_path),
                                }
                            if classification == "risky-codes":
                                params = value.get("parameters") or []
                                record["risky_context"] = {
                                    "plugin_header": params[0]
                                    if code == 357 and params and isinstance(params[0], str)
                                    else None,
                                    "actor_id": params[0]
                                    if code in {320, 324, 325} and params
                                    else None,
                                    "visibility": "requires-runtime-evidence",
                                }
                            records.append(record)

                for key in sorted(value):
                    if key != "_original":
                        walk(value[key], path_parts + (key,))
            elif isinstance(value, list):
                is_commands = any(
                    isinstance(item, dict) and isinstance(item.get("code"), int)
                    for item in value
                )
                for index, child in enumerate(value):
                    walk(
                        child,
                        path_parts + (index,),
                        value if is_commands else command_list,
                        index if is_commands else command_index,
                    )

        walk(document, ())

    records.sort(key=lambda item: item["identity"])
    unresolved.sort(
        key=lambda item: (item["file"], item.get("source_pointer") or "", item["reason"])
    )
    grouped: dict[tuple[str, str], list[str]] = {}
    for record in records:
        grouped.setdefault((record["source"], record["live"]), []).append(record["identity"])
    clusters = []
    for (source, live), identities in grouped.items():
        identities.sort()
        clusters.append(
            {
                "representative": identities[0],
                "identities": identities,
                "source": source,
                "live": live,
            }
        )
    clusters.sort(key=lambda item: item["representative"])
    review_sequence = sorted(
        (item["representative"] for item in clusters),
        key=lambda identity: _sha256(
            "rpgmaker-qa-focus-v1\0" + focus + "\0" + identity
        ),
    )
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "extractor": EXTRACTOR,
        "path_grammar": PATH_GRAMMAR,
        "ordering": ORDERING,
        "normalization": NORMALIZATION,
        "length_thresholds": LENGTH_THRESHOLDS,
        "focus": focus,
        "files": files,
        "records": records,
        "unresolved": unresolved,
        "clusters": clusters,
        "review_sequence": review_sequence,
        "counts": {
            "files": len(files),
            "records": len(records),
            "clusters": len(clusters),
            "unresolved": len(unresolved),
        },
    }
    manifest["content_sha256"] = _sha256(_canonical_bytes(manifest))
    return manifest


def write_manifest(manifest: dict[str, Any], output: str | Path) -> None:
    """Atomically write a canonical, newline-terminated manifest."""
    destination = Path(output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(_canonical_bytes(manifest) + b"\n")
    system.replace(temporary, destination)
