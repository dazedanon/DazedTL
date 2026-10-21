"""Preserved fitting and QA validators, with app-owned runtime publication."""

import difflib
import json
import shutil
import traceback
from datetime import datetime
from pathlib import Path

from dazedtl import system
from dazedtl.storage import write_json
from dazedtl.translation import publication
from dazedtl.translation.files import decode_json, digest, project_path, read_json

# Where each QA stage stands for the page's activity line.
ACTIVITY_STAGES = ("screen", "deep", "sweep", "editorial")


def _finding_kind(row):
    """How a finding came to be, for the audit log's grouping."""
    if row.get("kind") == "show-text" or row.get("source_fix"):
        return "source"
    if row.get("kind") == "scene":
        return "scene"
    if row.get("lint_only"):
        # A glossary term reads as the glossary's, not as a mechanical fix.
        if "lint:glossary-term" in (row.get("lint_families") or []):
            return "glossary"
        return "lint"
    if row.get("sweep_families"):
        return "sweep"
    return "review"


def binding(plan):
    guard = {
        key: value
        for key, value in plan["guard"].items()
        if key not in {"files", "translated", "variables"}
    }
    index = Path(plan["folder"]) / "source-inputs.json"
    return {
        "source": plan["project"]["source"],
        "project": plan["project_id"],
        "guard": guard,
        "source_inputs": digest(index.read_bytes()) if index.exists() else None,
    }


def qa_handoff(task, helper="project.py qa"):
    """The text a coding assistant receives for one prepared QA task, from
    the QA policy that also makes its README."""
    from util import rpgmaker_qa as qa

    return qa.handoff_text(task, helper)


def qa_selection(state, action, options):
    """The findings and chosen proposals an apply or undo names, each in the
    state that step needs: applied for an undo, and for an apply not in the
    game, whether never applied, such as a follow-up round's, or undone."""
    chosen = options.get("findings", [])
    proposals = options.get("proposals", [])
    if (
        not isinstance(chosen, list)
        or not isinstance(proposals, list)
        or not chosen + proposals
        or len(set(chosen + proposals)) != len(chosen + proposals)
        or any(not isinstance(value, str) for value in chosen + proposals)
    ):
        raise ValueError("Choose the corrections to apply or undo.")
    states = {row["id"]: row.get("state", "") for row in state["findings"]}
    # A proposal the user chose applies and undoes like a finding.
    states.update(
        (row["id"], row.get("state", ""))
        for row in state["questions"]
        if row.get("choice") == "use"
    )
    found = [states.get(value, "missing") for value in chosen + proposals]
    if "missing" in found:
        raise ValueError("The chosen QA corrections changed. Refresh findings.")
    if action == "qa_undo" and any(value != "applied" for value in found):
        raise ValueError("Only applied corrections can be undone.")
    if action == "qa_apply" and "applied" in found:
        raise ValueError("Those QA corrections are already applied.")
    return chosen, proposals


def _pointer(plan):
    """The record naming the focus's prepared task."""
    return Path(plan["folder"]) / (
        "text-qa-" + plan["options"].get("focus", "release") + ".json"
    )


def _task_folder(plan, saved):
    """The task folder a pointer names, inside QA's storage."""
    return _stored_task(plan["folder"], saved["task"])


def _stored_task(folder, task):
    """A task folder inside the game workspace's QA storage, by its path."""
    storage = Path(folder) / "text-qa"
    relative = Path(task).relative_to(storage)
    return project_path(storage, relative.as_posix(), exists=False)


# Where 2.24.0 and earlier kept the user's answers to QA's questions, by task.
EARLIER_ANSWERS = "text-qa-choices.json"


def adopt_answers(folder):
    """Copies the answers 2.24.0 and earlier kept in the game workspace into
    their tasks, whose ledgers read them there, so a line the user kept reads
    reviewed. The file stays, since going back to 2.24.0 reads it, and an
    answer the task already holds, given since, wins over it."""
    from util import rpgmaker_qa as qa

    try:
        earlier = read_json(Path(folder) / EARLIER_ANSWERS)
    except ValueError, OSError:
        return
    for task, choices in earlier.items() if isinstance(earlier, dict) else ():
        try:
            root = _stored_task(folder, task)
            if not root.is_dir():
                continue
            saved = qa.answers(root)
            for question, choice in choices.items():
                if question not in saved and choice in qa.ANSWERS:
                    qa.answer(root, question, choice)
        # A task gone, broken or out of reach now holds no review to build on.
        except ValueError, OSError, AttributeError:
            continue


