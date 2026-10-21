"""Likely slips in RPG Maker MZ Show Text headers, found before translation.

A Show Text header (code 101) gives the message box after it a face and a
nameplate. Developers sometimes put the wrong ones on a box: another
character's, a nameplate on a sound effect, or none on a spoken line. This
check learns the game's own conventions from its boxes and flags the boxes
that break them in a way a slip explains:

- face: a face that shows one character, once or twice on a box named for
  another;
- self-address: a box whose text calls out to its own nameplate's character,
  or names them with an honorific, as another speaker in the scene does;
- pronoun: a first-person pronoun its speaker never uses, as another speaker
  in the scene does;
- sound-effect and unnamed-line: a nameplate on a box styled like the game's
  unnamed sound effects, beside an unnamed box that reads as speech.

Unnamed speech is not flagged on its own: games leave narrators, crowds and
off-screen voices unnamed on purpose.

It reads the Japanese source, from `_original` where the engine translated a
value, leaves out headers the translation already gave another speaker, so a
fixed slip does not come back, and never changes a file. Text QA sends each
flag on a line its inventory holds to deep review as a `show-text-header`
check, which gives a flag the setup assistant kept this second look after
translation.

Why these rules and no others, measured on real games:

- On Arina and the Succubus Curse, whose translation, a manual fix and release
  QA corrected 24 headers, the check raised 14 flags on the Japanese source,
  all slips: 9 of those 24 and 5 no one had fixed.
- Across 16 other games in one translator's library it raised 6: three clear
  slips, two likely ones and a deliberate change of register.
- Those games ruled out cues that worked on Arina alone: an unnamed spoken box
  between named ones (15 flags and 11 slips on Arina, but about 200 elsewhere,
  nearly all narrators, crowds and off-screen voices left unnamed on purpose),
  a name called out without another speaker using it, a placeholder such as
  ？？？ and a face shown repeatedly with an alias.
- Arina ruled out voice files before a box (its voice folders also play before
  sound effects), every named sound effect (21 flags, 1 slip), narration under
  a nameplate (33 flags, 2 slips), a reply after someone addressed a third
  character (4 flags, 1 slip) and identical lines whose nameplates differ (all
  deliberate labels).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from util import rpgmaker_blocks as blocks

SCHEMA = "rpgmaker-header-check-v1"
FLAG_LIMIT = 200
TEXT_LIMIT = 120
KINDS = ("face", "self-address", "pronoun", "sound-effect", "unnamed-line")

_EVENT_FILE_RE = re.compile(r"(?:Map\d+|CommonEvents|Troops)\.json")
_ACTOR_CODE_RE = re.compile(r"\\[Nn]\[(\d+)\]")
_CODE_RE = re.compile(r"\\[A-Za-z]+(?:\[[^\]]*\]|<[^>]*>)?|\\[{}<>|.!^$]")
_LEADING_CODES_RE = re.compile(r"^(?:\\[A-Za-z]+(?:\[[^\]]*\])?)+")
_LETTER_RE = re.compile(r"[ぁ-ゖァ-ヺ一-龠々〆A-Za-zＡ-Ｚａ-ｚ]")
_QUOTED_RE = re.compile(r"「[^」]*」|『[^』]*』")
_HONORIFIC = r"(?:ちゃん|さん|さーん|様|さま|サマ|君|くん|クン|殿|どの|先生|先輩|せんぱい|たん|氏)"
# First-person pronouns. Kanji 私 is any of the readings that write it, so a
# speaker who says あたし is not flagged for 私, nor one who writes 私 for わたし.
_PRONOUNS = {
    "私": r"私",
    "わたし": r"わたし|ワタシ",
    "あたし": r"あたし|アタシ",
    "わたくし": r"わたくし",
    "ぼく": r"(?<![下公従])僕|ぼく|ボク",
    "おれ": r"俺|おれ|オレ",
    "わし": r"儂|わし|ワシ",
    "あたい": r"あたい|アタイ",
    "おいら": r"おいら|オイラ",
    "拙者": r"拙者",
}
_KANJI_READINGS = frozenset({"わたし", "あたし", "わたくし"})
# A pronoun ends where a particle, punctuation or the line does, so 私服,
# 僕ら or おれい (お礼) do not count.
_PRONOUN_END = r"(?=[はがのをにもとへやっねよさだでじか、。…‥！？!?♥♡　 \n〜～ー]|$)"
_PRONOUN_RES = {
    token: re.compile(f"(?:{pattern}){_PRONOUN_END}")
    for token, pattern in _PRONOUNS.items()
}


# A convention needs this many boxes before a break from it counts.
MIN_FACE_USES = 3
MIN_PRONOUN_BOXES = 8
MIN_SIGNATURE_BOXES = 10
# How rare a break must be: a face's other names, a speaker's other pronouns.
OWNER_SHARE = 0.8
STRAY_SHARE = 0.1
PRONOUN_STRAY = 0.05
PRONOUN_HABIT = 0.3
UNNAMED_SIGNATURE = 0.9
# A name seen this often with another character's faces is an alias.
FACE_ALIAS_USES = 3
# Probability a box's text is speech before an unnamed one counts as spoken.
SPEECH = 0.999


def _same_pronoun(token: str) -> frozenset[str]:
    """The pronouns that may be the same word as this one."""
    if token == "私":
        return _KANJI_READINGS | {"私"}
    return frozenset({token, "私"} if token in _KANJI_READINGS else {token})


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _source(command: dict[str, Any], position: int) -> str:
    """A parameter's Japanese: `_original` once the engine translated it."""
    original = command.get("_original")
    if isinstance(original, str):
        return original
    parameters = command.get("parameters") or []
    value = parameters[position] if len(parameters) > position else ""
    return value if isinstance(value, str) else ""


