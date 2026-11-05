"""Translate the same lines of a Guided game with several models, in a
comparison operation (translation/compare).

Each model gets its own staged engine run of one data file, the game's
recorded original cut down to the lines chosen (``cut``), built exactly as
a Translate run builds its requests: the game's guidance, glossary, speaker
names, workflow options and the model's frozen request policy
(full_estimate.stage_run). An estimate prices each run offline; a translate
operation, which only an approved estimate starts, sends them Live. Nothing
reaches the game, its working copies, its translation cache or its runs:
every run's folder is the operation's own, and only the lines each model
wrote, its cost, time and requests come back.
"""

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dazedtl import system
from dazedtl.actions import stopped_note
from dazedtl.translation.files import digest

from .full_estimate import (
    ENGINE,
    WORKER,
    counted,
    end,
    engine_configuration,
    launch,
    stage_run,
)

ESTIMATE, TRANSLATE = "compare_estimate", "compare_translate"
ACTIONS = (ESTIMATE, TRANSLATE)
# The requests a model's result keeps for Show request.
KEPT_REQUESTS = 20
# What a comparison's test-only guidance is saved as in a run's snapshot,
# beside the game's own guidance files, which every request carries.
INSTRUCTION = "game/.dazedtl/skills/comparison.md"
GLOSSARY = "game/.dazedtl/glossary.txt"
# An event command that ends a command list.
END = {"code": 0, "indent": 0, "parameters": []}


def _event_lists(name, document):
    """Each command list of an event file, in file order, by its path."""
    from util import rpgmaker_blocks as blocks

    from dazedtl.translation.file_lines import _events

    return [
        listed for listed, _commands in blocks.command_lists(_events(name, document))
    ]


def cut(name, document, phase, lines, markers=frozenset()):
    """*document* holding only its first *lines* lines that hold Japanese,
    all of them for 0, cut where its requests are built from: an event file
    after the command list of the last line, whose later lists end at once,
    a database file after the first entries holding that many lines. What the cut keeps is
    the file's own, so its requests are as a run of the whole file builds
    them, but for the last request, which may pack fewer lines. Returns the
    cut document and the lines it keeps."""
    from copy import deepcopy

    from dazedtl.translation.file_lines import _resolve
    from dazedtl.translation.file_lines import lines as read

    found = [line for line in read(name, document, phase, markers) if _japanese(line)]
    if not lines or len(found) <= lines:
        return document, found
    value = deepcopy(document)
    if phase == "database":
        if not isinstance(value, list):
            return document, found
        # Entries in their order, until they hold the lines asked for.
        counts = {}
        for line in found:
            counts[line.paths[0][0]] = counts.get(line.paths[0][0], 0) + 1
        total, end = 0, 0
        for entry in sorted(counts):
            total += counts[entry]
            end = entry
            if total >= lines:
                break
        for index in range(end + 1, len(value)):
            value[index] = None
        return value, [line for line in found if line.paths[0][0] <= end]
    last = found[lines - 1].paths[0]
    lists = [tuple(listed) for listed in _event_lists(name, value)]

    def owner(path):
        return next(
            (
                index
                for index, listed in enumerate(lists)
                if path[: len(listed)] == listed
            ),
            None,
        )

    end = owner(last)
    if end is None:
        return document, found[:lines]
    for listed in lists[end + 1 :]:
        _resolve(value, listed)[:] = [dict(END)]
    # Lines outside any command list, such as a map's display name, stay.
    kept = [line for line in found if (owner(line.paths[0]) or 0) <= end]
    return value, kept


def _japanese(line):
    from util.source_text import source_left

    return any(source_left(text) for text, _source in line.sent()) or any(
        source_left(source) for source in line.sources
    )


def pointer(line):
    """A line's place in the original file, which names its row."""
    return "/" + "/".join(str(part) for part in line.paths[0])


def _key(line):
    """What a line of the original and its translation share: the engine
    may join a message's rows or split it into pages, so places differ,
    but the translation keeps the Japanese it replaced (file_lines
    `shown_source`)."""
    return line.kind, line.shown_source()


def rows(name, document, phase, found, markers=frozenset()):
    """Each line of a translated *document* by the ``pointer`` of the line
    of the original it translates (*found*, in file order): the speaker its
    name box names, and its text."""
    from collections import defaultdict

    from dazedtl.translation.file_lines import _UNKEPT
    from dazedtl.translation.file_lines import lines as read

    places = defaultdict(list)
    # A map name or note label keeps no Japanese in its translation, so the
    # translation of each is the one in its place in file order.
    unkept = defaultdict(list)
    for line in found:
        places[_key(line)].append(pointer(line))
        if line.kind in _UNKEPT:
            unkept[line.kind].append(pointer(line))
    result = {}
    for line in read(name, document, phase, markers):
        waiting = places.get(_key(line)) or unkept.get(line.kind)
        if not waiting:
            continue
        texts = [text for text, _source in line.sent()]
        speaker = ""
        if line.units and len(line.paths) > 1 and line.paths[0][-1] == 4:
            speaker, texts = texts[0], texts[1:]
        place = waiting.pop(0)
        for listed in (places.get(_key(line)) or [], unkept.get(line.kind) or []):
            if place in listed:
                listed.remove(place)
        result[place] = {
            "speaker": speaker,
            "text": "\n".join(text for text in texts if text.strip()),
        }
    return result


