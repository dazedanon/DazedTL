"""Rebuild logical requests without rewriting saved plans or paid-work approvals."""

from dazedtl.freshness import Basis, compare

from . import name_codes, skill_users
from .files import project_path, read_json
from .requests import logical_request, plan_input

# Raise when the same plan input compiles to different requests or provider
# payloads. Plans saved before 2.25 hold a digest of the compiler's source
# files instead, so their payloads are checked again.
COMPILER_VERSION = 1


def compile_requests(
    engine, source, options, raw, language, skill_users=None, actor_variables=None
):
    """The plan's requests. ``skill_users`` holds the notes on its units'
    skill users that the run's policy gives them (translation/skill_users),
    and ``actor_variables`` what its name-code policy gives its sources
    (translation/name_codes variables)."""
    if not raw["batches"]:
        # Organize found every line translated; nothing reads the game.
        return [], COMPILER_VERSION
    compiled = engine.compile(
        source, options, raw, language, skill_users or {}, actor_variables
    )
    if len(compiled) != len(raw["batches"]):
        raise ValueError("The engine compiler did not return every source batch.")
    return [
        logical_request(batch, row["context"])
        for batch, row in zip(raw["batches"], compiled)
    ], COMPILER_VERSION


def batch_sources(raw):
    """Every unit's source text in a source plan, by unit ID."""
    return {
        identity: text
        for batch in raw["batches"]
        for identity, text in batch["sources"].items()
    }


CHANGED = "Shared guidance, source metadata or references changed. Compile and review a new plan."
# Digests of a request's context that also cover where its game was, so a
# moved game's requests compare without them; what they cover that the model
# reads is in the context itself, as the request's fingerprint has it.
LOCATED = {"context_sha256", "request_sha256"}


def portable(row):
    """A compiled request without the digests that name its game's folder."""
    context = row.get("context")
    if not isinstance(context, dict):
        return row
    return {
        **row,
        "context": {key: item for key, item in context.items() if key not in LOCATED},
    }


def verify_compilation(engine, workspace, project_id, plan, index=None):
    """Compiles the plan's requests again and refuses any that changed. With
    index, only that request: its context depends on its own batch, the
    shared guidance and the original game alone, so compiling that batch
    gives the request the whole plan would, and an import need not wait for
    every other one."""
    # Unversioned source plans are accepted only when validating an existing,
    # immutable run. New compilation always requires the current input contract.
    raw = plan_input(
        read_json(project_path(plan["source"], plan["input_path"])),
        allow_legacy=True,
        allow_empty=bool(plan.get("reused") or plan.get("converted")),
    )
    saved = plan["requests"]
    if index is not None:
        if len(raw["batches"]) != len(saved):
            raise ValueError(CHANGED)
        raw = {**raw, "batches": [raw["batches"][index]]}
        saved = [saved[index]]
    current, compiler = compile_requests(
        engine,
        plan["source"],
        plan["options"],
        raw,
        plan["configuration"]["language"],
        skill_users.notes(
            workspace,
            project_id,
            plan["source"],
            plan["configuration"],
            batch_sources(raw),
        ),
        name_codes.variables(
            engine,
            workspace,
            project_id,
            plan["source"],
            plan["configuration"],
            batch_sources(raw),
        ),
    )
    if len(current) != len(saved) or any(
        portable(row) != portable({key: request.get(key) for key in row})
        for row, request in zip(current, saved)
    ):
        raise ValueError(CHANGED)
    if compare(Basis(plan["compiler"], {}), Basis(compiler, {})):
        # A compatible code update need not orphan accepted results or approved
        # work. New paid calls still require exactly the reviewed provider bytes.
        for row, request in zip(current, saved):
            if plan["configuration"]["mode"] != "agent" and engine.payload(
                row, plan["configuration"]
            ) != request.get("params"):
                raise ValueError(
                    "The provider payload changed. Compile and review a new plan before further paid work."
                )