def _failure(error):
    """An error as raised, such as "PermissionError: [Errno 13] ..."."""
    return "".join(traceback.format_exception_only(error)).strip()


def qa_unreadable(plan, error):
    """A prepared task the app can't use, which reads as blocked: why, in the
    user's words, and for the helper where and what failed."""
    try:
        path = str(_task_folder(plan, read_json(_pointer(plan))))
    except ValueError, OSError, KeyError, TypeError:
        path = str(_pointer(plan))
    return {
        "current": False,
        "applied": False,
        "status": {},
        "findings": [],
        "questions": [],
        "unreadable": {"path": path, "error": _failure(error)},
        "message": "DazedTL isn't allowed to read this QA task's files."
        if isinstance(error, PermissionError)
        else "This QA task's files are missing."
        if isinstance(error, FileNotFoundError)
        else "This QA task's files are damaged or were changed outside DazedTL.",
    }


def _prepared(plan):
    """The task the pointer names, its checkpoint and its saved findings,
    once its evidence checks out; raises when the app can't read or trust it."""
    from util import rpgmaker_qa as qa

    saved = read_json(_pointer(plan))
    task_path = _task_folder(plan, saved)
    immutable = saved.get("immutable", {})
    if set(immutable) != {
        "task.json",
        "inventory.json",
        "context.json",
        "screen-index.json",
    } or any(
        digest((task_path / name).read_bytes()) != expected
        for name, expected in immutable.items()
    ):
        raise ValueError(
            "The immutable QA task evidence changed. Prepare current QA before using these reports."
        )
    # A task from before an update still shows what it found and applies it;
    # only one in review under an older rules version stops.
    root, task, checkpoint = qa.read_task(task_path)
    if (
        task["game_root"] != plan["project"]["source"]
        or task["data_root"] != plan["project"]["data"]
    ):
        raise ValueError("The QA task belongs to another project.")
    document = (
        read_json(root / "findings.json") if (root / "findings.json").exists() else {}
    )
    if document and (
        document.get("schema") != qa.FINDINGS_SCHEMA
        or document.get("task_sha256") != qa.task_sha256(task)
    ):
        raise ValueError("Saved findings belong to another QA task.")
    return saved, root, task, checkpoint, document


def _set_aside(plan, log):
    """Moves a prepared task the app can't use beside the others, so
    preparing again makes a fresh task instead of returning that one."""
    if not _pointer(plan).exists():
        return
    try:
        _prepared(plan)
        return
    except (ValueError, OSError, KeyError, TypeError) as error:
        failure = _failure(error)
    try:
        folder = _task_folder(plan, read_json(_pointer(plan)))
    except ValueError, OSError, KeyError, TypeError:
        # Preparing replaces a pointer that can't be read.
        return
    if not folder.is_dir():
        return
    number, target = 1, folder.with_name(folder.name + "-unreadable")
    while target.exists():
        number += 1
        target = folder.with_name(f"{folder.name}-unreadable-{number}")
    try:
        system.rename(folder, target)
    except OSError as error:
        raise ValueError(
            "Couldn't set the unreadable QA task aside. Close programs using its "
            "files, then try again."
        ) from error
    log(f"Set aside {folder} as {target.name}: {failure}")


