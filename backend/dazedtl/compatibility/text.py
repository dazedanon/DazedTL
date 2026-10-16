"""Preserved fitting and QA validators, with app-owned runtime publication."""

import difflib
import shutil
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

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
        return "lint"
    if row.get("sweep_families"):
        return "sweep"
    return "review"


def _task_record(folder, name, task):
    path = Path(folder) / name
    return (read_json(path) if path.exists() else {}).get(task)


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
    state that step needs: not yet applied before the task's first apply,
    undone after it, or applied for an undo."""
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
    wanted = "applied" if action == "qa_undo" else "undone" if state["applied"] else ""
    if any(states.get(value, "missing") != wanted for value in chosen + proposals):
        raise ValueError(
            "Only applied corrections can be undone."
            if action == "qa_undo"
            else "Only undone corrections can be applied again."
            if state["applied"]
            else "The chosen QA corrections changed. Refresh findings."
        )
    return chosen, proposals


def _pointer(plan):
    """The record naming the focus's prepared task."""
    return Path(plan["folder"]) / (
        "text-qa-" + plan["options"].get("focus", "release") + ".json"
    )


def _task_folder(plan, saved):
    """The task folder a pointer names, inside QA's storage."""
    storage = Path(plan["folder"]) / "text-qa"
    relative = Path(saved["task"]).relative_to(storage)
    return project_path(storage, relative.as_posix(), exists=False)


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
    """The task the pointer names and its saved findings, once its evidence
    checks out; raises when the app can't read or trust it."""
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
    # A task from before an update still shows what it found and applied,
    # though only a task prepared with the current rules can continue.
    root, task, _checkpoint = qa._read_task(task_path)
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
        or document.get("task_sha256") != qa._sha256(qa._canonical_bytes(task))
    ):
        raise ValueError("Saved findings belong to another QA task.")
    return saved, root, task, document


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
        folder.rename(target)
    except OSError as error:
        raise ValueError(
            "Couldn't set the unreadable QA task aside. Close programs using its "
            "files, then try again."
        ) from error
    log(f"Set aside {folder} as {target.name}: {failure}")


def qa_state(plan):
    from util import rpgmaker_qa as qa

    if not _pointer(plan).exists():
        return {
            "current": False,
            "applied": False,
            "status": {},
            "findings": [],
            "questions": [],
            "message": "No QA task prepared for this focus.",
        }
    saved, root, task, document = _prepared(plan)
    rules_changed = task["engine_fingerprint"] != qa._engine_fingerprint()
    current = saved["binding"] == binding(plan) and not rules_changed
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
    applied = any(row["kind"] == "qa_apply" for row in rows)

    def finding_state(identity):
        return (
            "undone"
            if identity in undone_ids
            else "applied"
            if identity in applied_ids
            else ""
        )

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
                    key: "\n".join(line[key] for line in lines) if lines else row[key]
                    for key in ("source", "current", "correction")
                },
                "category": row["category"],
                "severity": row["severity"],
                "family": row.get("family_key") or "",
                "kind": _finding_kind(row),
                "places": max(1, len(targets)),
                "files": files,
                "reason": row.get("evidence") or "",
                **({"lines": lines} if lines else {}),
                **(
                    {"editorial": row["editorial"]["note"]}
                    if (row.get("editorial") or {}).get("note")
                    else {}
                ),
                **(
                    {"state": finding_state(row["id"])}
                    if finding_state(row["id"])
                    else {}
                ),
            }
        )
    choices = _task_record(plan["folder"], "text-qa-choices.json", str(root)) or {}
    questions = [
        {
            "id": row["id"],
            "source": row.get("source", ""),
            "current": row.get("current", ""),
            "reason": row.get("evidence") or "",
            "places": int(row.get("places") or 1),
            **({"proposal": row["correction"]} if row.get("correction") else {}),
            **({"choice": choices[row["id"]]} if row["id"] in choices else {}),
            **({"state": finding_state(row["id"])} if finding_state(row["id"]) else {}),
        }
        for row in document.get("uncertain_playtests", [])
    ]
    engine_status = qa.status(root)
    stage = engine_status.get("stage", "")
    untranslated = engine_status.get("not_translated") or {}
    reviewed = set(
        _task_record(plan["folder"], "text-qa-reviewed.json", str(root)) or []
    )
    unreviewed = [
        row
        for row in document.get("not_reviewed", [])
        if row["identity"] not in reviewed
    ]
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
        activity = {
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
                    "not_reviewed": len(unreviewed),
                }
            }
            if document
            else {}
        ),
        # Known once the task is prepared, before any reviewer starts.
        **({"not_translated": untranslated} if untranslated.get("total") else {}),
        **(
            {
                "interface": {
                    key: interface[key]
                    for key in ("captured", "squeezed", "outside", "error")
                    if key in interface
                }
            }
            if (interface := engine_status.get("interface"))
            else {}
        ),
        **({"activity": activity} if activity else {}),
        **({"rules_changed": True} if rules_changed else {}),
        "message": "Saved results match current project text."
        if current
        else "An update changed QA's rules after this task was prepared."
        if rules_changed
        else "The game text changed since this QA task was prepared.",
    }


