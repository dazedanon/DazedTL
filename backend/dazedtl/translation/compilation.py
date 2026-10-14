"""Rebuild logical requests without rewriting saved plans or paid-work approvals."""

from .files import project_path, read_json
from .requests import logical_request, plan_input


def compile_requests(engine, source, options, raw, language):
    compiled, compiler = engine.compile(source, options, raw, language)
    if len(compiled) != len(raw["batches"]):
        raise ValueError("The engine compiler did not return every source batch.")
    return [
        logical_request(batch, row["context"])
        for batch, row in zip(raw["batches"], compiled)
    ], compiler


CHANGED = "Shared guidance, source metadata or references changed. Compile and review a new plan."


def verify_compilation(engine, plan, index=None):
    """Compiles the plan's requests again and refuses any that changed. With
    index, only that request: its context depends on its own batch and the
    shared guidance alone, so compiling that batch gives the request the
    whole plan would, and an import need not wait for every other one."""
    # Unversioned source plans are accepted only when validating an existing,
    # immutable run. New compilation always requires the current input contract.
    raw = plan_input(
        read_json(project_path(plan["source"], plan["input_path"])), allow_legacy=True
    )
    saved = plan["requests"]
    if index is not None:
        if len(raw["batches"]) != len(saved):
            raise ValueError(CHANGED)
        raw = {**raw, "batches": [raw["batches"][index]]}
        saved = [saved[index]]
    current, compiler = compile_requests(
        engine, plan["source"], plan["options"], raw, plan["configuration"]["language"]
    )
    if len(current) != len(saved) or any(
        row != {key: request.get(key) for key in row}
        for row, request in zip(current, saved)
    ):
        raise ValueError(CHANGED)
    if compiler != plan["compiler"]:
        # A compatible code update need not orphan accepted results or approved
        # work. New paid calls still require exactly the reviewed provider bytes.
        for row, request in zip(current, saved):
            if plan["configuration"]["mode"] != "agent" and engine.payload(
                row, plan["configuration"]
            ) != request.get("params"):
                raise ValueError(
                    "The provider payload changed. Compile and review a new plan before further paid work."
                )
    return compiler