def qa_state(plan):
    from util import rpgmaker_qa as qa

    from dazedtl.plugins.service import kept_settings

    if not _pointer(plan).exists():
        return {
            "current": False,
            "applied": False,
            "status": {},
            "findings": [],
            "questions": [],
            "message": "No QA task prepared for this focus.",
        }
    adopt_answers(plan["folder"])
    saved, root, task, checkpoint, document = _prepared(plan)
    # A finished task stays current through any update.
    rules_changed = qa.rules_changed(task, checkpoint)
    now = binding(plan)
    current = saved["binding"] == now and not rules_changed
    # Only the game's plugins changed, as after a playtest fix or a Plugin
    # files apply: preparing again captures the screens again and keeps the
    # review, which the copied task's assistant does after its own fixes.
    plugins_changed = (
        not current
        and not rules_changed
        and _beside_plugins(saved["binding"]) == _beside_plugins(now)
    )
    if current:
        # Plugin files decides what it keeps in Japanese without changing the
        # game's files; the never-translated report follows its decisions.
        qa.refresh_kept(root, kept_settings(plan["project"]["source"]))
    # Batches applied or undone from this task, oldest first; a restored one
    # counts for neither. Records saved before batches named their task count
    # when made after it was prepared.
    prepared = datetime.fromisoformat(task["created_at"]).timestamp()
    rows = [
        row
        for row in publication.history(plan["folder"])
        if row["kind"] in {"qa_apply", "qa_undo"}
        and row["state"] == "complete"
        and (row["task"] == str(root) if "task" in row else row["created"] >= prepared)
    ]
    every = [row["id"] for row in document.get("findings", [])]
    applied_ids, undone_ids = set(), set()
    for row in sorted(rows, key=lambda row: row["created"]):
        named = set(row.get("findings") or every)
        if row["kind"] == "qa_apply":
            applied_ids |= named
            undone_ids -= named
        else:
            undone_ids |= named

    def finding_state(identity):
        return (
            "undone"
            if identity in undone_ids
            else "applied"
            if identity in applied_ids
            else ""
        )

    def shown(row, key):
        """A finding's text as the page shows it: a text variable's as it
        reads rather than as its script holds it."""
        return (row.get("shown") or {}).get(key, row.get(key, ""))

    findings = []
    for row in document.get("findings", []):
        targets = row.get("target_identities") or []
        files = sorted(
            {identity.split("#", 1)[0] for identity in targets}
            or ({row["file"]} if row.get("file") else set())
        )
        # A scene correction's lines, which apply and undo together.
        lines = [
            {key: line[key] for key in ("source", "current", "correction")}
            for line in row.get("lines") or []
        ]
        findings.append(
            {
                "id": row["id"],
                **{
                    key: "\n".join(line[key] for line in lines)
                    if lines
                    else shown(row, key)
                    for key in ("source", "current", "correction")
                },
                "category": row["category"],
                "severity": row["severity"],
                "family": row.get("family_key") or "",
                "kind": _finding_kind(row),
                "places": max(1, len(targets)),
                "files": files,
                "reason": reason(row),
                **({"lines": lines} if lines else {}),
                **(
                    {"state": finding_state(row["id"])}
                    if finding_state(row["id"])
                    else {}
                ),
            }
        )
    choices = qa.answers(root)
    questions = [
        {
            "id": row["id"],
            "source": shown(row, "source"),
            "current": shown(row, "current"),
            "reason": reason(row),
            "places": int(row.get("places") or 1),
            "proposal": shown(row, "correction"),
            **({"choice": choices[row["id"]]} if row["id"] in choices else {}),
            **({"state": finding_state(row["id"])} if finding_state(row["id"]) else {}),
        }
        # A question without a proposal, which older tasks made, could only
        # be kept: QA reports it as not corrected instead.
        for row in document.get("uncertain_playtests", [])
        if row.get("correction")
    ]
    engine_status = qa.status(root)
    stage = engine_status.get("stage", "")
    # Its corrections are in the game once one was applied and nothing QA
    # made since, such as a follow-up round's finding, waits to be.
    applied = (
        any(row["kind"] == "qa_apply" for row in rows)
        and stage == "complete"
        and all(row.get("state") for row in findings)
        and all(row.get("choice") == "keep" or row.get("state") for row in questions)
    )
    activity = {}
    if stage in ACTIVITY_STAGES:
        counts = engine_status[stage]
        done = counts["accepted"]
        total = (
            max(counts["total"], counts.get("projected", 0))
            if stage == "deep"
            else counts["total"]
        )
        if stage == "screen":
            # Second screens of accepted lines are screening work too.
            checks = counts.get("checks") or {}
            done += checks.get("accepted", 0)
            total += checks.get("projected", 0)
        lint = engine_status["screen"]["lint"]
        if stage == "screen" and lint["accepted"] + lint["declined"] < lint["total"]:
            # Lint families lead the screen bundles; the line names them
            # until every proposal is reviewed or declined.
            stage, done, total = "lint", lint["accepted"], lint["total"]
        estimate = engine_status["estimate"]
        # A round prepared only for observed lines has nothing to screen
        # until its first bundle moves it on: no "Screening 0 of 0".
        activity = (
            {}
            if not total
            else {
                "stage": stage,
                "done": done,
                "total": total,
                **(
                    {"eta_seconds": int(estimate["eta_seconds"])}
                    if estimate["eta_seconds"] is not None
                    else {}
                ),
                **({"one_at_a_time": True} if estimate["one_at_a_time"] else {}),
            }
        )
    return {
        "current": current,
        "applied": applied,
        "task": str(root),
        "status": engine_status,
        "findings": findings,
        "questions": questions,
        **(
            {
                "coverage": {
                    "lines": int((task.get("counts") or {}).get("records", 0)),
                    "not_reviewed": len(document.get("not_reviewed", [])),
                }
            }
            if document
            else {}
        ),
        **({"activity": activity} if activity else {}),
        **({"rules_changed": True} if rules_changed else {}),
        **({"plugins_changed": True} if plugins_changed else {}),
        "prepared_at": task["created_at"],
        "message": "Saved results match current project text."
        if current
        else "An update changed QA's rules while this task was in review."
        if rules_changed
        else "The game's plugins changed since this QA task was prepared; "
        "preparing it again keeps its review."
        if plugins_changed
        else "The game text changed since this QA task was prepared.",
    }