def _actors(data: Path) -> dict[str, str]:
    names = {}
    for index, actor in enumerate(_read(data / "Actors.json") or []):
        if isinstance(actor, dict):
            original = actor.get("_original")
            name = original.get("name") if isinstance(original, dict) else None
            name = name if isinstance(name, str) else actor.get("name")
            if isinstance(name, str):
                names[str(index)] = name
    return names


def _placeholder(name: str) -> bool:
    """A nameplate that hides its speaker, such as ？？？, names no one."""
    return not _LETTER_RE.search(name)


def _plain(text: str, actors: dict[str, str]) -> str:
    text = _ACTOR_CODE_RE.sub(lambda match: actors.get(match.group(1), ""), text)
    return _CODE_RE.sub("", text).strip()


def _signature(text: str) -> str:
    """The control codes a box starts with, which some games give sound effects."""
    match = _LEADING_CODES_RE.match(text.strip())
    return match.group(0).upper() if match else ""


def _boxes(data: Path) -> list[dict[str, Any]]:
    """Every command list's message boxes, in order, each beside its list's."""
    actors = _actors(data)
    found = []
    for path in sorted(data.glob("*.json"), key=lambda item: item.name):
        if not _EVENT_FILE_RE.fullmatch(path.name):
            continue
        document = _read(path)
        for list_path, commands in blocks.command_lists(document):
            boxes = []
            for block in blocks.blocks(commands):
                if block.kind != blocks.MESSAGE or block.head is None:
                    continue
                index, command = block.head, commands[block.head]
                parameters = command.get("parameters")
                if not isinstance(parameters, list) or len(parameters) < 5:
                    continue
                lines = list(block.rows)
                raw = "\n".join(_source(commands[line], 0) for line in lines)
                name = _plain(_source(command, 4), actors)
                boxes.append({
                    "file": path.name,
                    "list": list_path,
                    "index": index,
                    "lines": lines,
                    "face_name": parameters[0] if isinstance(parameters[0], str) else "",
                    "face_index": parameters[1] if type(parameters[1]) is int else 0,
                    "name": name,
                    "raw_name": _source(command, 4),
                    "live_name": parameters[4] if isinstance(parameters[4], str) else "",
                    "translated": isinstance(command.get("_original"), str),
                    "raw": raw,
                    "text": _plain(raw, actors),
                    "signature": _signature(raw),
                })
            for position, box in enumerate(boxes):
                box["previous"] = boxes[position - 1] if position else None
                box["next"] = boxes[position + 1] if position + 1 < len(boxes) else None
                box["scene"] = boxes
            found += boxes
    return found


