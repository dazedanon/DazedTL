"""The assistant's progress report, which the app republishes with counts from
saved results. The helper, the app and a run's worker all rewrite it, so each
holds the project's progress lock while it reads, changes and publishes.

The app keeps the last report it published in the project's records, out of
the game, where the assistant writes its reports and could send or edit the
app's copy; only a report that passed its checks is kept (`kept`).

The report also names the assistant's checkpoints: the app commits the
assistant's work at each report it publishes and when one of its runs ends,
named for the phase the work was done in (`checkpoint`). Work that no longer
covers a phase reopens it and every phase after it (`reopen`): undoing or
going back past a phase's checkpoint (`follow`), or a game update, whose new
text is extracted again."""

from pathlib import Path
from typing import Any

from dazedtl.compatibility.checkpoint_commits import Change
from dazedtl.storage import exclusive, write_json
from dazedtl.translation.files import project_path, read_json, verify_evidence
from dazedtl.translation.project import MANUAL, WORK
from dazedtl.translation.results import Results

# Where apps before 2.59.5 kept the last report, read once (`_last`).
LEGACY = WORK + "/progress-report.json"
VERSION = 1
NEXT_ACTION = "Continue saved work, then fit, inject and perform QA."
# What the assistant does next once work no longer covers a phase.
REOPENED = "Check the game's files again, then continue from {}."
# The action that names the checkpoints of the assistant's phases.
PHASE_ACTION = "assistant_phase"


