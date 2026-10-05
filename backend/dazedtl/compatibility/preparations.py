"""Discard only app-created, unapproved preparation; retain all paid evidence."""

import shutil
import sqlite3

from .process_view import saved, evidence_root


def temporary(job):
    return (
        job.get("dazedtl_preapproval") is True
        and not job.get("dazedtl_approved")
        and not job.get("dazedtl_submission_intent")
    )


def discardable(job, root):
    if not temporary(job) or job.get("dazedtl_submission_intent"):
        return False
    # Authorization is the primary guard. Retained provider evidence is an
    # independent backstop against deleting an inconsistent or older record.
    from .request_scope import requests

    try:
        evidence = evidence_root(root)
        state = saved(evidence, "batch_state.json")
        if (
            state.get("batches")
            or state.get("status")
            in {
                "submitting",
                "submitted",
                "partially_submitted",
                "submission_uncertain",
                "fetched",
            }
            or saved(evidence, "batch_history.json").get("batches")
            or saved(evidence, "batch_results.json")
        ):
            return False
        return all(
            row["state"] in {"prepared", "queued"} for row in requests(root, job)
        )
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return False


def discard(job, root):
    if not discardable(job, root):
        raise ValueError("This run may contain approved work. Keep it for recovery.")
    if root.is_symlink() or root.parent.is_symlink() or root.parent.parent.is_symlink():
        raise ValueError("Temporary preparation must stay inside its run folder.")
    shutil.rmtree(root)