def _pointer(box: dict[str, Any], index: int | None = None) -> str:
    parts = (*box["list"], box["index"] if index is None else index)
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


class _Speech:
    """How likely a box's text is a spoken line rather than narration or a
    sound effect: character pairs of the game's named against its unnamed
    boxes, each box scored without its own counts."""

    def __init__(self, boxes: list[dict[str, Any]]) -> None:
        self.pairs = {True: Counter(), False: Counter()}
        self.boxes = Counter()
        for box in boxes:
            box["pairs"] = self._pairs(box["text"])
            named = bool(box["name"])
            self.pairs[named].update(box["pairs"])
            self.boxes[named] += 1
        self.totals = {key: sum(value.values()) for key, value in self.pairs.items()}
        self.vocabulary = len(set(self.pairs[True]) | set(self.pairs[False])) or 1

    @staticmethod
    def _pairs(text: str) -> Counter:
        text = "^" + re.sub(r"\s+", " ", text) + "$"
        return Counter(text[index:index + 2] for index in range(len(text) - 1))

    def spoken(self, box: dict[str, Any]) -> float:
        own = bool(box["name"])
        scores = {}
        for named in (True, False):
            mine = named == own
            boxes = self.boxes[named] - mine
            if boxes <= 0:
                return 0.5
            total = self.totals[named] - (sum(box["pairs"].values()) if mine else 0)
            score = math.log(boxes)
            for pair, count in box["pairs"].items():
                seen = self.pairs[named][pair] - (count if mine else 0)
                score += count * math.log((seen + 0.5) / (total + 0.5 * self.vocabulary))
            scores[named] = score
        top = max(scores.values())
        weights = {key: math.exp(value - top) for key, value in scores.items()}
        return weights[True] / sum(weights.values())


def _flag(box: dict[str, Any], kind: str, evidence: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "file": box["file"],
        "pointer": _pointer(box),
        "face_name": box["face_name"],
        "face_index": box["face_index"],
        "name": box["raw_name"],
        "text": box["raw"] if len(box["raw"]) <= TEXT_LIMIT else box["raw"][:TEXT_LIMIT] + "…",
        "evidence": evidence,
        "lines": [_pointer(box, line) for line in box["lines"]],
    }


def _face_flags(boxes: list[dict[str, Any]]) -> list[tuple[dict, str, str]]:
    """A face that shows one character, once or twice on a box named for
    another."""
    by_face: dict[tuple, Counter] = defaultdict(Counter)
    by_name: dict[str, Counter] = defaultdict(Counter)
    for box in boxes:
        key = (box["face_name"], box["face_index"])
        by_name[box["name"]][key] += 1
        if box["face_name"]:
            by_face[key][box["name"]] += 1
    owners = {
        key: owner for key, names in by_face.items()
        for owner, uses in [names.most_common(1)[0]]
        if owner and not _placeholder(owner)
        and uses >= MIN_FACE_USES and uses / sum(names.values()) >= OWNER_SHARE
    }
    # How often each name shows each owner's faces: an alias, a costume or a
    # name before a reveal recurs, where a slip does not.
    pairs: Counter = Counter()
    for box in boxes:
        owner = owners.get((box["face_name"], box["face_index"]))
        if owner:
            pairs[(owner, box["name"])] += 1
    flags = []
    for box in boxes:
        key = (box["face_name"], box["face_index"])
        owner, name = owners.get(key), box["name"]
        if (
            not owner or not name or owner == name or _placeholder(name)
            or owner in name or name in owner
            or pairs[(owner, name)] >= FACE_ALIAS_USES
            or by_face[key][name] / sum(by_face[key].values()) > STRAY_SHARE
            # A name usually shown with this face is this character's.
            or by_name[name].most_common(1)[0][0] == key
        ):
            continue
        uses = by_face[key][owner]
        flags.append((box, "face", (
            f"Face {box['face_name']} {box['face_index']} shows {owner} in {uses} "
            f"of its {sum(by_face[key].values())} boxes, but this box has the "
            f"nameplate {name}."
        )))
    return flags


