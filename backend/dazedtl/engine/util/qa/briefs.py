"""What reviewers read: briefs, the hand-off text, rendered bundles and the
context view."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from util import rpgmaker_blocks as blocks
from util import rpgmaker_qa_glossary as glossary_rules
from util import system
from util.game_settings import load_language_pair
from util.prompt_pair import pair_note
from util.qa.bundles import _load_screen_index
from util.qa.interface import _place_text
from util.qa.records import (
    _bundle_row,
    _decode_pointer,
    _register_worker,
    _resolve_parts,
    _split_notice,
)
from util.qa.schema import (
    DEEP_RESULT_SCHEMA,
    EDITORIAL_RESULT_SCHEMA,
    FINDING_CATEGORIES,
    SCREEN_RESULT_SCHEMA,
    SUMMARY_LIMIT,
    SWEEP_RESULT_SCHEMA,
    _utc_now,
)
from util.qa.scope import _assigned_scenes, _declined_scope
from util.qa.selection import _command_number, _glossary_entries
from util.qa.storage import (
    _atomic_write_json,
    _atomic_write_text,
    _decisions,
    _load_task,
    _read_json,
    _task_lock,
    task_json,
)
from util.skills import rpgmaker_qa_skill_parts

# A handoff argument, quoted for the assistant's shell.
shell_argument = system.shell_argument


def runtime_command(script: str | Path) -> str:
    """Runs script with the running managed interpreter, even with no Python
    on PATH, by the app's rules for a command an assistant runs."""
    return system.shell_command(system.python_command(script))


# Each brief's sections besides the policy, commands and result formats; a
# worker reviews whichever bundle next gives it.
_BRIEF_SECTIONS = {
    "screen": ("Screen reviewer",),
    "deep": ("Deep reviewer",),
    "group": ("Group reviewer",),
    "editorial": ("Editorial reviewer",),
    "worker": (
        "Worker", "Screen reviewer", "Deep reviewer", "Group reviewer", "Editorial reviewer",
    ),
}
QA_ROLES = tuple(_BRIEF_SECTIONS)
_SKILL_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def _skill_sections(focus: str) -> tuple[str, dict[str, str], str]:
    """The QA policy's introduction, its sections by title, and the focus."""
    common, selected = rpgmaker_qa_skill_parts(focus)
    starts = list(_SKILL_SECTION_RE.finditer(common))
    intro = common[: starts[0].start()].strip() if starts else common
    sections = {
        match.group(1).strip(): common[
            match.end() : starts[index + 1].start() if index + 1 < len(starts) else None
        ].strip()
        for index, match in enumerate(starts)
    }
    return intro, sections, selected