def sources(found):
    """The lines a comparison shows, from the original file's ``cut``."""
    result = []
    for line in found:
        texts = list(line.sent())
        speaker = ""
        if line.units and len(line.paths) > 1 and line.paths[0][-1] == 4:
            name, texts = texts[0], texts[1:]
            speaker = name[1] or name[0]
        result.append(
            {
                "id": pointer(line),
                "speaker": speaker,
                "source": "\n".join(
                    (source if source and source.strip() else text)
                    for text, source in texts
                    if (source or text).strip()
                ),
            }
        )
    return result


class Activity:
    """Where each model's run stands, reported with every status line."""

    def __init__(self, log, candidates):
        self.log = log
        self.stopped = log.stopped
        self.lock = threading.Lock()
        self.states = {row["index"]: "waiting" for row in candidates}

    def __call__(self, message, index=None, state=None, **_progress):
        with self.lock:
            if index is not None and state:
                self.states[index] = state
            self.log(
                message,
                {
                    "models": [
                        {"index": index, "state": state}
                        for index, state in sorted(self.states.items())
                    ]
                },
            )


def stage(target, workspace, project_id, root, relative, name, phase, lines, markers):
    """The game's recorded original of a data file cut down to its first
    *lines* lines (``cut``), staged under *target* as the engine reads a
    game's data folder, with the lines it keeps."""
    from dazedtl.translation import originals

    original = originals.prepared(workspace, project_id, root)
    if original is None or relative not in original.files:
        raise ValueError(f"{name} has no recorded original to compare.")
    with original.materialized([relative]) as folder:
        document = json.loads(
            system.read_bytes(Path(folder) / relative).decode("utf-8-sig")
        )
    value, found = cut(name, document, phase, lines, markers)
    if not found:
        raise ValueError(f"{name} has no Japanese lines to compare.")
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    path = Path(target) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    inventory = {
        "source": str(target),
        "engine": ENGINE,
        "files": [{"name": name, "bytes": len(raw), "sha256": digest(raw)}],
        "revision": digest([{"name": name, "bytes": len(raw)}]),
    }
    return inventory, found


def guidance(candidate):
    """Writes a candidate's test-only glossary and instruction over the
    game's guidance a run froze, and binds them in its plan."""

    def change(directory, native):
        for relative, text in (
            (GLOSSARY, candidate.get("glossary")),
            (INSTRUCTION, candidate.get("instruction")),
        ):
            if text is None or relative == INSTRUCTION and not text.strip():
                continue
            path = Path(directory) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == GLOSSARY:
                from .compare_units import glossary

                text = glossary(
                    system.read_bytes(path).decode("utf-8-sig")
                    if path.is_file()
                    else "",
                    text,
                )
            system.write_text(path, text)
            native["context_hashes"][relative] = digest(path.read_bytes())

    return change


def translate(directory, env, label, log, index):
    """Runs a staged run's translate worker to its end. The approved quote
    covers its names pass, so a confirmation it asks for is answered yes."""
    with (directory / "log/startup.txt").open("a", encoding="utf-8") as errors:
        process = system.popen(
            [sys.executable, "-u", str(WORKER), str(directory)],
            cwd=directory,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            bufsize=1,
            group=True,
        )
        failure = None
        finished = None
        try:
            assert process.stdout is not None and process.stdin is not None
            for line in process.stdout:
                if log.stopped():
                    raise InterruptedError(stopped_note(TRANSLATE))
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind, args = event.get("event"), event.get("args") or []
                if kind == "speaker_confirmation":
                    log(f"{label} · translating speaker names", index, "translating")
                    process.stdin.write(
                        json.dumps({"command": "speakers", "approved": True}) + "\n"
                    )
                    process.stdin.flush()
                elif kind == "status" and args:
                    log(f"{label} · {args[0]}", index, "translating")
                elif kind == "file_error" and len(args) >= 2 and failure is None:
                    failure = str(args[1])
                elif kind == "finished" and args:
                    finished = args
            process.wait()
        finally:
            end(process)
    if not finished or finished[0] is not True:
        message = failure or (finished[1] if finished and len(finished) > 1 else "")
        raise ValueError(f"{label}: {message or 'the translation did not finish.'}")


