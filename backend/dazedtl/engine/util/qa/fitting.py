"""How corrections fit the game's windows: task layouts, the written form of
a correction, the problems it would cause, and the writes an operation
makes."""

from __future__ import annotations

import copy
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from util import rpgmaker_blocks as blocks
from util import rpgmaker_rewrap as rewrap
from util import rpgmaker_script_strings as script_strings
from util.game_settings import game_wrap_widths, normalize_wrap_widths
from util.qa import mechanical
from util.qa.schema import _QUOTED_VALUE_RE, ADDED_BATTLER_NAME
from util.rpgmaker_qa_manifest import (
    QUOTED_TRANSFORMS,
    SCRIPT_STRINGS,
    resolve_pointer,
)
from util.rpgmaker_rewrap import rendered_rows, widest_line

APPROVED_NONBLOCKING_MECHANICAL_FLAGS = frozenset({"suspicious-length-ratio"})


def task_layout(
    game_root: str | Path, fit: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The Line widths a task fits corrections to. The app passes its own;
    without them a task reads the game's saved widths."""
    fit = fit or {}
    return {
        "widths": normalize_wrap_widths(
            fit.get("widths") or game_wrap_widths(game_root)
        ),
    }


def _window(record: dict[str, Any], layout: dict[str, Any]) -> rewrap.Box | None:
    """The window a record's text shows in, as DazedTL fits text to it, or
    None when nothing known limits the text."""
    widths = rewrap.Layout.from_widths(layout["widths"])
    code = record.get("event_code")
    field = (record.get("database_entity") or {}).get("field")
    source = str(record.get("source") or "")
    if code == 401:
        face = str((record.get("speaker") or {}).get("face_name") or "").strip()
        return rewrap.message_box(widths, face=bool(face))
    if code == 408 and record.get("choice_help"):
        return rewrap.choice_help_box(widths, face=record["choice_help"]["face"])
    if code == 405:
        return rewrap.scrolling_box(widths)
    if code == 324:
        return rewrap.nickname_box(widths)
    if code == 122 and record["live_transform"] in _SCRIPT_QUOTES:
        return rewrap.variable_box(widths)
    if code == 325:
        return rewrap.help_box(widths, source, dialogue=True)
    if code == 357:
        plugin = (record.get("risky_context") or {}).get("plugin_header") or ""
        key = record["live_pointers"][0].rsplit("/", 1)[-1]
        if key in rewrap.MESSAGE_PLUGIN_TEXT.get(plugin, ()):
            return rewrap.message_box(widths)
        return None
    if code is None and field in rewrap.LIST_FIELDS_BY_FILE.get(record["file"], ()):
        return rewrap.help_box(widths, source)
    if code is None and field == "note":
        return rewrap.note_box(widths)
    return None


def _box(record: dict[str, Any], layout: dict[str, Any]) -> dict[str, Any] | None:
    """The box a record's text shows in, by the task's Line widths: its width,
    the rows it shows, whether a message goes on to a new page after them, and
    whether DazedTL rewraps a correction to it. None when nothing limits the
    text."""
    window = _window(record, layout)
    if window is None:
        return None
    box: dict[str, Any] = {"width": window.width, "kind": window.kind}
    if window.rows:
        box["rows"] = window.rows
    if window.paged:
        box["pages"] = True
    # A message or a choice's help spread over several commands is fitted
    # and spread over them again (rpgmaker_rewrap.spread); other text spread
    # over several commands, such as a script, keeps its line structure. A text
    # variable's script string is wrapped once escaped (see _as_written).
    box["wraps"] = window.kind == "variable" or (
        record["live_transform"] == "identity"
        and (len(record["live_pointers"]) == 1 or _message_record(record))
    )
    # A choice's help shows with the rest of its comment, whose rows count
    # with its own; inventories made before they were kept have none.
    if comment := (record.get("choice_help") or {}).get("comment"):
        box["help"] = comment
    return box


def _message_record(record: dict[str, Any]) -> bool:
    """Whether a record's commands hold the rows of a message or a choice's
    help, which DazedTL fits as a whole however many commands hold its
    rows."""
    return record.get("event_code") in (401, 405) or bool(record.get("choice_help"))


def _fit_window(box: dict[str, Any]) -> rewrap.Box:
    """The fitter's window for a box. A correction is never paged: one taller
    than its message window is refused instead."""
    rows = None if box.get("pages") else box.get("rows")
    return rewrap.Box(box["width"], rows, False, box.get("kind", "message"))


def _widens(correction: str, live: str, width: int) -> bool:
    """Whether a correction has a line wider than both its box and the current
    text."""
    return widest_line(correction) > max(width, widest_line(live))


def _spread_over(event_code: int | None, live_pointers: list[str]) -> int:
    """The commands a text is laid over as written: a message keeps the rows
    it no longer needs, empty, while a choice's help (408) moves them out of
    it (see rpgmaker_blocks.write_help)."""
    return 1 if event_code == 408 else len(live_pointers)


def _fit(
    correction: str,
    live: str,
    box: dict[str, Any] | None,
    source: str | None = None,
    commands: int = 1,
) -> str:
    """A correction as DazedTL writes it: wrapped again, as translation wraps
    it, when a line does not fit its box, and as it reads once spread over
    the *commands* that hold the text."""
    if not box or not box.get("wraps"):
        return correction
    fitted = rewrap.fit_value(correction, _fit_window(box), source=source)
    return "\n".join(rewrap.spread(fitted, commands))


# The quote mark of each script string transform.
_SCRIPT_QUOTES = {transform: quote for quote, transform in SCRIPT_STRINGS.items()}
# A line break a script string's text would read as the start of a name code,
# such as \n[1] or \n<name>, once written as "\n" (see
# rpgmaker_script_strings.BREAK).
_BREAK_BEFORE_CODE = re.compile(rf"\n(?={script_strings.NAME_CODE})")


def _as_written(
    correction: str,
    live: str,
    box: dict[str, Any] | None,
    source: str | None,
    commands: int,
    transform: str,
) -> str:
    """A correction as DazedTL writes it in place of *live*. Plain text is
    fitted to its box (see _fit). Into a script string it goes with the
    escapes translation writes there, so it can't end the string early or
    interpolate in it, except in an interpolation the target's current text
    runs, such as the hero's name; then it is wrapped to its box as the
    fitter wraps a text variable.

    The source's own interpolations don't count: a source between quote
    marks that don't interpolate, such as '${x}', shows its ${x} as text,
    which translation wrote escaped, and running it would stop the game."""
    quote = _SCRIPT_QUOTES.get(transform)
    if not quote:
        return _fit(correction, live, box, source, commands)
    text = script_strings.escape(
        correction, quote, script_strings.interpolated(quote, live)
    )
    if box and box.get("wraps"):
        text = rewrap.wrap_variable(quote + text + quote, box["width"])[1:-1]
    return text


def _fitted(
    correction: str,
    live: str,
    targets: list[dict[str, Any]],
    layout: dict[str, Any],
) -> str:
    """One correction for every target it reaches, as findings keep it:
    fitted to the narrowest box when each target is plain text DazedTL
    rewraps, so the page shows the rows the game gets; otherwise as its
    reviewer wrote it. Each target gets it as DazedTL writes it there (see
    _written), so a script string's escapes go in once, as it is written."""
    if any(target["live_transform"] != "identity" for target in targets):
        return correction
    boxes = [_box(target, layout) for target in targets]
    if not boxes or not all(box and box.get("wraps") for box in boxes):
        return correction
    narrowest = min((box for box in boxes if box), key=lambda box: box["width"])
    return _fit(correction, live, narrowest, targets[0].get("source"))


def _fit_corrections(
    findings: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    clusters: dict[str, dict[str, Any]],
    layout: dict[str, Any],
) -> None:
    """Write each correction and proposal as DazedTL applies it, so findings
    show the text the game gets; *questions* also holds the lines reported
    as not corrected, which only show their text."""
    for finding in findings:
        if finding.get("kind") == "show-text":
            continue
        scene = finding.get("kind") == "scene"
        for change in finding["lines"] if scene else [finding]:
            identities = change["identities"] if scene else finding["target_identities"]
            targets = [records[identity] for identity in identities]
            change["correction"] = _fitted(
                change["correction"], change["current"], targets, layout
            )
            if shown := _shown(change, targets, layout):
                change["shown"] = shown
    for question in questions:
        targets = [
            records[identity] for identity in clusters[question["id"]]["identities"]
        ]
        if question.get("correction"):
            question["correction"] = _fitted(
                question["correction"], question["current"], targets, layout
            )
        # A line without a proposal still shows its Japanese and current text.
        if shown := _shown(question, targets, layout):
            question["shown"] = shown


def _shown(
    change: dict[str, Any], targets: list[dict[str, Any]], layout: dict[str, Any]
) -> dict[str, str] | None:
    """A text variable's Japanese, current text and any correction as the
    Text QA page shows them, all as their text reads (see
    script_strings.text): its Japanese and current text hold the script
    string's escapes, while findings keep its correction as its reviewer
    wrote it, so the page would show escapes as changes. The correction reads
    as the game gets it, wrapped to the list width. None for other text,
    which the page shows as findings keep it."""
    quotes = {_SCRIPT_QUOTES.get(target["live_transform"], "") for target in targets}
    if len(quotes) != 1 or "" in quotes:
        return None
    (quote,) = quotes
    return {
        # The original script's escapes, which JavaScript reads alike in any
        # string and Ruby in its own.
        "source": script_strings.text(change["source"], quote),
        "current": script_strings.text(change["current"], quote),
        **(
            {
                "correction": script_strings.text(
                    _written(targets[0], change["correction"], layout), quote
                )
            }
            if change.get("correction")
            else {}
        ),
    }


def _record_problems(
    record: dict[str, Any],
    correction: str,
    layout: dict[str, Any],
    allowed: frozenset[str] = frozenset(),
) -> list[str]:
    """Why one correction of an inventory record would block apply."""
    return correction_problems(
        record["source"], record["live"], correction, record.get("event_code"),
        record["live_pointers"], record["live_transform"], allowed,
        box=_box(record, layout),
    )


def correction_problems(
    source: str,
    live: str,
    correction: str,
    event_code: int | None,
    live_pointers: list[str],
    live_transform: str,
    allowed: frozenset[str] = frozenset(),
    *,
    box: dict[str, Any] | None,
) -> list[str]:
    """Why applying one correction would fail or trip the post-apply regression.

    This simulates the apply step for one target: the line structure its
    pointers need, the rows its box shows, and the mechanical flags the
    regression treats as blocking. DazedTL writes the correction fitted to
    the box, which may not need more rows than the box shows or the current
    text uses; a correction it cannot rewrap may not have a line wider than
    both the box and the current text. Into a script string it writes the
    correction escaped as translation writes the string (see _as_written).
    """
    problems = []
    written = _as_written(
        correction, live, box, source, _spread_over(event_code, live_pointers),
        live_transform,
    )
    if written == live:
        problems.append("the correction matches the current text")
    lines = correction.split("\n")
    if live_transform in _SCRIPT_QUOTES and _BREAK_BEFORE_CODE.search(correction):
        # Written as "\n", the break would start a code such as \n[1] instead.
        problems.append(
            'a line break right before "[" or "<" reads as a name code in a '
            "script string; move or drop the break"
        )
    if live_transform == "quoted-string":
        # The text sits between quote marks in a script parameter whose
        # escapes are unknown, so a new kind of quote mark could end the
        # string early.
        if any(mark in correction and mark not in live for mark in "'\"`"):
            problems.append("adds a quote mark to a script string")
    elif (
        len(live_pointers) > 1 and not (box and box.get("wraps"))
        and len(lines) != len(live_pointers)
    ):
        problems.append(
            f"needs {len(live_pointers)} lines like the current text, "
            f"not {len(lines)}"
        )
    elif event_code in {101, 102} and "\n" in correction:
        problems.append("a name or choice cannot contain a line break")
    elif box and box.get("help") and box.get("rows"):
        # The window shows the rest of the help with it (see _box).
        rows = rendered_rows(blocks.help_shown(box["help"], written.split("\n")))
        if rows > max(rendered_rows(blocks.help_shown(box["help"])), box["rows"]):
            problems.append(
                f"needs {rows} rows with the rest of its choice help; its window "
                f"shows {box['rows']}"
            )
    elif box and box.get("rows"):
        rows = rendered_rows(written)
        if rows > max(rendered_rows(live), box["rows"]):
            window = "a message window" if event_code == 401 else "its window"
            problems.append(f"needs {rows} rows; {window} shows {box['rows']}")
    if (
        box and box.get("width") and not box.get("wraps")
        and _widens(correction, live, box["width"])
    ):
        problems.append(
            f"has a line {widest_line(correction)} characters wide; its line "
            f"width is {box['width']}"
        )
    before = set(mechanical.evidence(source, live, event_code)["flags"])
    after = set(mechanical.evidence(source, written, event_code)["flags"])
    introduced = sorted(_disallowed_flags(
        after - before - APPROVED_NONBLOCKING_MECHANICAL_FLAGS, allowed,
        source, written,
    ))
    if introduced:
        problems.append("introduces " + _flag_details(introduced, source, written))
    return problems


def _flag_details(flags: Iterable[str], source: str, text: str) -> str:
    """*flags* for a reviewer, with the runtime codes a token mismatch
    changes, so the next correction can keep them."""
    return ", ".join(
        f"{flag} ({_token_difference(source, text)})"
        if flag == "runtime-token-mismatch" else flag
        for flag in flags
    )


def _token_difference(source: str, text: str) -> str:
    """How *text* changes *source*'s runtime codes, as the token check
    compares them (see rpgmaker_qa_manifest._runtime_tokens_match)."""
    source_starts, source_codes = mechanical.row_codes(source)
    starts, codes = mechanical.row_codes(text)
    parts = []
    for verb, difference in (
        ("drops", source_codes - codes), ("adds", codes - source_codes)
    ):
        if difference:
            parts.append(f"{verb} " + " ".join(sorted(difference.elements())))
    if starts != source_starts:
        shown = lambda runs: " / ".join("".join(run) or "no code" for run in runs)
        parts.append(
            f"its rows start with {shown(starts)} where the source's start "
            f"with {shown(source_starts)}"
        )
    return "; ".join(parts)


def _adds_only_battler_name(source: str, text: str) -> bool:
    """Whether a text keeps its source's runtime codes and adds only the %1
    the source lacks."""
    evidence = mechanical.evidence(source, text, None)
    source_tokens = Counter(evidence["source_runtime_tokens"])
    text_tokens = Counter(evidence["live_runtime_tokens"])
    return (
        "%1" not in source_tokens
        and text_tokens - source_tokens == Counter({"%1": 1})
        and not source_tokens - text_tokens
    )


def _disallowed_flags(
    introduced: set[str], allowed: Iterable[str], source: str, text: str
) -> set[str]:
    """The introduced flags no allowance covers; a battler-name allowance
    covers a runtime-token mismatch only from the one %1 it adds."""
    allowed = set(allowed)
    left = introduced - allowed
    if (
        ADDED_BATTLER_NAME in allowed
        and "runtime-token-mismatch" in left
        and _adds_only_battler_name(source, text)
    ):
        left.discard("runtime-token-mismatch")
    return left


def _written(
    record: dict[str, Any], text: str, layout: dict[str, Any] | None
) -> str:
    """The text a correction leaves in a record under the task's Line widths
    *layout*, as DazedTL writes it there (see _as_written), and a message's
    rows spread over the commands that hold them.

    Findings keep a correction as its reviewer wrote it, fitted only to the
    boxes all its targets share, so it is escaped once, here: escaping
    escaped text again would turn a line break before "<" into a name
    code."""
    rows = _spread_over(record.get("event_code"), record["live_pointers"])
    text = _as_written(
        text,
        str(record.get("live") or ""),
        _box(record, layout) if layout else None,
        record.get("source"),
        rows,
        record["live_transform"],
    )
    if rows > 1 and _message_record(record):
        return "\n".join(rewrap.spread(text, rows))
    return text


def _operation_writes(document: Any, operation: dict) -> list[tuple[str, Any]]:
    """The pointers one operation writes, after checking it still finds the
    value it was approved against."""
    if operation.get("kind") == "show-text":
        if resolve_pointer(document, operation["pointer"]) != operation["expected"]:
            raise ValueError(
                f"Expected Show Text header changed for {operation['finding_id']}; rebuild QA"
            )
        return [(operation["pointer"], operation["replacement"])]
    help_rows = _help_rows(document, operation)
    if help_rows is not None:
        return help_rows
    values = _operation_values(document, operation)
    current = "\n".join(values)
    if operation["live_transform"] in QUOTED_TRANSFORMS:
        match = _QUOTED_VALUE_RE.search(current)
        current = match.group(2) if match else current
    if current != operation["expected"]:
        raise ValueError(
            f"Expected value changed for {operation['identity']}; rebuild QA"
        )
    return list(zip(operation["live_pointers"], _operation_replacements(values, operation)))


def _help_rows(document: Any, operation: dict) -> list[tuple[str, Any]] | None:
    """The commands a correction of a choice's help writes, as translation
    writes help (see rpgmaker_blocks.write_help): over the rows its
    translation owns now, which an earlier correction may have changed,
    moving the rows it no longer needs past the game's own; None for other
    text."""
    pointers = operation.get("live_pointers") or []
    if operation.get("live_transform") != "identity" or not pointers:
        return None
    listed, _slash, place = pointers[0].rpartition("/parameters/0")
    listed, _slash, index = listed.rpartition("/")
    if place or not index.isdigit():
        return None
    try:
        commands = resolve_pointer(document, listed)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    anchor = int(index)
    if (
        not isinstance(commands, list)
        or anchor >= len(commands)
        or blocks.code(commands[anchor]) != 408
        or "_original" not in commands[anchor]
        or blocks.help_branch(commands, anchor) is None
    ):
        return None
    rows = blocks.owned(commands, anchor)
    if "\n".join(blocks.text(commands[at]) for at in rows) != operation["expected"]:
        raise ValueError(
            f"Expected value changed for {operation['identity']}; rebuild QA"
        )
    # The rows it writes and moves: its own and the comment's after them.
    start, stop = rows[0], (blocks.run(commands, rows[-1], 408) or rows)[-1] + 1
    written = copy.deepcopy(commands[start:stop])
    blocks.write_help(
        written, tuple(at - start for at in rows), operation["replacement"].split("\n")
    )
    return [
        (f"{listed}/{start + at}", command)
        for at, (command, before) in enumerate(zip(written, commands[start:stop]))
        if command != before
    ]


def _operation_values(document: Any, operation: dict) -> list[str]:
    return [resolve_pointer(document, pointer) for pointer in operation["live_pointers"]]


def _operation_replacements(values: list[str], operation: dict) -> list[str]:
    replacement = operation["replacement"]
    transform = operation["live_transform"]
    if transform in QUOTED_TRANSFORMS:
        if len(values) != 1:
            raise ValueError("Quoted-string operation has multiple live pointers")
        match = _QUOTED_VALUE_RE.search(values[0])
        if not match:
            raise ValueError("Quoted-string live value no longer contains a quoted value")
        return [values[0][: match.start(2)] + replacement + values[0][match.end(2) :]]
    if len(values) == 1:
        return [replacement]
    if operation.get("message"):
        return rewrap.spread(replacement, len(values))
    lines = replacement.split("\n")
    if len(lines) != len(values):
        raise ValueError(
            f"Replacement for {operation['identity']} must have {len(values)} lines"
        )
    return lines
