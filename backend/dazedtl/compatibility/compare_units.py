"""Model comparisons of an Assistant-led or Manual game (compatibility/compare
runs those of a Guided game).

Its lines are the units its extractor saved: the first of one group, whole
scenes at a time. Each model's requests are organized, compiled and priced
as an API run of the game would build them (translation/run_compiler), but
against a private copy of the game's guidance, which a Tune test may
change, and sent by the run's own Live runner from a run store of the
operation's own (``Store``), so no reply reaches the game's results, its
runs or its reuse.
"""

import shutil
from pathlib import Path

from dazedtl import system
from dazedtl.translation.files import project_path, read_json

# The game's guidance a request reads (util/len_translation shared_context
# and reference_context), copied to a comparison's own game folder.
GUIDANCE = (
    ".dazedtl/glossary.txt",
    ".dazedtl/settings.json",
    ".dazedtl/reference-games.json",
    ".dazedtl/reference-index.json",
    ".dazedtl/reference-overlaps.json",
    # Legacy guidance the compile moves into .dazedtl.
    "glossary.txt",
    "translation_quirks.txt",
)
FOLDERS = (".dazedtl/skills", ".dazedtl/reference-data", "skills")
INSTRUCTION = ".dazedtl/skills/comparison.md"


def units(root, relative, group, lines):
    """The first *lines* units of *group* that a request sends, all for 0,
    whole scenes at a time, and those of them the run writes without a
    request (organize.unsent) left out."""
    from dazedtl.translation import organize

    found = [
        unit
        for unit in organize.units_input(read_json(project_path(root, relative)))
        if group is None or unit["group"] == group
    ]
    if lines and len(found) > lines:
        last = found[lines - 1]["scene"]
        scenes = list(dict.fromkeys(unit["scene"] for unit in found))
        keep = set(scenes[: scenes.index(last) + 1])
        found = [unit for unit in found if unit["scene"] in keep]
    return found


def sources(found):
    return [
        {"id": unit["id"], "speaker": unit["speaker"] or "", "source": unit["source"]}
        for unit in found
    ]


def stage(root, target, candidate):
    """A game folder holding a copy of the game at *root*'s guidance, with
    a candidate's test-only glossary and instruction over it."""
    root, target = Path(root), Path(target)
    for relative in GUIDANCE:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target / relative)
    for relative in FOLDERS:
        path = root / relative
        if path.is_dir() and not path.is_symlink():
            shutil.copytree(path, target / relative, symlinks=False)
    (target / ".dazedtl").mkdir(parents=True, exist_ok=True)
    if candidate.get("glossary") is not None:
        from util.vocab import write_game_vocab

        # As Context saves it: over a legacy glossary moved into .dazedtl,
        # with the shipped base after it.
        write_game_vocab(candidate["glossary"], game_root=target)
    if (candidate.get("instruction") or "").strip():
        (target / INSTRUCTION).parent.mkdir(parents=True, exist_ok=True)
        system.write_text(target / INSTRUCTION, candidate["instruction"])
    return target


def build(engine, workspace, options, candidate, found, game):
    """A candidate's requests for *found*, compiled against its staged
    *game*, with their provider payloads, and the earlier lines each later
    part of a split scene quotes (organize.layout)."""
    from util.request_packing import SHARED_LINES

    from dazedtl.translation import name_codes, organize, skill_users
    from dazedtl.translation.compilation import batch_sources, compile_requests
    from dazedtl.translation.requests import plan_input

    cfg = candidate["configuration"]
    root, project_id = options["source"], options["projectId"]
    value, preceding = organize.layout(
        found,
        options["inputPath"],
        True,
        cfg["entries_per_request"],
        organize.MAX_CHARACTERS,
        SHARED_LINES,
        None,
    )
    raw = plan_input(value)
    requests, _compiler = compile_requests(
        engine,
        game,
        options["selected"],
        raw,
        cfg["language"],
        skill_users.notes(workspace, project_id, root, cfg, batch_sources(raw)),
        name_codes.variables(
            engine, workspace, project_id, root, cfg, batch_sources(raw)
        ),
        staged=True,
    )
    for request in requests:
        request["params"] = engine.payload(request, cfg)
    return requests, preceding