def _fill(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _skill_values(task_dir: Path, task: dict[str, Any]) -> dict[str, str]:
    return {
        "CLI": runtime_command(
            Path(__file__).resolve().parents[2] / "scripts" / "rpgmaker_qa.py"
        ),
        "TASK": shell_argument(task_dir),
        "CONTEXT": str(task_dir / "context.json"),
        # The README, every brief and the prompt that hands a worker its
        # first command, the brief, start with it. It goes at the start of a
        # line, never indented: its here-document's end marker must be.
        "SHELL_NOTE": system.shell_note(),
        "RECEIPTS": str(
            Path(task["game_root"]) / ".dazedtl" / "qa-receipts" / task_dir.name
        ),
        "CATEGORIES": ", ".join(sorted(FINDING_CATEGORIES)),
        "SUMMARY_LIMIT": str(SUMMARY_LIMIT),
        "SCREEN_SCHEMA": SCREEN_RESULT_SCHEMA,
        "DEEP_SCHEMA": DEEP_RESULT_SCHEMA,
        "SWEEP_SCHEMA": SWEEP_RESULT_SCHEMA,
        "EDITORIAL_SCHEMA": EDITORIAL_RESULT_SCHEMA,
    }


def _languages(task: dict[str, Any]) -> str:
    """What a brief adds for the game's languages: a note when the game
    records a pair, which the policy, written for Japanese into English,
    reads differently."""
    try:
        pair = load_language_pair(task["game_root"])
    except (OSError, ValueError):
        # A game whose settings can't be read reads as Japanese, as the
        # census and Lines read it.
        return ""
    return pair_note(pair["source"], pair["target"]) if pair else ""


def _task_instructions(task_dir: Path, task: dict[str, Any]) -> str:
    """The task README: the QA policy with every role's brief, for this task."""
    intro, sections, focus = _skill_sections(task["focus"])
    body = "\n\n".join(
        f"## {title}\n\n{text}" for title, text in sections.items() if title != "Handoff"
    )
    return _fill(
        f"# Text QA task\n\n{{{{SHELL_NOTE}}}}{_languages(task)}Task: `{task_dir}`"
        f"\n\n{focus}\n\n{intro}\n\n{body}\n",
        _skill_values(task_dir, task),
    )


def write_instructions(task_dir: Path) -> None:
    """Writes the task README as it reads now, its game where it is now
    (storage.located), unless the README already says so: the README names
    the game's folder, which a move changes. The caller holds the task lock."""
    path = task_dir / "README.md"
    text = _task_instructions(task_dir, task_json(task_dir)).rstrip() + "\n"
    try:
        if system.read_bytes(path).decode("utf-8") == text:
            return
    except OSError, UnicodeDecodeError:
        pass
    _atomic_write_text(path, text)


def brief(task_dir: str | Path, role: str, worker: str = "") -> str:
    """One reviewer's brief: the policy, its role, the commands, and the
    game's guidance and decisions, so a reviewer reads no other context.

    A named *worker* starts a run with it, whose bundles `accept_text` counts.
    """
    if role not in QA_ROLES:
        raise ValueError("Choose a role: " + ", ".join(QA_ROLES))
    if worker:
        root = Path(task_dir).expanduser().resolve()
        with _task_lock(root):
            _root, _task, checkpoint = _load_task(root)
            _register_worker(checkpoint, worker, None)
            checkpoint["workers"][worker]["run_started"] = _utc_now()
            _atomic_write_json(root / "checkpoint.json", checkpoint)
    root, task, _checkpoint = _load_task(task_dir)
    _intro, sections, focus = _skill_sections(task["focus"])
    # A worker starts from its brief alone, so it carries the shell note too.
    parts = ["{{SHELL_NOTE}}" + _languages(task) + focus] + [
        f"## {name}\n\n{sections[name]}"
        for name in ("Policy", *_BRIEF_SECTIONS[role], "Commands", "Result formats")
    ]
    # The game's own text is appended after filling, so it is never read as
    # a placeholder.
    return "\n\n".join(
        [_fill("\n\n".join(parts), _skill_values(root, task)), *_game_guidance(root)]
    ) + "\n"


def _decision_line(decision: dict[str, Any]) -> str:
    wording = (
        f" ({decision['source']} = {decision['translation']})"
        if decision.get("source") else ""
    )
    return f"- {decision['key']}: {decision['choice']}{wording}"


def _game_guidance(root: Path) -> list[str]:
    """The task context's game notes, translation quirks, custom guidance and
    the decisions recorded so far; bundles carry the glossary entries they use."""
    context = _read_json(root / "context.json")
    documents = [
        ("Game notes", context.get("game")),
        ("Translation quirks", context.get("quirks")),
        *(
            (f"Game guidance: {Path(str(overlay.get('path') or '')).stem}", overlay)
            for overlay in context.get("overlays") or []
        ),
    ]
    parts = [
        f"## {title}\n\n{text}"
        for title, document in documents
        if (text := str((document or {}).get("text") or "").strip())
    ]
    if decisions := _decisions(root):
        parts.append("## Decisions\n\n" + "\n".join(map(_decision_line, decisions)))
    return parts


def handoff_text(task_dir: str | Path, helper: str) -> str:
    """The copied task: the policy's handoff for this task and helper, whose
    README it writes for the game where it is now."""
    root, task, _checkpoint = _load_task(task_dir)
    with _task_lock(root):
        write_instructions(root)
    _intro, sections, _focus = _skill_sections(task["focus"])
    return _fill(
        sections["Handoff"],
        {
            "GAME": Path(task["game_root"]).name,
            "README": str(root / "README.md"),
            "HELPER": helper,
        },
    ) + "\n"


# Commands the context view leaves out: flow, waits, sound and picture moves.
_CONTEXT_QUIET_CODES = frozenset({
    0, 221, 222, 223, 224, 225, 230, 231, 232, 235, 241, 245, 246, 249, 250,
    404, 412,
})
_CONTEXT_TEXT_CODES = frozenset({
    101, 102, 108, 122, 320, 324, 355, 357, 401, 402, 405, 408, 655,
})


def _context_text(value: Any) -> str:
    return "∅" if value is None else str(value).replace("\n", "⏎")


def context_view(
    task_dir: str | Path, locator: str, radius: int = 12, worker: str = ""
) -> str:
    """Read-only game text around a locator, with Japanese and current English.

    The locator is an inventory identity or a command list such as
    `Map001.json#/events/1/pages/0/list`. Scenes a reviewer declined stay out,
    except for the worker whose assigned bundle prints them.
    """
    root, task, checkpoint = _load_task(task_dir)
    data_root = Path(task["data_root"]).resolve()
    filename, _, pointer = locator.split("@", 1)[0].partition("#")
    path = (data_root / filename).resolve()
    if data_root not in path.parents or not path.is_file() or path.suffix != ".json":
        raise ValueError(f"Unknown game data file: {filename}")
    parts = _decode_pointer(pointer)
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if "list" not in parts:
        node = _resolve_parts(
            document, parts[: parts.index("_original")] if "_original" in parts else parts
        )
        return json.dumps(node, ensure_ascii=False, indent=1)[:6000]
    list_index = len(parts) - 1 - parts[::-1].index("list")
    scene = f"{filename}#/" + "/".join(
        part.replace("~", "~0").replace("/", "~1") for part in parts[: list_index + 1]
    )
    declined = _declined_scope(
        root, checkpoint, _read_json(root / "inventory.json"), waiting=True
    )
    if scene in declined["context_scenes"] and scene not in _assigned_scenes(
        checkpoint, worker
    ):
        raise ValueError(
            "A reviewer declined this scene, so context shows it only to the worker "
            "whose assigned bundle prints it, with --worker <name>."
        )
    commands = _resolve_parts(document, parts[: list_index + 1])
    if list_index + 1 < len(parts):
        center = int(parts[list_index + 1])
        start = max(0, center - radius)
        end = min(len(commands), center + radius + 1)
    else:
        center, start, end = None, 0, len(commands)
    lines = [f"{scene} commands {start}-{end - 1} of {len(commands)}"]
    for index in range(start, end):
        command = commands[index]
        if not isinstance(command, dict):
            continue
        code = blocks.code(command)
        if code in _CONTEXT_QUIET_CODES:
            continue
        mark = ">>" if index == center else "  "
        parameters = command.get("parameters")
        if code in _CONTEXT_TEXT_CODES:
            shown = [
                value for value in parameters if isinstance(value, (str, list))
            ] if isinstance(parameters, list) else parameters
            lines.append(
                f"{mark}#{index} c{code}: JP="
                + _context_text(json.dumps(command.get("_original"), ensure_ascii=False))
                + " EN=" + _context_text(json.dumps(shown, ensure_ascii=False))
            )
        else:
            lines.append(
                f"{mark}#{index} c{code}: "
                + _context_text(json.dumps(parameters, ensure_ascii=False))[:200]
            )
    return "\n".join(lines)


# Event commands whose text a rendered context shows; others print as data.
_RENDERED_TEXT_CODES = frozenset({
    101, 102, 108, 122, 320, 324, 355, 357, 401, 402, 405, 408, 655,
})


def _render_commands(commands: list[dict] | None, indent: str) -> list[str]:
    out = []
    for command in commands or []:
        if not isinstance(command, dict):
            continue
        code = blocks.code(command)
        if code in _CONTEXT_QUIET_CODES:
            continue
        parameters = command.get("parameters")
        if code in _RENDERED_TEXT_CODES:
            shown = [
                value for value in parameters if isinstance(value, (str, list))
            ] if isinstance(parameters, list) else parameters
            out.append(
                f"{indent}#{command.get('index')} c{code}: JP="
                + _context_text(json.dumps(command.get("original"), ensure_ascii=False))
                + " EN=" + _context_text(json.dumps(shown, ensure_ascii=False))
            )
        else:
            out.append(
                f"{indent}#{command.get('index')} c{code}: "
                + _context_text(json.dumps(parameters, ensure_ascii=False))[:160]
            )
    return out


def _render_hints(entry: dict, indent: str) -> list[str]:
    out = [
        indent + f"check {failed['check']}: " + _context_text(failed["note"])
        for failed in entry.get("checks") or []
    ]
    if entry.get("glossary"):
        out.append(indent + "glossary: " + "; ".join(f"{a}={b}" for a, b in entry["glossary"]))
    for alternative in entry.get("same_source_alternatives") or []:
        out.append(indent + "same JP elsewhere: " + _context_text(alternative))
    for row in entry.get("reference_translations") or []:
        out.append(indent + "reference: " + _context_text(row.get("translation")))
    if entry.get("lint"):
        out.append(
            indent + "lint (" + ", ".join(entry["lint"]["families"]) + "): "
            + _context_text(entry["lint"]["proposed"])
        )
    return out


def _render_line(line: dict, mark: str) -> list[str]:
    """One scene line, numbered by the event command that holds it, so an
    observation can name it as the scene's command list and that number."""
    number = f"#{line['command']}" if line.get("command") is not None else ""
    speaker = f"<{line['speaker']}> " if line.get("speaker") else ""
    code = f" c{line['event_code']}" if line.get("event_code") else ""
    out = [
        f"{number:>5} {mark}{code} JP: {speaker}{_context_text(line['source'])}",
        f"{'':>5}   EN: {_context_text(line['translation'])}",
    ]
    if line.get("risk"):
        out.append(f"{'':>5}   risk: " + ",".join(line["risk"]))
    if line.get("context_expansion"):
        out.append(f"{'':>5}   repeated in: " + ",".join(line["context_expansion"]))
    if line.get("choice_context"):
        labels = " | ".join(
            f"{branch['index']}:{branch['label']}"
            for branch in line["choice_context"].get("branches", [])
        )
        out.append(f"{'':>5}   choices: {labels}")
    return out + _render_hints(line, "        ")


def _render_screen_item(
    item: dict, screen_index: dict[str, dict[str, str]]
) -> list[str]:
    kind = item.get("kind")
    if kind == "scene":
        out = [(
            f"### SCENE {item['id']} {item['scene_id']} "
            f"({item['line_count']} lines, {item['target_count']} targets)"
        )]
        for line in item["lines"]:
            mark = f"[T {line['id']}]" if "id" in line else "[ctx]"
            entry = screen_index[line.get("id") or line["context_id"]]
            out += _render_line(
                {**line, "command": _command_number(entry["representative_identity"])},
                mark,
            )
        return out
    if kind == "cluster":
        meta = [f"occ={item.get('occurrences', 1)}"]
        if item.get("display_shapes"):
            meta.append("shape=" + ",".join(item["display_shapes"]))
        if item.get("speakers"):
            meta.append("speakers=" + ",".join(item["speakers"]))
        out = [f"### CLUSTER {item['id']} " + " ".join(meta)]
        if item.get("risk"):
            out.append("  risk: " + ",".join(item["risk"]))
        out += [
            "  JP: " + _context_text(item["source"]),
            "  EN: " + _context_text(item["translation"]),
        ]
        return out + _render_hints(item, "  ")
    if kind == "motif-family":
        out = [
            f"### MOTIF {item['id']} ({item['variant_count']} variants)",
            "  anchors: " + ", ".join(item["anchors"]),
            "  guidance: " + _context_text(item["guidance"]),
        ]
        for variant in item["variants"]:
            out += [
                f"  - VARIANT {variant['id']} occ={variant['occurrences']}",
                "    JP: " + _context_text(variant["source"]),
                "    EN: " + _context_text(variant["translation"]),
            ] + _render_commands(variant.get("nearby_commands"), "      ")
        if item.get("reviewed_variants"):
            out.append("  reviewed in this family before, for comparison:")
            out += [
                "  - " + _context_text(variant["source"])
                + " || " + _context_text(variant["translation"])
                for variant in item["reviewed_variants"]
            ]
        return out
    if kind == "lint-family":
        out = [f"### LINT {item['id']} {item['family']}: {item['description']}"]
        for proposal in item["proposals"]:
            speaker = f" <{proposal['speaker']}>" if proposal.get("speaker") else ""
            # The line, which an observation may name, in its scene.
            line = proposal["cluster_id"].split("@", 1)[0]
            out += [
                f"  {proposal['id']} {line}{speaker}",
                "    JP:  " + _context_text(proposal["source"]),
                "    EN:  " + _context_text(proposal["current"]),
                "    FIX: " + _context_text(proposal["proposed"]),
            ] + (["    WHY: " + proposal["note"]] if proposal.get("note") else [])
        return out
    return ["### " + json.dumps(item, ensure_ascii=False)]


def _render_boxes(places: list[dict] | None) -> list[str]:
    """The boxes an item's text shows in, such as 50 chars x 4 rows; for a
    target whose lines break between characters, in half-width cells, which
    a full-width character takes two of."""
    shown = []
    for place in places or []:
        box = place.get("box") or {}
        width = "half-width cells" if box.get("target") else "chars"
        size = " x ".join(
            f"{box[key]} {unit}"
            for key, unit in (("width", width), ("rows", "rows"))
            if box.get(key)
        )
        text = size + (", rewrapped" if box.get("wraps") else "")
        if size and text not in shown:
            shown.append(text)
    return ["  box: " + " | ".join(shown)] if shown else []


def _render_deep(bundle: dict) -> list[str]:
    out = []
    numbers = {item["id"]: number for number, item in enumerate(bundle["items"], 1)}
    for number, item in enumerate(bundle["items"], 1):
        out += [
            "",
            f"### ITEM {number} {item['id']}",
            "  deep_reasons: " + ", ".join(item.get("deep_reasons") or []),
        ]
        meta = []
        for key, label in (("risk", "risk"), ("display_shapes", "shape"),
                           ("event_codes", "codes"), ("speakers", "speakers")):
            if item.get(key):
                meta.append(f"{label}=" + ",".join(map(str, item[key])))
        listed = len(item.get("locators") or [])
        meta.append(
            f"occurrences={item.get('occurrences', listed)}"
            + (f" (listing {listed})" if item.get("occurrences", listed) != listed else "")
        )
        out.append("  " + " ".join(meta))
        out += [
            "  JP: " + _context_text(item["source"]),
            "  EN: " + _context_text(item["translation"]),
        ] + _render_boxes(item.get("target_shapes")) + _render_hints(item, "  ")
        for evidence in item.get("screen_evidence") or []:
            source = (
                "observed at " + evidence["identity"].split("@", 1)[0]
                if evidence["verdict"] == "observation"
                else f"screen [{evidence['verdict']}]"
            )
            out.append(
                f"  {source} ({','.join(evidence['categories'])}): "
                + _context_text(evidence["note"])
            )
        prior = item.get("prior_review")
        if prior:
            out.append(
                f"  earlier deep review [{prior['disposition']}]: "
                + _context_text(prior.get("evidence"))
                + (f" -> {_context_text(prior['correction'])}" if prior.get("correction") else "")
            )
        if item.get("scenes"):
            out.append("  scenes: " + ", ".join(item["scenes"]))
        if item.get("motifs"):
            out.append("  motifs: " + ", ".join(item["motifs"]))
        for locator in item.get("locators") or []:
            if len(item.get("locators") or []) == 1 and locator["identity"] == item["id"]:
                break
            extra = []
            speaker = (locator.get("speaker") or {}).get("display_name")
            if speaker:
                extra.append(f"speaker={speaker}")
            if locator.get("database_entity"):
                extra.append("entity=" + json.dumps(locator["database_entity"], ensure_ascii=False))
            if locator.get("database_values"):
                extra.append("values=" + ",".join(locator["database_values"]))
            out.append(f"  - {locator['identity']} " + " ".join(extra))
        if item.get("nearby_commands"):
            out.append("  nearby:")
            out += _render_commands(item["nearby_commands"], "    ")
        for context in item.get("suspect_contexts") or []:
            out.append(f"  around {context['identity']}:")
            out += _render_commands(context["nearby_commands"], "    ")
    for key, scene in (bundle.get("scenes") or {}).items():
        out += ["", f"## SCENE {key} {scene['scene_id']} ({len(scene['lines'])} lines)"]
        for line in scene["lines"]:
            named = [str(numbers[item]) for item in line.get("items") or [] if item in numbers]
            mark = (">>ITEM " + ",".join(named)) if named else "  "
            out += _render_line(line, mark)
    for motif_id, motif in (bundle.get("motifs") or {}).items():
        out += [
            "",
            f"## MOTIF {motif_id} {motif.get('disposition', '')}",
            "  guidance: " + _context_text(motif.get("guidance")),
            "  screen note: " + _context_text(motif.get("note")),
        ]
        for variant in motif.get("variants") or []:
            out.append(
                "  - " + _context_text(variant.get("source"))
                + " || " + _context_text(variant.get("translation"))
            )
    return out


def _render_group(item: dict) -> list[str]:
    rule = item["rule"]
    out = [
        f"### SWEEP {item['id']} {item['family_key']}: "
        f"{rule['find']!r} -> {rule['replace']!r}"
        + (f" where the source has {rule['source_has']!r}" if rule.get("source_has") else ""),
        "  accepted: JP " + _context_text(item["example"]["source"]),
        "            EN " + _context_text(item["example"]["current"]),
        "           FIX " + _context_text(item["example"]["correction"]),
        "        reason " + _context_text(item["example"]["evidence"]),
    ]
    for candidate in item["candidates"]:
        speaker = f" <{candidate['speaker']}>" if candidate.get("speaker") else ""
        out += [
            f"  {candidate['id']} {candidate['scene']}{speaker}",
            "    JP:  " + _context_text(candidate["source"]),
            "    EN:  " + _context_text(candidate["current"]),
            "    FIX: " + _context_text(candidate["proposed"]),
        ]
    return out


def _render_editorial(item: dict) -> list[str]:
    finding = item["finding"]
    scene = finding.get("kind") == "scene"
    out = [
        f"### FINDING {item['id']} [{finding['severity']} {finding['category']}] "
        f"{finding.get('family_key', '')} occurrences={item['occurrences']}"
        + (f" SCENE CORRECTION of {len(finding['lines'])} lines" if scene else ""),
    ]
    if not scene:
        out += [
            "  JP:  " + _context_text(finding["source"]),
            "  EN:  " + _context_text(finding["current"]),
            "  FIX: " + _context_text(finding["correction"]),
        ]
    out += _render_boxes(item.get("targets"))
    out.append("  evidence: " + _context_text(finding["evidence"]))
    basis = finding.get("editorial_basis")
    if basis:
        out += [
            "  defect: " + _context_text(basis["defect"]),
            "  support: " + _context_text(basis["source_support"]),
        ]
    for conflict in item.get("conflicts") or []:
        out.append(f"  CONFLICT ({conflict['kind']}): " + conflict["message"])
    for place in item.get("after") or []:
        if "error" in place:
            out.append("  corrected screen: " + place["error"])
        elif place.get("clipped") or place.get("squeezed"):
            out.append("  corrected screen, still too long: " + _place_text(place))
        else:
            out.append(f"  corrected screen, fits: {place['title']}: {place['capture']}")
    if not scene:
        return out + _render_commands(item.get("nearby_commands"), "    ")
    # The whole scene, each changed line marked with its correction.
    fixes = {line["position"]: line["correction"] for line in finding["lines"]}
    out.append(f"  scene {finding['scene_id']} ({len(item['scene'])} lines):")
    for position, line in enumerate(item["scene"]):
        out += _render_line(line, ">>FIX" if position in fixes else "  ")
        if position in fixes:
            out.append(f"{'':>5}   FIX: {_context_text(fixes[position])}")
    return out


def render_bundle(task_dir: str | Path, bundle_id: str) -> str:
    """A bundle as compact text: what a reviewer reads instead of its JSON."""
    root, task, checkpoint = _load_task(task_dir)
    stage, row = _bundle_row(checkpoint, bundle_id)
    if row["status"] == "split":
        raise ValueError(_split_notice(row))
    bundle = _read_json(Path(row["path"]))
    # A follow-up or check bundle carries the index entries the task's lacks.
    screen_index = (
        {**_load_screen_index(root, task), **(bundle.get("screen_index") or {})}
        if stage == "screen" else {}
    )
    out = [(
        f"BUNDLE {bundle_id} ({stage}, {bundle['item_count']} targets, "
        f"sha256 {bundle['content_sha256']}). Newlines show as ⏎."
    )]
    if stage == "deep":
        out += _render_deep(bundle)
    else:
        for item in bundle["items"]:
            out.append("")
            if stage == "screen":
                out += _render_screen_item(item, screen_index)
            elif stage == "sweep":
                out += _render_group(item)
            else:
                out += _render_editorial(item)
    out += _glossary_section(root, bundle)
    return "\n".join(out) + "\n"


def _bundle_wording(value: Any, japanese: list[str], names: set[str]) -> None:
    """Collect a bundle's Japanese and the speaker names it shows."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source", "original"}:
                japanese.append(
                    item if isinstance(item, str)
                    else json.dumps(item, ensure_ascii=False)
                )
            elif key == "speaker":
                name = item.get("display_name") if isinstance(item, dict) else item
                if name:
                    names.add(str(name))
            elif key == "speakers" and isinstance(item, list):
                names.update(str(name) for name in item if name)
            else:
                _bundle_wording(item, japanese, names)
    elif isinstance(value, list):
        for item in value:
            _bundle_wording(item, japanese, names)


def _glossary_section(root: Path, bundle: dict[str, Any]) -> list[str]:
    """The glossary entries whose Japanese a bundle holds, or whose English
    names one of its speakers, so a reviewer needs no other glossary."""
    japanese: list[str] = []
    names: set[str] = set()
    _bundle_wording(bundle, japanese, names)
    text = "\n".join(japanese)
    glossary = (_read_json(root / "context.json").get("glossary") or {}).get("text")
    used = [
        line for terms, english, line in _glossary_entries(glossary)
        if names.intersection(english)
        or any(glossary_rules.mentions(text, term) for term in terms)
    ]
    return ["", "## GLOSSARY entries for this bundle's text", *used] if used else []
