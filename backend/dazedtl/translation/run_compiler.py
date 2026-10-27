"""Compiles a translation run in an operation worker.

Grouping a big game's units, then compiling, pricing and saving thousands of
requests takes tens of seconds. The app only checks drafts, ownership and the
settings the run freezes, and starts this worker, so the interface and the
project helper, which share its one dispatch, keep their answers meanwhile.
"""

import hashlib
import os
from pathlib import Path

from dazedtl import system
from dazedtl.compatibility.batch_window import RUN_POLICY as BATCH_WINDOW
from dazedtl.settings.execution import worker_secret
from dazedtl.storage import write_json

from . import census, organize, progress_report, skill_users
from .compilation import batch_sources, compile_requests
from .files import evidence, project_path, read_json, verify_evidence
from .jobs import RunStore, now
from .operations import census_path, census_stale, lifecycle, require_baseline
from .project import WORK, ProjectWorkspace, scope
from .requests import plan_input, quote
from .results import Results

# Operations the app starts with the settings a run freezes; the helper's
# operation command can't start them.
ACTIONS = frozenset({"organize", "compile"})
SCOPE_RULES = WORK + "/work/scope-rules.json"
CENSUS_UNCOVERED = WORK + "/work/census-uncovered.json"


def coverage_path(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id / "coverage.json"


def inventory_path(workspace, project_id):
    return Path(workspace) / "translation/projects" / project_id / "inventory.json"


def census_sha256(workspace, project_id):
    path = census_path(workspace, project_id)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def require_coverage(scope):
    """Complete means the tool saw every Japanese run the game holds
    extracted or set aside by a rule; the assistant's word is not enough."""
    if scope is None:
        raise ValueError(
            "Run census first: --complete needs the tool's own count of the game's Japanese text."
        )
    if scope["stale"]:
        raise ValueError(
            "The census no longer counts the game as it is: the game was updated, or this DazedTL counts more of its text. Run census again."
        )
    if scope["needs_dump"]:
        raise ValueError(
            "The census can't read "
            + ", ".join(scope["needs_dump"][:5])
            + ". Decode it with Len's tools into a folder in the game, then run census --decoded <folder>."
        )
    if scope["untraced"] > max(50, scope["unit_runs"] // 4):
        raise ValueError(
            f"The census never saw {scope['untraced']:,} of your units' Japanese runs, so it can't read where this game keeps its text. Decode it with Len's tools and run census --decoded <folder>."
        )
    if scope["uncovered"]:
        fields = "; ".join(
            f"{row['kind']} {row['field']}: {row['runs']:,}"
            for row in scope["uncovered_fields"][:8]
        )
        raise ValueError(
            f"{scope['uncovered']:,} Japanese runs in the game are not extracted ({fields}). Extract them, or set aside text the player never sees with a rule in "
            + SCOPE_RULES
            + "; "
            + CENSUS_UNCOVERED
            + " lists each location."
        )


def require_whole_messages(messages):
    """Units hold whole messages: requests carry a fixed number of units, so
    a unit per stored line multiplies requests and cuts sentences apart."""
    if messages and messages[0] * 2 > messages[1]:
        raise ValueError(
            f"Your units split {messages[0]:,} of {messages[1]:,} checked RPG Maker messages into a unit per line. "
            "Save each message, a run of consecutive 401 or 405 lines, as one unit with its lines joined by newlines, "
            "then organize again; a unit per line multiplies requests and cuts sentences apart."
        )


def scope_coverage(engine, workspace, project_id, root, units):
    """How the census is covered by these units, the glossary and the
    scope rules, saved for Progress, with the RPG Maker messages the
    units split line by line; None before a census. The uncovered runs
    go to a file by location, so the extractor can be fixed."""
    path = census_path(workspace, project_id)
    if not path.exists():
        system.unlink(coverage_path(workspace, project_id), missing_ok=True)
        return None, None
    value = read_json(path)
    rules_file = project_path(root, SCOPE_RULES, exists=False)
    rules = census.rules_input(
        read_json(rules_file) if rules_file.exists() else None,
        census.fields(value),
        census.files(value),
        census.counted_language(value),
    )
    report, uncovered = census.coverage(
        value,
        [unit["source"] for unit in units],
        engine.glossary_terms(root),
        rules,
    )
    report.update(
        stale=bool(census_stale(workspace, project_id, root)),
        source="assistant_dump" if value["decoded"] else "tool",
        needs_dump=[] if value["decoded"] else value["needs_dump"],
        unreadable=len(value["unreadable"]),
        uncovered_fields=census.summary(uncovered),
    )
    write_json(
        project_path(root, CENSUS_UNCOVERED, exists=False),
        {"uncovered": uncovered, "unreadable": value["unreadable"]},
    )
    write_json(coverage_path(workspace, project_id), {**report, "checked_at": now()})
    return report, census.split_messages(value, [unit["source"] for unit in units])


def saved_coverage(workspace, project_id, root, state=None):
    """The last coverage organize found, for Progress: stale once a later
    census replaced the one it was counted against, or the census no longer
    counts the game's current version, as after a game update."""
    path = coverage_path(workspace, project_id)
    try:
        value = read_json(path)
        counted = os.stat(path).st_mtime_ns
    except ValueError, OSError:
        return None
    if not value.get("stale"):
        try:
            replaced = os.stat(census_path(workspace, project_id)).st_mtime_ns > counted
        except FileNotFoundError:
            replaced = True
        value["stale"] = replaced or bool(
            census_stale(workspace, project_id, root, state)
        )
    return value


def guidance_inputs(source):
    root = Path(source)
    result = []
    for relative in (
        ".dazedtl/glossary.txt",
        ".dazedtl/reference-games.json",
        ".dazedtl/skills/game.md",
        ".dazedtl/skills/quirks.md",
    ):
        path = project_path(root, relative, exists=False)
        if path.is_file():
            result.append(relative)
    folder = root / ".dazedtl/skills"
    if folder.is_dir():
        result.extend(
            path.relative_to(root).as_posix()
            for path in folder.glob("*.md")
            if path.relative_to(root).as_posix() not in result
        )
    return result


def claude_inputs(engine, workspace, cfg, requests):
    """Anthropic bills by Claude's tokenizer, so its quote counts with it
    when the endpoint answers; None keeps the approximate count."""
    if cfg["protocol"] != "anthropic" or not requests:
        return None
    try:
        secret = worker_secret(workspace, cfg)
    except ValueError:
        return None
    return engine.claude_input_tokens(requests, cfg, secret)


def claude_cache(engine, cfg, requests, counted):
    """What Claude's cached instructions cost, for its quote's range; None
    for other providers."""
    if cfg["protocol"] != "anthropic" or not requests:
        return None
    return engine.claude_cache(requests, cfg, counted)


def prepare(engine, workspace, job, plan, progress):
    """Runs an organize or compile operation; its result names the new run."""
    if plan["action"] == "organize":
        return _organize(engine, workspace, job, plan, progress)
    input_path = plan["arguments"].get("input_path")
    if plan.get("finishes"):
        # A run of declined requests compiles the plan the assistant's run did.
        _declined, declined_plan = RunStore(workspace).load(
            plan["finishes"], job["project_id"]
        )
        input_path = declined_plan["input_path"]
    return {"run": compile_run(engine, workspace, job, plan, input_path, progress)}


def _organize(engine, workspace, job, plan, progress):
    """Groups the lines Len's extractor saved into a source plan, so the
    assistant never reads or rewrites the game's text to group it, then
    compiles the run. The result carries counts only."""
    project_id, root = job["project_id"], Path(plan["source"])
    input_path, complete = (
        plan["arguments"]["input_path"],
        plan["arguments"]["complete"],
    )
    frozen = plan["compile"]
    # The units' bytes as read, which the compiled run must still find.
    read = evidence(root, [input_path])
    units = organize.units_input(read_json(ProjectWorkspace(root).artifact(input_path)))
    progress("Checking the units against the census")
    coverage, messages = scope_coverage(engine, workspace, project_id, root, units)
    require_whole_messages(messages)
    if complete:
        require_coverage(coverage)
        write_json(
            inventory_path(workspace, project_id),
            {
                "census_sha256": census_sha256(workspace, project_id),
                "units": len(units),
            },
        )
    progress(f"Grouping {len(units):,} lines into requests")
    value = organize.plan(
        units,
        input_path,
        complete,
        frozen["lines"],
        frozen["characters"],
        frozen.get("shared"),
    )
    relative = organize.plan_path(value)
    path = project_path(root, relative, exists=False)
    if not path.exists() or read_json(path) != value:
        write_json(path, value)
    summary = organize.summary(units, value)
    if coverage is not None:
        summary["coverage"] = coverage
    run = compile_run(engine, workspace, job, plan, relative, progress, read)
    return {"run": run, "summary": summary}


def compile_run(engine, workspace, job, plan, input_path, progress, read=None):
    """Compiles the source plan into a new run and returns its ID. A run that
    finishes another run's declined requests quotes only what has no saved
    translation yet. ``read`` holds the hashes of input files read earlier,
    which must not have changed since."""
    project_id, root, selected = (
        job["project_id"],
        Path(plan["source"]),
        plan["options"],
    )
    frozen = plan["compile"]
    cfg = frozen["configuration"]
    finishes = plan.get("finishes")
    require_baseline(engine, root, selected, lifecycle(workspace, project_id))
    raw = plan_input(read_json(ProjectWorkspace(root).artifact(input_path)))
    if cfg["mode"] != "agent" and not raw["complete"] and not finishes:
        raise ValueError(
            "API cost review requires the complete independently audited request corpus."
        )
    # Declined lines keep the Assistant only run's larger requests, so
    # their translations land where that run reads them.
    if (
        not finishes
        and cfg["entries_per_request"]
        and any(
            len(batch["sources"]) > cfg["entries_per_request"]
            for batch in raw["batches"]
        )
    ):
        raise ValueError(
            "A batch exceeds the configured entries per request. Split at a coherent boundary with source context, or adjust the model setting."
        )
    inputs = list(dict.fromkeys([input_path, *raw["inputs"], *guidance_inputs(root)]))
    for path in inputs:
        project_path(root, path, exists=False)
    bindings = engine.source_bindings(root, raw["inputs"])
    before = evidence(root, [path for path in inputs if path not in bindings])
    if read and any(
        before.get(path, sha256) != sha256 for path, sha256 in read.items()
    ):
        raise ValueError(
            "The units file changed while DazedTL organized it. Organize it again."
        )
    progress(f"Compiling {len(raw['batches']):,} requests")
    requests, compiler = compile_requests(
        engine,
        root,
        selected,
        raw,
        cfg["language"],
        skill_users.notes(workspace, project_id, root, cfg, batch_sources(raw)),
    )
    verify_evidence(root, before)
    engine.verify_bindings(root, bindings)
    store = RunStore(workspace)
    store.overlapping(project_id, {row["fingerprint"] for row in requests})
    limits = None
    if cfg["mode"] != "agent":
        # A Batch runner counts each request's tokens when it packs them.
        limits = engine.batch_limits(cfg) if frozen["batch"] else None
        for index, request in enumerate(requests, 1):
            progress(f"Building provider requests: {index:,} of {len(requests):,}")
            request["params"] = engine.payload(request, cfg)
    results = Results(root)
    pending = [row for row in requests if not results.get(row)]
    estimate = None
    if cfg["mode"] != "agent":
        progress(f"Estimating the cost of {len(pending):,} requests")
        counted = claude_inputs(engine, workspace, cfg, pending)
        provider = engine.batch_supported(cfg)
        estimate = quote(
            pending,
            cfg,
            provider,
            engine.token_count,
            counted.total if counted else None,
            claude_cache(engine, cfg, pending, counted),
            engine.openai_cache(pending) if provider == "openai" else None,
        )
    progress("Saving the run")
    value = {
        "version": 1,
        "kind": "translation",
        "source": str(root),
        "options": selected,
        "scope_sha256": scope(selected),
        "configuration": cfg,
        "requests": requests,
        "complete": raw["complete"],
        "evidence": before,
        "original_bindings": bindings,
        "compiler": compiler,
        "input_path": input_path,
        "batch_limits": limits,
    }
    if limits:
        # Its chunks wait for room in the provider's Batch window.
        value["batch_window"] = BATCH_WINDOW
    if finishes:
        value.update(label="Declined requests", finishes=finishes)
    run = store.create(project_id, value, estimate)
    progress_report.refresh(workspace, project_id, engine, value)
    return run["id"]