def _said(name: str, text: str) -> str:
    """How a text calls a character by name, outside quoted speech: with an
    honorific, or calling out to them."""
    text = _QUOTED_RE.sub("", text)
    escaped = re.escape(name)
    # このコルパ様 is a speaker boasting of themself, and マリカちゃん、言うな
    # one objecting to how others call them.
    honorific = re.search(
        r"(?<!この)" + escaped + _HONORIFIC + r"(?!(?:、)?(?:って|と呼|呼ぶ|呼ば|言うな))",
        text,
    )
    if honorific:
        return f"says {honorific.group(0)}"
    # "Name、" more often starts a speaker's line about themself.
    if re.search(r"(?:^|[\n（(　 ])" + escaped + r"(?=[…‥！？!?　 \n〜～ー]|$)", text):
        return f"calls out to {name}"
    return ""


def _self_address_flags(boxes: list[dict[str, Any]]) -> list[tuple[dict, str, str]]:
    """A box whose text calls its own nameplate's character by name, as
    another speaker in the scene does."""
    found = defaultdict(list)
    named = Counter(box["name"] for box in boxes)
    for box in boxes:
        name = box["name"]
        if len(name) < 2 or _placeholder(name):
            continue
        said = _said(name, box["text"])
        others = said and sorted({
            other["name"] for other in box["scene"]
            if other["name"] and other["name"] != name
            and _said(name, other["text"]) == said
        })
        if others:
            found[name].append((box, said, others))
    flags = []
    for name, hits in found.items():
        # A speaker who often says their own name does it on purpose.
        if len(hits) > max(2, named[name] * 0.02):
            continue
        for box, said, others in hits:
            flags.append((box, "self-address", (
                f"The nameplate is {name}, but the text {said}, as "
                f"{', '.join(others[:3])} does in this scene, so another character "
                "likely speaks."
            )))
    return flags


def _pronouns(text: str) -> set[str]:
    text = _QUOTED_RE.sub("", text)
    return {token for token, pattern in _PRONOUN_RES.items() if pattern.search(text)}


def _pronoun_flags(boxes: list[dict[str, Any]]) -> list[tuple[dict, str, str]]:
    """A first-person pronoun its speaker never uses, as another speaker in the
    same scene does."""
    habits: dict[str, Counter] = defaultdict(Counter)
    counted: Counter = Counter()
    for box in boxes:
        box["pronouns"] = _pronouns(box["text"]) if box["name"] else set()
        if box["pronouns"]:
            counted[box["name"]] += 1
            habits[box["name"]].update(box["pronouns"])

    def share(name: str, tokens: frozenset[str], without: set[str] = frozenset()) -> float:
        boxes = counted[name] - bool(without)
        used = sum(habits[name][token] - (token in without) for token in tokens)
        return used / boxes if boxes else 0.0

    flags = []
    for box in boxes:
        name = box["name"]
        if (
            not box["pronouns"] or _placeholder(name)
            or counted[name] - 1 < MIN_PRONOUN_BOXES
        ):
            continue
        for token in sorted(box["pronouns"]):
            same = _same_pronoun(token)
            # The box's own words do not count towards its speaker's habit.
            if share(name, same, box["pronouns"]) > PRONOUN_STRAY:
                continue
            partners = sorted({
                other["name"] for other in box["scene"]
                if other["name"] and other["name"] != name
                and not _placeholder(other["name"])
                and counted[other["name"]] >= MIN_PRONOUN_BOXES
                and share(other["name"], same) >= PRONOUN_HABIT
            })
            if not partners:
                continue
            usual = habits[name].most_common(1)[0][0]
            flags.append((box, "pronoun", (
                f"The nameplate is {name}, who says {usual} in other boxes, but this "
                f"box says {token}, as {', '.join(partners)} does in this scene."
            )))
            break
    return flags


