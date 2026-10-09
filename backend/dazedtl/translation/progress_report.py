"""The assistant's progress report, which the app republishes with counts from
saved results. The helper, the app and a run's worker all rewrite it, so each
holds the project's progress lock while it reads, changes and publishes."""

from pathlib import Path
from typing import Any

from dazedtl.storage import exclusive, write_json
from dazedtl.translation.files import project_path, read_json, verify_evidence
from dazedtl.translation.project import WORK
from dazedtl.translation.results import Results

REPORT = WORK + "/progress-report.json"
NEXT_ACTION = "Continue saved work, then fit, inject and perform QA."


def _lock(workspace, project_id):
    return exclusive(
        Path(workspace) / "translation/projects" / project_id / "progress.lock"
    )


def publish(workspace, project_id, engine, source, options, report):
    """Publishes the assistant's complete report, then keeps it as the one
    later refreshes build on."""
    with _lock(workspace, project_id):
        value = engine.progress(source, options, report)
        write_json(project_path(source, REPORT, exists=False), report)
    return value


def update(workspace, project_id, engine, source, options, change):
    """Republishes the last report after change edits it in place; nothing
    happens before the assistant's first report."""
    with _lock(workspace, project_id):
        path = project_path(source, REPORT, exists=False)
        if not path.exists():
            return None
        report = read_json(path)
        change(report)
        value = engine.progress(source, options, report)
        write_json(path, report)
    return value


def refresh(workspace, project_id, engine, plan, *, started=False):
    """Republishes the last report with counts from the plan's saved results.

    New results reopen translation and every phase after it. A run that
    starts or resumes answers the question the assistant last stopped on,
    such as approving this run; a question it reports during the run stays.
    """
    verify_evidence(plan["source"], plan["evidence"])
    engine.verify_bindings(plan["source"], plan["original_bindings"])
    with _lock(workspace, project_id):
        path = project_path(plan["source"], REPORT, exists=False)
        report: dict[str, Any] = read_json(path) if path.exists() else {}
        relative, changed = Results(plan["source"]).export(plan)
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
        engine.progress(plan["source"], plan["options"], report)
        write_json(path, report)