def _records(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id


def _lock(workspace, project_id):
    return exclusive(_records(workspace, project_id) / "progress.lock")


def kept(workspace, project_id):
    """The record of the last report the app published."""
    return _records(workspace, project_id) / "progress-report.json"


def _keep(workspace, project_id, report):
    write_json(kept(workspace, project_id), {"version": VERSION, "report": report})


def _last(workspace, project_id, source, check=None):
    """The last report the app published, or None before the first; a record
    this app can't read counts as none. Before its first record, the report
    an earlier app kept in the game is read once: with `check`, which refuses
    a report, it is kept if it passes, as the one later refreshes build on,
    since the assistant may have sent or edited that file since."""
    path = kept(workspace, project_id)
    if path.exists():
        try:
            value = read_json(path)
        except ValueError, OSError:
            return None
        if not isinstance(value, dict) or value.get("version") != VERSION:
            return None
        report = value.get("report")
        return report if isinstance(report, dict) else None
    try:
        report = read_json(project_path(source, LEGACY, exists=False))
        if not isinstance(report, dict):
            report = None
        elif check:
            check(report)
    except ValueError, OSError:
        report = None
    if check:
        _keep(workspace, project_id, report)
    return report


def phase(workspace, project_id, source, report=None):
    """The checkpoint of the assistant's work in the phase it last reported,
    or in `report`'s before its first report."""
    from util.len_progress import PHASES

    last = _last(workspace, project_id, source) or report
    name = last.get("phase") if isinstance(last, dict) else None
    label = PHASES.get(name) if isinstance(name, str) else None
    return Change(label or "Assistant's work", "Assistant-led", PHASE_ACTION)


def checkpoint(engine, workspace, project_id, source, report=None):
    """Commits the assistant's changes waiting in the game, its own edits and
    the writes that wait for their phase, as one checkpoint of `phase`, with
    the files its runtime manifest lists that the patch lacks."""
    from .operations import lifecycle, runtime_manifest

    named = ()
    if manifest := lifecycle(workspace, project_id).get("runtime_manifest"):
        try:
            named = engine.runtime_paths(runtime_manifest(source, manifest))
        except OSError, ValueError:
            # Packaging, which needs the manifest, says what is wrong with it.
            pass
    engine.pending_checkpoint(
        source, phase(workspace, project_id, source, report), named
    )


def publish(workspace, project_id, engine, source, options, report):
    """Publishes the assistant's complete report, then keeps it as the one
    later refreshes build on."""
    with _lock(workspace, project_id):
        value = engine.progress(source, options, report)
        _keep(workspace, project_id, report)
    return value


def _checked(engine, source, options):
    return lambda report: engine.check_progress(source, options, report)


def update(workspace, project_id, engine, source, options, change):
    """Republishes the last report after change edits it in place; nothing
    happens before the assistant's first report."""
    with _lock(workspace, project_id):
        report = _last(workspace, project_id, source, _checked(engine, source, options))
        if report is None:
            return None
        change(report)
        value = engine.progress(source, options, report)
        _keep(workspace, project_id, report)
    return value


def reopen(workspace, project_id, engine, source, options, phase):
    """Reopens `phase` and every phase after it in the last report, for work
    that no longer covers them, and republishes it; nothing happens before
    the assistant's first report. Phases out of scope stay out. Images, which
    the Images task follows from the game's files, reopens only as `phase`
    itself or as the report's phase. Inputs the game no longer holds are
    left out, and unless the report is at an earlier phase, it moves back to
    the first reopened one, leaving the question it asked there behind."""
    from util.len_progress import PHASES

    order = list(PHASES)

    def change(report):
        phases = report.setdefault("phases", {})
        current = report.get("phase")
        reopened = [
            name
            for name in order[order.index(phase) :]
            if phases.get(name) != "out_of_scope"
            and (name != "images" or name in {phase, current})
        ]
        if not reopened:
            return
        for name in reopened:
            phases[name] = "pending"
        report["inputs"] = [
            relative
            for relative in report.get("inputs", [])
            if project_path(source, relative, exists=False).is_file()
        ]
        if current in PHASES and order.index(current) < order.index(reopened[0]):
            return
        report["phase"] = reopened[0]
        phases[reopened[0]] = "active"
        report["blocker"] = ""
        report["next_action"] = REOPENED.format(PHASES[reopened[0]].lower())

    return update(workspace, project_id, engine, source, options, change)


def follow(workspace, project_id, engine, source, undone):
    """Reopens, from the earliest of them, the phases whose checkpoints are
    among `undone`, which an undo or a go back took out."""
    from util.len_progress import PHASES

    from dazedtl.compatibility.checkpoint_history import entries

    from .project import ProjectWorkspace

    if _last(workspace, project_id, source) is None:
        return None
    names = {label: name for name, label in PHASES.items()}
    found = {
        names[entry.title]
        for entry in entries(source, undone)
        if entry.action == PHASE_ACTION and entry.title in names
    }
    if not found:
        return None
    earliest = min(found, key=list(PHASES).index)
    options = ProjectWorkspace(source).read()["options"]
    return reopen(workspace, project_id, engine, source, options, earliest)


def reports(plan):
    """Whether the run *plan* reports to the assistant's progress report and
    checkpoints the game's work; a Manual run (project MANUAL) has no
    assistant and writes nothing into the game."""
    return plan.get("method") != MANUAL


def refresh(workspace, project_id, engine, plan, *, started=False):
    """Republishes the last report with counts from the plan's saved results.

    New results reopen translation and every phase after it. A run that
    starts or resumes answers the question the assistant last stopped on,
    such as approving this run; a question it reports during the run stays.
    """
    if not reports(plan):
        return
    source, options = plan["source"], plan["options"]
    verify_evidence(source, plan["evidence"])
    engine.verify_bindings(source, plan["original_bindings"])
    with _lock(workspace, project_id):
        report: dict[str, Any] = (
            _last(workspace, project_id, source, _checked(engine, source, options))
            or {}
        )
        relative, changed = Results(source).export(plan)
        report.update(text=relative, inputs=list(plan["evidence"]))
        phases = report.setdefault("phases", {})
        if changed:
            phases.update(injection="pending", qa="pending", patch="pending")
        if started:
            report["blocker"] = ""
        if changed or started:
            report["phase"] = "translation"
            if not report.get("blocker"):
                phases["translation"] = "active"
                report["next_action"] = NEXT_ACTION
            elif phases.get("translation") != "blocked":
                phases["translation"] = "active"
        engine.progress(source, options, report)
        _keep(workspace, project_id, report)