def qa_report(plan):
    """What QA could not cover: lines no reviewer judged, with whether the user
    reviewed them, Japanese never translated, by file and plugin, and text the
    game squeezes or cuts off that QA holds no line of."""
    from util import rpgmaker_qa as qa
    from util.rpgmaker_qa_preflight import read_sources

    state = qa_state(plan)
    if not state.get("task"):
        raise ValueError("Prepare text QA first.")
    root = Path(state["task"])
    document = (
        read_json(root / "findings.json") if (root / "findings.json").exists() else {}
    )
    reviewed = set(
        _task_record(plan["folder"], "text-qa-reviewed.json", str(root)) or []
    )
    _places, outside = qa._interface_places(
        root / qa.INTERFACE_FOLDER, qa._read_json(root / "inventory.json")
    )
    interface = state.get("interface") or {}
    return {
        "not_reviewed": [
            {**row, "reviewed": row["identity"] in reviewed}
            for row in document.get("not_reviewed", [])
        ],
        "not_translated": read_sources(qa._read_json(root / "preflight.json")),
        "interface_outside": [
            {"text": row["text"], "title": row["title"]} for row in outside
        ],
        **({"interface_error": interface["error"]} if "error" in interface else {}),
    }


def run_qa(plan, log):
    from desktop.backend.workflow_actions import validate_plan
    from util import rpgmaker_qa as qa

    validate_plan(plan)
    folder = Path(plan["folder"])
    if plan["action"] == "qa_prepare":
        _set_aside(plan, log)
        # What the release playtest found in the same text goes to review.
        from .playtest import pending

        observations = pending(folder, plan["guard"])
        task, _state = qa.prepare_task(
            plan["project"]["source"],
            plan["project"]["data"],
            plan["options"]["focus"],
            folder / "text-qa",
            fit=plan["options"].get("fit"),
            interface=True,
            progress=log,
            observations=observations,
        )
        if observations:
            log(f"QA reviews {len(observations)} line(s) the playtest found")
        manifest = qa.build_manifest(plan["project"]["data"], plan["options"]["focus"])
        descriptor = read_json(task / "task.json")
        if (
            descriptor["manifest_sha256"] != manifest["content_sha256"]
            or read_json(task / "inventory.json") != manifest
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
            folder / ("text-qa-" + plan["options"]["focus"] + ".json"),
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
    candidates, outputs, restored, sources = {}, {}, None, {}
    if action == "export_selected":
        saved = plan.get("run_output")
        output_folder = Path(saved["folder"]) if saved else folder
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
            decode_json(output)
            candidates[(prefix / name).as_posix()] = output
            # Apply publishes the saved output itself, checked by hash.
            sources[(prefix / name).as_posix()] = path
            outputs[name] = digest(output)
    elif action == "runtime_restore":
        candidates, restored = publication.restore_candidates(
            folder, root, options["publication"]
        )
    elif action == "rewrap_apply":
        from util.rpgmaker_rewrap import (
            RewrapOptions,
            parse_event_codes,
            rewrap_directory,
        )

        widths = options["widths"]
        settings = RewrapOptions(
            widths["width"],
            widths["faceWidth"],
            widths["listWidth"],
            widths["noteWidth"],
            categories=frozenset(options["categories"]),
            event_codes=parse_event_codes(options["codes"]),
            max_protected_rows=options["max_rows"] if options["protect_rows"] else 0,
            skip_protected_overflow=options["protect_rows"],
            only_over_limit=options["over_limit"],
        )
        with tempfile.TemporaryDirectory(dir=folder, prefix="fitting-") as temporary:
            staging = Path(temporary)
            for name in options["files"]:
                shutil.copyfile(
                    project_path(root, (prefix / name).as_posix()), staging / name
                )
            report = rewrap_directory(
                staging, settings, file_names=options["files"], apply=True
            )
            if report.errors:
                raise ValueError("; ".join(report.errors))
            for name in options["files"]:
                raw = (staging / name).read_bytes()
                if raw != (data / name).read_bytes():
                    candidates[(prefix / name).as_posix()] = raw
        if not candidates:
            raise ValueError(
                "No fitting edits are eligible. Protected row overflows were skipped; review the text or fitting settings and scan again."
            )
    elif action in {"qa_apply", "qa_undo"}:
        from util import rpgmaker_qa as qa

        state = qa_state(plan)
        # Applying an undone correction again checks each of its lines against
        # the text QA reviewed, as Undo does, so edits elsewhere since the
        # first apply do not stop it.
        again = action == "qa_apply" and state["applied"]
        if action == "qa_apply" and not again and not state["current"]:
            raise ValueError(state["message"])
        if options.get("task") != state["task"]:
            raise ValueError(
                "The QA task changed. Choose corrections from the current findings."
            )
        if state.get("rules_changed"):
            raise ValueError(
                "An update changed QA's rules after these corrections were applied, so "
                "they can't be undone or applied again. Run QA again to check the text."
            )
        task_root, task, _checkpoint = qa._load_task(state["task"])
        chosen, proposals = qa_selection(state, action, options)
        try:
            selected = qa.correction_map(
                task_root, chosen, proposals, undo=action == "qa_undo"
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        with tempfile.TemporaryDirectory(
            dir=folder, prefix="qa-candidates-"
        ) as temporary:
            staging = Path(temporary)
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
                qa._apply_loaded_correction_map(
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
    elif action == "glossary_apply":
        from .glossary_check import candidates as glossary_candidates

        candidates = glossary_candidates(plan, root, prefix, folder)
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
        task=options["task"] if action in {"qa_apply", "qa_undo"} else None,
        findings=options.get("findings", []) + options.get("proposals", [])
        if action in {"qa_apply", "qa_undo"}
        else None,
    )
    if action == "export_selected":
        plan["overwrite_runtime"] = True
    plan["publication"] = frozen
    previous = (
        read_json(folder / "applied-outputs.json").get("files", {})
        if (folder / "applied-outputs.json").exists()
        else {}
    )
    rows = []
    for row in frozen["files"]:
        name = Path(row["path"]).name
        # The frozen row's index and mode stay internal to publication.
        change = {
            **{key: row[key] for key in ("path", "before", "after", "size")},
            "destination": str(root / row["path"]),
            "later_edits": action == "export_selected"
            and name in previous
            and row["before"] != previous[name],
        }
        if action in COMPARED:
            change.update(
                comparison(
                    project_path(root, row["path"]).read_bytes(),
                    candidates[row["path"]],
                )
            )
        rows.append(change)
    return {
        "publication": rows,
        "paths": [row["path"] for row in rows],
        "files": len(rows),
    }


def run_publication(plan, log):
    validate_publication(plan)
    result = publication.publish(
        plan["folder"], plan["project"]["source"], plan["publication"], log
    )
    return {**result, "ace_packing_required": plan["project"]["engine"] == "ACE"}


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