def _unnamed_signatures(boxes: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Leading codes the game keeps for unnamed boxes, such as its sound effects."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for box in boxes:
        if box["signature"]:
            counts[box["signature"]][bool(box["name"])] += 1
    return {
        signature: (count[False], count[False] + count[True])
        for signature, count in counts.items()
        if sum(count.values()) >= MIN_SIGNATURE_BOXES
        and count[False] / sum(count.values()) >= UNNAMED_SIGNATURE
    }


def _spoken(box: dict[str, Any], speech: _Speech, unnamed: dict) -> bool:
    return (
        box["signature"] not in unnamed
        and len(_LETTER_RE.findall(box["text"])) >= 2
        and speech.spoken(box) >= SPEECH
    )


def _unnamed_flags(
    boxes: list[dict[str, Any]], speech: _Speech
) -> list[tuple[dict, str, str]]:
    """A nameplate on a sound effect beside an unnamed spoken line: a header
    one box from where it belongs."""
    unnamed = _unnamed_signatures(boxes)
    flags = []
    for box in boxes:
        if not box["name"] or box["signature"] not in unnamed:
            continue
        for neighbour, side, back in (
            (box["next"], "after", "before"), (box["previous"], "before", "after"),
        ):
            if neighbour and not neighbour["name"] and _spoken(neighbour, speech, unnamed):
                blank, total = unnamed[box["signature"]]
                flags.append((box, "sound-effect", (
                    f"This box has the nameplate {box['name']}, but {blank} of the game's "
                    f"{total} boxes that start with {box['signature']} have none, and the "
                    f"spoken line {side} it has no nameplate."
                )))
                flags.append((neighbour, "unnamed-line", (
                    "This box reads as a spoken line but has no nameplate, while the "
                    f"box {back} it puts {box['name']} on what reads as a sound effect."
                )))
                break
    return flags


def _relabeled(boxes: list[dict[str, Any]]) -> set[int]:
    """Boxes whose translated nameplate already differs from what its source
    nameplate usually becomes, such as a slip fixed during translation."""
    usual: dict[str, Counter] = defaultdict(Counter)
    for box in boxes:
        if box["translated"]:
            usual[box["raw_name"]][box["live_name"]] += 1
    return {
        id(box) for box in boxes
        if box["translated"]
        and box["live_name"] != usual[box["raw_name"]].most_common(1)[0][0]
    }


def check(data_root: str | Path) -> dict[str, Any]:
    """Likely Show Text header slips in a game's event files."""
    data = Path(data_root).expanduser().resolve()
    boxes = _boxes(data)
    speech = _Speech(boxes)
    found = (
        _face_flags(boxes) + _self_address_flags(boxes) + _pronoun_flags(boxes)
        + _unnamed_flags(boxes, speech)
    )
    relabeled = _relabeled(boxes)
    order = {id(box): position for position, box in enumerate(boxes)}
    flags, seen = [], set()
    for box, kind, evidence in sorted(
        found, key=lambda value: (order[id(value[0])], KINDS.index(value[1]))
    ):
        if id(box) in relabeled or id(box) in seen:
            continue
        seen.add(id(box))
        flags.append(_flag(box, kind, evidence))
    return {
        "schema": SCHEMA,
        "boxes": len(boxes),
        "total": len(flags),
        "counts": {kind: sum(flag["kind"] == kind for flag in flags) for kind in KINDS},
        "flags": flags[:FLAG_LIMIT],
    }
