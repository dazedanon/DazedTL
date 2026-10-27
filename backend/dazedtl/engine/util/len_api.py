"""Len request plans. No translation/provider calls or keys."""
from __future__ import annotations

import hashlib
import json

from util.freshness import Basis
from util.len_translation import LenProject, request_contexts


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _evidence(project, paths):
    from util.len_progress import _read_artifact
    if not isinstance(paths, list) or not paths:
        raise ValueError("The request plan needs source/guidance input paths, relative to the game.")
    evidence = {}
    for path in paths:
        _read_artifact(project.game_root, path, evidence)
    return [{"path": key, "sha256": evidence[key]["sha256"]} for key in sorted(evidence)]


# Recorded in each compiled plan; raise when the same plan input compiles to
# different requests, such as after a template or prompt change.
PLAN_VERSION = 1


def _plan_basis():
    return Basis(PLAN_VERSION, {})


def compile_plan(project: LenProject, plan: dict) -> dict:
    if (not isinstance(plan, dict) or set(plan) != {"complete", "inputs", "batches"}
            or type(plan["complete"]) is not bool):
        raise ValueError("A request plan requires complete, inputs and batches.")
    inputs = _evidence(project, plan["inputs"])
    requests = request_contexts(project, plan["batches"])
    if inputs != _evidence(project, plan["inputs"]):
        raise ValueError("Source inputs changed during compilation; retry the plan.")
    for request in requests:
        request["sources_sha256"] = _hash(_canonical(request["sources"]))
    return {"schema": 1, "complete": plan["complete"], "compiler": _plan_basis().record(),
            "inputs": inputs, "batches": requests,
            "scope_sha256": _scope(project)}


def _scope(project):
    return _hash(_canonical({"images": project.include_images, "instructions": project.instructions,
                             "base_glossary": project.include_glossary_base, "install_forge": project.install_forge}))