# What a line's check found, as the page names it (translation/result_checks
# hits: Text QA's mechanical flags, glossary hint, pronoun check and lint).
FLAGS = {
    "empty-live": "Empty translation",
    "unchanged-source": "Left as it was",
    "source-language-residue": "Source language left in",
    "censor-mask-mismatch": "Censor mask changed",
    "runtime-token-mismatch": "Control codes changed",
    "missing-center-alignment": "Centering code missing",
    "unsafe-bare-center-code": "Centering code changed",
    "visible-number-mismatch": "Numbers changed",
    "suspicious-length-ratio": "Unusual length",
}


def problems(name, found, lines, glossary, pair):
    """Each translated line's check findings by its ID, in words."""
    from util import rpgmaker_qa_lint as lint

    from dazedtl.languages import reading
    from dazedtl.translation.result_checks import GLOSSARY_HINT, hits

    rows = [
        {
            "source": line["source"],
            "translation": lines[line["id"]]["text"],
            "batch": name,
            "source_id": line["id"],
            "request_sha256": "",
        }
        for line in found
        if (lines.get(line["id"]) or {}).get("text", "").strip()
    ]
    if not rows:
        return {}
    with reading(pair["source"], pair["target"]):
        found_hits = hits(rows, glossary, pair["target"])
    result = {}
    for hit in found_hits:
        rule = hit["rule"]
        if rule == GLOSSARY_HINT:
            text = "Glossary: " + "; ".join(
                f"{source} is {english}" for source, english in hit["terms"]
            )
        elif rule in lint.FAMILIES:
            text = lint.FAMILIES[rule]["description"]
        elif "pronouns" in hit:
            text = "Pronoun: " + "; ".join(
                f"{name_} is {gender}" for name_, gender, _pronoun in hit["pronouns"]
            )
        else:
            text = FLAGS.get(rule, rule)
        for unit in hit["units"]:
            listed = result.setdefault(unit["unit"], [])
            if text not in listed:
                listed.append(text)
    return result


def result(directory, name, phase, markers, seconds, original, found, pair):
    """What a finished run returns: each line it wrote, what its checks
    found, its cost and time, and the requests it sent."""
    from .process_view import ledger_payload, ledger_records, paid_receipts

    path = directory / "translated" / name
    if not path.is_file():
        raise ValueError(f"{name} came back without a translation.")
    document = json.loads(system.read_bytes(path).decode("utf-8-sig"))
    paid = paid_receipts(directory)
    records = ledger_records(directory) or []
    lines = rows(name, document, phase, original, markers)
    glossary = directory / GLOSSARY
    return {
        "lines": lines,
        "problems": problems(
            name,
            found,
            lines,
            system.read_bytes(glossary).decode("utf-8-sig")
            if glossary.is_file()
            else "",
            pair,
        ),
        "cost": round(sum(float(item.get("cost") or 0) for item in paid.values()), 6),
        "seconds": round(seconds, 1),
        "requests": [
            ledger_payload(directory, records, index, len(records))
            for index in range(min(len(records), KEPT_REQUESTS))
        ],
        "requestCount": len(records),
    }


def run(plan, log):
    """A comparison operation: estimates each model's run, or, approved,
    translates it."""
    from desktop.backend.manual import worker_environment
    from desktop.backend.workflow_actions import validate_plan

    if plan["options"].get("method") in UNITS:
        return run_units(plan, log)
    validate_plan(plan)
    folder = Path(plan["folder"])
    options = plan["options"]
    action = plan["action"]
    candidates = options["candidates"]
    report = Activity(log, candidates)
    name, phase = options["file"], options["phase"]
    markers = frozenset(options.get("markers") or ())
    with system.staging_folder(folder, "compare-") as root:
        report("Reading the original lines")
        inventory, found = stage(
            root / "source",
            folder.parent.parent,
            options["projectId"],
            plan["project"]["source"],
            options["relative"],
            name,
            phase,
            options["lines"],
            markers,
        )
        stopped = log.stopped

        shown = sources(found)

        def one(candidate):
            index = candidate["index"]
            label = candidate["label"]
            if "error" in candidate:
                report(f"{label} · can't be compared", index, "failed")
                return {"index": index, "error": candidate["error"]}
            directory = root / f"model-{index}"
            report(f"{label} · preparing", index, "preparing")
            workspace = folder.parent.parent
            started = time.monotonic()
            try:
                _, native = stage_run(
                    directory,
                    folder,
                    plan["project"]["source"],
                    inventory,
                    [name],
                    "estimate" if action == ESTIMATE else "translate",
                    options["workflow"],
                    candidate["policy"],
                    stopped,
                    configuration=engine_configuration(workspace, candidate),
                    context=guidance(candidate),
                )
                if action == ESTIMATE:
                    value = counted(
                        directory,
                        workspace,
                        native,
                        options["claudeCount"],
                        lambda env: launch(directory, env, label, index, report),
                        lambda: report(f"{label} · counting Claude tokens", index),
                        stopped,
                    )
                    report(f"{label} · estimated", index, "done")
                    return {"index": index, "estimate": value}
                translate(
                    directory,
                    worker_environment(workspace, native),
                    label,
                    report,
                    index,
                )
                value = result(
                    directory,
                    name,
                    phase,
                    markers,
                    time.monotonic() - started,
                    found,
                    shown,
                    options["pair"],
                )
                report(f"{label} · translated", index, "done")
                return {"index": index, **value}
            except InterruptedError:
                raise
            except (
                OSError,
                RuntimeError,
                ValueError,
                subprocess.SubprocessError,
            ) as error:
                if action == ESTIMATE:
                    # Another model's estimate still prices it.
                    report(f"{label} · could not be estimated", index, "failed")
                    return {"index": index, "error": _message(error)}
                report(f"{label} · failed", index, "failed")
                return {
                    "index": index,
                    "error": _message(error),
                    **_spent(directory),
                }

        with ThreadPoolExecutor(max_workers=len(candidates) or 1) as pool:
            values = list(pool.map(one, candidates))
    return {"file": name, "lines": shown, "models": values}