def _beside_plugins(value):
    """A QA binding without the game's plugin list and plugin files."""
    return {
        **value,
        "guard": {
            key: item
            for key, item in value["guard"].items()
            if key not in {"plugins", "plugin_files"}
        },
    }


def qa_pointers(folder):
    """Each focus's record of its prepared QA task in a game's workspace."""
    from util.rpgmaker_qa_manifest import FOCUSES

    return [Path(folder) / ("text-qa-" + focus + ".json") for focus in sorted(FOCUSES)]


def qa_pointed_task(folder, pointer):
    """The task folder a focus's record names, inside QA's storage."""
    return _task_folder({"folder": str(folder)}, read_json(pointer))


def qa_capture(task):
    """A prepared QA task's latest capture of the game's screens: its round,
    which a capture taken again counts up, and its listing; None for a task
    prepared without one."""
    from util import rpgmaker_qa as qa

    captured = qa.interface_capture(task)
    if not captured:
        return None
    return {"round": captured["round"], "listing": captured["folder"] / "screens.json"}


def qa_outside(task):
    """Text the prepared QA task in *task* found squeezed or cut off on a
    captured screen that its inventory holds no line of, such as a plugin's
    menu command: each label's text, screen title, capture and how short of
    room it is. A task that captured nothing has none."""
    from util import rpgmaker_qa as qa

    root = Path(task)
    captured = qa.interface_capture(root)
    if not captured or not (captured["folder"] / "screens.json").is_file():
        return []
    _places, outside = qa.interface_places(
        captured["folder"], read_json(root / "inventory.json")
    )
    return outside


def reason(row):
    """What is wrong with a reviewed line, as the page shows it: the
    reviewer's one plain sentence, or for a task made before reviewers wrote
    one, their full evidence, which the page shortens."""
    return row.get("summary") or row.get("evidence") or ""


def review_notes(document):
    """Each correction's and question's full review, for the History
    inspector; the page shows only its plain sentence."""
    return [
        {
            "id": row["id"],
            "current": (row.get("shown") or {}).get(
                "current",
                row.get("current")
                or "\n".join(line["current"] for line in row.get("lines") or []),
            ),
            "evidence": row.get("evidence") or "",
            **(
                {"editorial": row["editorial"]["note"]}
                if (row.get("editorial") or {}).get("note")
                else {}
            ),
        }
        for row in [
            *document.get("findings", []),
            *(
                row
                for row in document.get("uncertain_playtests", [])
                if row.get("correction")
            ),
        ]
        # Lint fixes' evidence is their plain sentence, which the page shows.
        if row.get("evidence") not in (None, "", row.get("summary"))
        or (row.get("editorial") or {}).get("note")
    ]


def not_corrected(document):
    """The defects reviewers found but could not correct, as the page shows
    them: a text variable's as it reads. Older tasks asked a question without
    a proposal for these."""
    return [
        {
            "id": row["id"],
            "file": row["id"].split("#", 1)[0],
            "source": (row.get("shown") or {}).get("source", row["source"]),
            "current": (row.get("shown") or {}).get("current", row["current"]),
            "reason": reason(row),
            **(
                {"evidence": row["evidence"]}
                if row.get("summary")
                and row.get("evidence") not in (None, "", row["summary"])
                else {}
            ),
            "places": int(row.get("places") or 1),
        }
        for row in [
            *document.get("not_corrected", []),
            *(
                row
                for row in document.get("uncertain_playtests", [])
                if not row.get("correction")
            ),
        ]
    ]