def estimate(engine, candidate, requests):
    """The candidate's Live quote, as an API run's review prices it."""
    from dazedtl.translation.requests import quote

    cfg = candidate["configuration"]
    return quote(requests, cfg, engine.batch_supported(cfg), engine.token_count)


def run_store(folder, game):
    """A run store under *folder* whose runs' game is *game*, the
    comparison's own copy, so their results land there."""
    from dazedtl.translation.jobs import RunStore

    class Store(RunStore):
        def source(self, project_id):
            return str(game)

    return Store(folder)


def translate(
    engine, workspace, options, candidate, requests, preceding, game, folder, stopped
):
    """Sends the requests with the API run's Live runner and returns each
    unit's translation, the cost and the requests with their replies."""
    from dazedtl.settings.execution import worker_secret
    from dazedtl.translation.organize import DELIVERED
    from dazedtl.translation.repricing import route_of
    from dazedtl.translation.results import QUOTES, Results
    from dazedtl.translation.runner import Runner

    from .estimate_prices import usage_cost
    from .translation import TranslationProvider

    cfg = candidate["configuration"]
    store = run_store(folder, game)
    plan = {
        "version": 1,
        "kind": "translation",
        "source": str(game),
        "options": options["selected"],
        "scope_sha256": "",
        "configuration": cfg,
        "requests": requests,
        "complete": True,
        "evidence": {},
        "original_bindings": {},
        "compiler": 1,
        "input_path": options["inputPath"],
        "batch_limits": None,
        QUOTES: options["quotes"],
        "delivered": DELIVERED,
        "preceding": preceding,
    }
    job = store.create(options["projectId"], plan, {"live_cost": 0})
    provider = TranslationProvider(cfg, worker_secret(workspace, cfg))

    def current():
        if stopped():
            raise InterruptedError("Stopped.")

    from .compare import KEPT_REQUESTS, STOPPED, _message

    runner = Runner(store, job["id"], provider, current)
    failure = None
    try:
        runner.step(recover=False)
    except InterruptedError:
        failure = STOPPED
    except (OSError, RuntimeError, ValueError) as error:
        failure = _message(error)
    # What came back before a stop or a failure is kept, with its cost.
    results = Results(game)
    lines = {}
    for request in requests:
        value = results.get(request) or {}
        for unit, text in (value.get("translations") or {}).items():
            lines[unit] = {"speaker": "", "text": text}
    record = store.record(job["id"])
    usage = record.get("usage") or {}
    cost = usage_cost(
        usage, cfg, route_of(engine, cfg), (record.get("request_usage") or {}).values()
    )
    shown = []
    # The first ones, as a Guided model's result keeps them.
    for index, request in enumerate(requests[:KEPT_REQUESTS]):
        path = runner.response_path(request["id"])
        response = read_json(path) if path.is_file() else {}
        params = request["params"]
        shown.append(
            {
                "index": index,
                "total": len(requests),
                "state": record["states"][request["id"]]["state"],
                "source": request["sources"],
                "context": None,
                "parameters": {
                    key: value
                    for key, value in params.items()
                    if key not in {"messages", "system"}
                },
                "messages": params.get("messages"),
                "system": params.get("system"),
                "exact": params,
                "response": response.get("text"),
                "usage": {
                    key: float(value)
                    for key, value in response.items()
                    if key.endswith("tokens") and isinstance(value, (int, float))
                },
            }
        )
    failed = [
        row["message"]
        for row in record["states"].values()
        if row["state"] != "accepted" and row.get("message")
    ]
    return {
        "lines": lines,
        "cost": round(float(cost or 0), 6),
        "requests": shown,
        "requestCount": len(requests),
        **({"error": failure or failed[0]} if failure or failed and not lines else {}),
    }