# The methods whose lines are the units an extractor saved.
UNITS = ("len", "manual")


def run_units(plan, log):
    """A comparison of an Assistant-led or Manual game (compare_units)."""
    from util.paths import runtime_data_profile

    from dazedtl.languages import reading_game

    from . import compare_units
    from .translation import TranslationEngine

    options = plan["options"]
    action = plan["action"]
    workspace = Path(options["workspace"])
    root = options["source"]
    candidates = options["candidates"]
    report = Activity(log, candidates)
    engine = TranslationEngine(workspace / "engine")
    parent = workspace / "translation/projects" / options["projectId"]
    parent.mkdir(parents=True, exist_ok=True)
    with (
        runtime_data_profile(engine.profile),
        reading_game(root),
        system.staging_folder(parent, "compare-") as scratch,
    ):
        report("Reading the lines")
        found = compare_units.units(
            root,
            options["inputPath"],
            options.get("file"),
            options["lines"],
        )
        if not found:
            raise ValueError("These lines hold no text.")
        shown = compare_units.sources(found)
        built = {}
        for candidate in candidates:
            index, label = candidate["index"], candidate["label"]
            if "error" in candidate:
                continue
            report(f"{label} · preparing", index, "preparing")
            game = compare_units.stage(root, scratch / f"model-{index}/game", candidate)
            try:
                built[index] = (
                    game,
                    *compare_units.build(
                        engine, workspace, options, candidate, found, game
                    ),
                )
            except ValueError as error:
                built[index] = error

        def one(candidate):
            index, label = candidate["index"], candidate["label"]
            if "error" in candidate:
                return {"index": index, "error": candidate["error"]}
            value = built[index]
            if isinstance(value, ValueError):
                report(f"{label} · can't be compared", index, "failed")
                return {"index": index, "error": str(value)}
            game, requests, preceding = value
            if action != TRANSLATE:
                report(f"{label} · estimated", index, "done")
                return {
                    "index": index,
                    "estimate": compare_units.estimate(engine, candidate, requests),
                }
            started = time.monotonic()
            try:
                result = compare_units.translate(
                    engine,
                    workspace,
                    options,
                    candidate,
                    requests,
                    preceding,
                    game,
                    scratch / f"model-{index}/runs",
                    log.stopped,
                )
            except (OSError, RuntimeError, ValueError) as error:
                report(f"{label} · failed", index, "failed")
                return {"index": index, "error": _message(error)}
            glossary = game / ".dazedtl/glossary.txt"
            result.update(
                seconds=round(time.monotonic() - started, 1),
                problems=problems(
                    options.get("file") or "",
                    shown,
                    result["lines"],
                    system.read_bytes(glossary).decode("utf-8-sig")
                    if glossary.is_file()
                    else "",
                    options["pair"],
                ),
            )
            report(f"{label} · translated", index, "done")
            return {"index": index, **result}

        with ThreadPoolExecutor(max_workers=len(candidates) or 1) as pool:
            values = list(pool.map(one, candidates))
    return {"file": options.get("file"), "lines": shown, "models": values}


def _message(error):
    return str(error) if isinstance(error, ValueError) else type(error).__name__


def _spent(directory):
    """What a run that failed after sending paid for, which its result
    still shows."""
    from .process_view import paid_receipts

    try:
        paid = paid_receipts(directory)
    except OSError, ValueError:
        return {}
    cost = sum(float(item.get("cost") or 0) for item in paid.values())
    return {"cost": round(cost, 6)} if cost else {}