def qa_report(plan):
    """What QA could not cover, for the History inspector: lines no reviewer
    judged, defects no correction could fix, Japanese never translated, by
    file and plugin, and text the game squeezes or cuts off that QA holds no
    line of."""
    from util.rpgmaker_qa_preflight import read_sources

    state = qa_state(plan)
    if not state.get("task"):
        raise ValueError("Prepare text QA first.")
    root = Path(state["task"])
    document = (
        read_json(root / "findings.json") if (root / "findings.json").exists() else {}
    )
    outside = qa_outside(root)
    interface = state["status"].get("interface") or {}
    return {
        "not_reviewed": document.get("not_reviewed", []),
        "not_corrected": not_corrected(document),
        "notes": review_notes(document),
        "not_translated": read_sources(read_json(root / "preflight.json")),
        "interface_outside": [
            {"text": row["text"], "title": row["title"]} for row in outside
        ],
        **({"interface_error": interface["error"]} if "error" in interface else {}),
    }


def run_qa(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util import rpgmaker_qa as qa

    from dazedtl.plugins.service import kept_settings

    validate_plan(plan)
    folder = Path(plan["folder"])
    if plan["action"] == "qa_prepare":
        _set_aside(plan, log)
        # A new task builds on the earlier ones, with the lines the user kept.
        adopt_answers(folder)
        # What the release playtest found in the same text goes to review; a
        # task prepared again keeps its own and takes the ones it lacks.
        from .playtest import pending

        focus = plan["options"]["focus"]
        observations = pending(folder, plan["guard"])
        task, _state = qa.prepare_task(
            plan["project"]["source"],
            plan["project"]["data"],
            focus,
            folder / "text-qa",
            fit=plan["options"].get("fit"),
            interface=True,
            progress=log,
            observations=observations,
            kept=kept_settings(plan["project"]["source"]),
            since=plan["options"].get("since") or None,
            earlier=not plan["options"].get("everything"),
        )
        if observations:
            log(f"QA reviews {len(observations)} line(s) the playtest found")
        if not qa.inventory_matches(
            task, qa.build_manifest(plan["project"]["data"], focus)
        ):
            raise ValueError(
                "The cached QA inventory changed. Retain it for investigation and prepare a fresh task."
            )
        immutable = {
            name: digest(project_path(task, name).read_bytes())
            for name in (
                "task.json",
                "inventory.json",
                "context.json",
                "screen-index.json",
            )
        }
        write_json(
            folder / ("text-qa-" + focus + ".json"),
            {"task": str(task), "binding": binding(plan), "immutable": immutable},
        )
        handoff = qa_handoff(task)
    else:
        handoff = None
    result = qa_state(plan)
    if handoff:
        result["handoff"] = handoff
    log(result["message"])
    return result


# Only a restore's review shows its files' text changes: Apply lists the files
# it overwrites, fitting lists its own changes and QA applies without a review.
COMPARED = {"runtime_restore"}


# The characters of each file's diff and text a review shows, and the equal
# lines around each change.
SHOWN = 16000
CONTEXT = 2
# The lines difflib matches at a time, growing up to the largest window while
# no equal line starts in a window's first three quarters.
WINDOW = 200
LARGEST_WINDOW = 16000


def comparison(raw, candidate):
    """A file's current and replacement text for its review, with the start
    of their unified diff."""
    before = raw.decode("utf-8-sig")
    after = candidate.decode("utf-8-sig")
    diff, truncated = _diff_start(before.splitlines(), after.splitlines())
    return {
        "diff": diff,
        "truncated": truncated,
        "before_text": before[:SHOWN],
        "after_text": after[:SHOWN],
    }


def _opcodes(before, after):
    """difflib opcodes that turn before into after, until their changed lines
    fill the review.

    difflib's match of two whole files grows with the square of their changed
    lines, so a large game's common events took minutes. Equal lines are
    skipped one by one instead, and difflib matches only a window after each
    difference, kept up to an equal line well inside it, where the window's
    end cannot have shifted the match.
    """
    codes, shown, i, j = [], 0, 0, 0

    def add(tag, i1, i2, j1, j2):
        nonlocal shown
        if tag == "equal" and codes and codes[-1][0] == "equal":
            i1, j1 = codes.pop()[1::2]
        elif tag != "equal":
            shown += sum(len(line) + 2 for line in before[i1:i2])
            shown += sum(len(line) + 2 for line in after[j1:j2])
        codes.append((tag, i1, i2, j1, j2))

    while True:
        start = i
        while i < len(before) and j < len(after) and before[i] == after[j]:
            i, j = i + 1, j + 1
        if i > start:
            add("equal", start, i, start + j - i, j)
        if (i, j) == (len(before), len(after)) or shown > SHOWN:
            return codes
        window = WINDOW
        while True:
            # Junk heuristics make repeated lines such as map tiles unmatched.
            found = difflib.SequenceMatcher(
                None, before[i : i + window], after[j : j + window], autojunk=False
            ).get_opcodes()
            if i + window >= len(before) and j + window >= len(after):
                kept = found
                break
            inside = window * 3 // 4
            last = next(
                (
                    index
                    for index in range(len(found) - 1, -1, -1)
                    if found[index][0] == "equal"
                    and max(found[index][1], found[index][3]) < inside
                ),
                None,
            )
            if last is not None:
                tag, i1, i2, j1, j2 = found[last]
                length = min(i2 - i1, inside - max(i1, j1))
                kept = [*found[:last], (tag, i1, i1 + length, j1, j1 + length)]
                break
            if window == LARGEST_WINDOW:
                # However it matched, it turns the window's lines into each other.
                kept = found
                break
            window = min(window * 4, LARGEST_WINDOW)
        for tag, i1, i2, j1, j2 in kept:
            add(tag, i + i1, i + i2, j + j1, j + j2)
        i, j = codes[-1][2], codes[-1][4]


def _hunks(codes):
    """The opcodes grouped into unified diff hunks, as difflib groups them."""
    if not codes:
        return
    codes = list(codes)
    if codes[0][0] == "equal":
        tag, i1, i2, j1, j2 = codes[0]
        codes[0] = tag, max(i1, i2 - CONTEXT), i2, max(j1, j2 - CONTEXT), j2
    if codes[-1][0] == "equal":
        tag, i1, i2, j1, j2 = codes[-1]
        codes[-1] = tag, i1, min(i2, i1 + CONTEXT), j1, min(j2, j1 + CONTEXT)
    group = []
    for tag, i1, i2, j1, j2 in codes:
        if tag == "equal" and i2 - i1 > 2 * CONTEXT:
            group.append((tag, i1, i1 + CONTEXT, j1, j1 + CONTEXT))
            yield group
            group = []
            i1, j1 = i2 - CONTEXT, j2 - CONTEXT
        group.append((tag, i1, i2, j1, j2))
    if group and not (len(group) == 1 and group[0][0] == "equal"):
        yield group


def _span(start, stop):
    """A hunk's line range, as difflib writes it."""
    length = stop - start
    if length == 1:
        return str(start + 1)
    return f"{start + 1 if length else start},{length}"


def _diff_start(before, after):
    """The first SHOWN characters of the lines' unified diff, and whether
    more was cut."""
    lines, length = [], 0
    for group in _hunks(_opcodes(before, after)):
        if not lines:
            lines = ["--- Current runtime", "+++ Reviewed replacement"]
            length = sum(len(line) + 1 for line in lines)
        first, last = group[0], group[-1]
        hunk = [f"@@ -{_span(first[1], last[2])} +{_span(first[3], last[4])} @@"]
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                hunk += [" " + line for line in before[i1:i2]]
                continue
            hunk += ["-" + line for line in before[i1:i2]]
            hunk += ["+" + line for line in after[j1:j2]]
        for line in hunk:
            length += len(line) + 1
            if length > SHOWN:
                return "\n".join(lines), True
            lines.append(line)
    return "\n".join(lines), False


def fitting_layout(plan):
    """The Line widths an RPG Maker game's applied text is fitted to, or None
    for a game DazedTL does not fit."""
    from util.rpgmaker_rewrap import Layout

    project = plan["project"]
    if project.get("engine") not in {"MVMZ", "ACE"}:
        return None
    return Layout.from_widths(project.get("widths"))


def fit_output(document, name, layout, areas=None, *, newline=False):
    """A translated file's bytes with every translated line that does not
    fit the Line widths wrapped again, and how many values that changed; no
    bytes when nothing needs it."""
    from util.rpgmaker_rewrap import fit_document, needs_fit

    if not needs_fit(document, name, layout, areas=areas):
        return None, 0
    changes = len(fit_document(document, name, layout, areas=areas).changes)
    # The engine's own formatting, so only the fitted lines differ.
    text = json.dumps(document, ensure_ascii=False, indent=4)
    return (text + "\n" if newline else text).encode("utf-8"), changes


def unfitted(document, name, layout):
    """The translated values in *document* that do not fit the Line widths
    even wrapped again, such as help that needs more rows than its window
    shows; fits *document* in place."""
    from util.rpgmaker_rewrap import fit_document

    return fit_document(document, name, layout).misfits


def prepare_publication(plan):
    from desktop.backend.workflow_actions import validate_plan

    validate_plan(plan)
    root, data, folder = (
        Path(plan["project"]["source"]),
        Path(plan["project"]["data"]),
        Path(plan["folder"]),
    )
    action, options = plan["action"], plan["options"]
    prefix = data.relative_to(root)
    candidates, outputs, restored, sources, written = {}, {}, None, {}, {}
    if action == "export_selected":
        saved = plan.get("run_output")
        output_folder = Path(saved["folder"]) if saved else folder
        layout = fitting_layout(plan)
        for name in options["files"]:
            path = project_path(output_folder, "translated/" + name)
            output = path.read_bytes()
            if saved and digest(output) != saved["outputs"].get(name):
                raise ValueError("Saved Batch output changed. Review this Batch again.")
            # Parse the same bytes that will be frozen for publication.
            if len(output) > 128_000_000:
                raise ValueError(
                    "Choose a JSON output within the supported size limit."
                )
            document = decode_json(output)
            outputs[name] = digest(output)
            fitted = fit_output(document, name, layout)[0] if layout else None
            if fitted is not None:
                candidates[(prefix / name).as_posix()] = fitted
                written[name] = digest(fitted)
                continue
            candidates[(prefix / name).as_posix()] = output
            # Apply publishes the saved output itself, checked by hash.
            sources[(prefix / name).as_posix()] = path
    elif action == "runtime_restore":
        candidates, restored = publication.restore_candidates(
            folder, root, options["publication"]
        )
    elif action == "fit_text":
        # New Line widths: the translated text of the files DazedTL applied,
        # in the areas the widths changed, wherever a line no longer fits.
        # Files it never applied, such as ones translated by hand, stay.
        from util.len_originals import LISTED_MISFITS

        layout = fitting_layout(plan)
        plan["fitted_lines"] = 0
        plan["misfits"], plan["misfit_count"] = [], 0
        receipt = (
            read_json(folder / "applied-outputs.json")
            if (folder / "applied-outputs.json").exists()
            else {}
        )
        applied = receipt.get("files", {})
        # Only files an Apply published: one whose bytes merely equal a run's
        # output, such as a map with nothing to translate, is the game's own.
        for name in sorted(set(options["files"]) & set(applied), key=str.casefold):
            relative = (prefix / name).as_posix()
            raw = project_path(root, relative).read_bytes()
            document = decode_json(raw)
            fitted, changes = fit_output(
                document,
                name,
                layout,
                set(options["areas"]),
                newline=raw.endswith(b"\n"),
            )
            # What no wrap fits at these widths, in every area, as the game
            # will hold it once this fit is written.
            misfits = unfitted(document, name, layout)
            plan["misfits"] += misfits[: LISTED_MISFITS - len(plan["misfits"])]
            plan["misfit_count"] += len(misfits)
            if fitted is None:
                continue
            candidates[relative] = fitted
            plan["fitted_lines"] += changes
            # A file as the last Apply wrote it is still that Apply's, now
            # fitted to the new widths, so the next Apply reads no edits.
            if digest(raw) in {
                applied.get(name),
                receipt.get("written", {}).get(name),
            }:
                written[name] = digest(fitted)
        if not candidates:
            return {"publication": [], "paths": [], "files": 0}
    elif action in {"qa_apply", "qa_undo"}:
        from util import rpgmaker_qa as qa

        state = qa_state(plan)
        if options.get("task") != state["task"]:
            raise ValueError(
                "The QA task changed. Choose corrections from the current findings."
            )
        chosen, proposals = qa_selection(state, action, options)
        # Applying an undone correction again checks each of its lines against
        # the text QA reviewed, as Undo does, so edits elsewhere since the
        # first apply do not stop it.
        undone = {
            row["id"]
            for row in state["findings"] + state["questions"]
            if row.get("state") == "undone"
        }
        again = action == "qa_apply" and set(chosen + proposals) <= undone
        if action == "qa_apply" and not again and not state["current"]:
            raise ValueError(state["message"])
        task_root, task, _checkpoint = qa.read_task(state["task"])
        try:
            selected = qa.correction_map(
                task_root, chosen, proposals, undo=action == "qa_undo"
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        with system.staging_folder(folder, "qa-candidates-") as staging:
            scratch = staging / "data"
            scratch.mkdir()
            for path in data.glob("*.json"):
                shutil.copyfile(
                    project_path(root, path.relative_to(root).as_posix()),
                    scratch / path.name,
                )
            write_json(
                staging / "inventory.json", read_json(task_root / "inventory.json")
            )
            scratch_task = {**task, "data_root": str(scratch)}
            try:
                qa.apply_loaded_correction_map(
                    staging,
                    scratch_task,
                    selected,
                    read_json(task_root / "inventory.json"),
                    dry_run_name="dry-run.json",
                    regression_name="regression.json",
                    nonblocking_introduced_flags=qa.APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
                )
            except ValueError as exc:
                if action == "qa_undo" and "Expected" in str(exc):
                    raise ValueError(
                        "A line changed in the game since QA corrected it, so the "
                        "correction can't be undone here. Use History or edit it."
                    ) from exc
                if again and "Expected" in str(exc):
                    raise ValueError(
                        "A line changed in the game since QA reviewed it, so the "
                        "correction can't be applied again. Run QA again to check it."
                    ) from exc
                raise
            for name in {row["file"] for row in selected["operations"]}:
                candidates[(prefix / name).as_posix()] = project_path(
                    scratch, name
                ).read_bytes()
    else:
        raise ValueError("Unknown text publication.")
    frozen = publication.freeze(
        folder,
        root,
        candidates,
        action,
        outputs=outputs,
        restore=restored,
        overwrite=action == "export_selected",
        sources=sources,
        written=written,
        run=(plan.get("run_output") or {}).get("run_id")
        if action == "export_selected"
        else None,
        task=options["task"] if action in {"qa_apply", "qa_undo"} else None,
        findings=options.get("findings", []) + options.get("proposals", [])
        if action in {"qa_apply", "qa_undo"}
        else None,
    )
    if action == "export_selected":
        plan["overwrite_runtime"] = True
    plan["publication"] = frozen
    receipt = (
        read_json(folder / "applied-outputs.json")
        if (folder / "applied-outputs.json").exists()
        else {}
    )
    previous = receipt.get("files", {})
    rows = []
    for row in frozen["files"]:
        name = Path(row["path"]).name
        # The frozen row's index and mode stay internal to publication.
        change = {
            **{key: row[key] for key in ("path", "before", "after", "size")},
            "destination": str(root / row["path"]),
            # What the last Apply wrote: its output, or the output fitted to
            # the Line widths.
            "later_edits": action == "export_selected"
            and name in previous
            and row["before"]
            not in {previous[name], receipt.get("written", {}).get(name)},
        }
        if action in COMPARED:
            # A file a batch added compares with none.
            current = project_path(root, row["path"], exists=False)
            change.update(
                comparison(
                    current.read_bytes() if current.exists() else b"",
                    candidates[row["path"]] or b"",
                )
            )
        rows.append(change)
    return {
        "publication": rows,
        "paths": [row["path"] for row in rows],
        "files": len(rows),
    }


def run_fit(plan, log):
    """Fit the game's translated text to new Line widths in one backed-up
    publication."""
    log(plan["label"])
    files = prepare_publication(plan)["files"]
    # The text the widths leave too long, which Guided lists while the
    # game holds this fit's text.
    unfit = {
        "misfits": plan["misfits"],
        "misfit_count": plan["misfit_count"],
        "widths": plan["project"]["widths"],
    }
    if not files:
        message = (
            "No lines needed rewrapping."
            if unfit["misfit_count"]
            else "Every line already fits the new Line widths."
        )
        return {"files": 0, "lines": 0, "message": message, **unfit}
    lines = plan["fitted_lines"]
    counted = f"{lines:,} {'line' if lines == 1 else 'lines'}"
    log(f"Rewrapping {counted}.")
    return {
        **run_publication(plan, log),
        "lines": lines,
        "message": f"Rewrapped {counted} to the new Line widths.",
        **unfit,
    }


def run_publication(plan, log):
    validate_publication(plan)
    return publication.publish(
        plan["folder"], plan["project"]["source"], plan["publication"], log
    )


def validate_publication(plan):
    from desktop.backend.workflow_actions import action_guard, validate_plan

    if plan.get("overwrite_runtime") and plan.get("action") == "export_selected":
        current = action_guard(plan["project"], plan["folder"])
        if {key: value for key, value in current.items() if key != "data"} != {
            key: value for key, value in plan["guard"].items() if key != "data"
        }:
            raise ValueError(
                "The saved output, destination or settings changed. Review Apply again."
            )
    else:
        validate_plan(plan)
