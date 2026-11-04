"""Compare models: the same lines of one game file translated by up to four
models, or by one model with changed settings, to choose between them in
equal conditions.

A comparison is two operations (compatibility/compare). Its estimate prices
each model's requests offline, built as the game's own method builds them:
Guided's engine run of the file, or Assistant-led's and Manual's requests of
their units. The Translate button carries that price, and its click approves
it once: the translate operation starts only from a finished estimate whose
inputs are unchanged and that no translate used before. Results are the
operations' own records, as the whole-game estimate's are; the best line a
person picks in each row, and whether model names stay hidden, are kept
beside them here.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import NamedTuple

from dazedtl import system
from dazedtl.actions import label
from dazedtl.compatibility.compare import ESTIMATE, TRANSLATE, UNITS, WHOLE_GAME
from dazedtl.compatibility.compare_units import GUIDANCE
from dazedtl.projects.store import working_method
from dazedtl.settings import providers
from dazedtl.settings.execution import Choice, request_policy
from dazedtl.storage import read_versioned_json, write_json

from .files import digest, evidence, project_path, read_json

# Raise when the same choices would be estimated or translated differently,
# or the saved record changes shape.
VERSION = 1
# What fits side by side on a laptop screen.
MODELS = 4
KINDS = ("single", "versus", "tune")
# How many lines a comparison may hold, so its requests stay a few.
MAX_LINES = 200
# A test-only glossary or instruction, as the guidance editors take them.
TEXT_LIMIT = 200_000
# The comparisons a page lists.
HISTORY = 20
# Assistant-led and Manual runs freeze this mode for a Live request.
LIVE = "live"
UNORGANIZED = (
    "Compare uses the lines your assistant extracted. It's available once "
    "they are organized into requests."
)
UNLOADED = "Load your text file on Text first; Compare uses its lines."


class Game(NamedTuple):
    """A project as a comparison reads it: its method ("guided", "len" or
    "manual"), the owner its operations are filed under, its game folder,
    and its Guided record or its units file."""

    method: str
    project: str
    owner: str
    root: str
    native: dict | None = None
    units: str = ""


class Compare:
    def __init__(self, guided):
        self.guided = guided

    # Records

    def _path(self, project_id):
        return (
            self.guided.translation.workspace
            / "translation/projects"
            / project_id
            / "compare.json"
        )

    def _read(self, project_id):
        return read_versioned_json(
            self._path(project_id),
            {"version": VERSION, "used": {}, "marks": {}},
            {},
            _validate,
        )

    def _write(self, project_id, value):
        path = self._path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, value)

    # The game

    def game(self, project_id):
        """The project as a comparison reads it, refusing one it can't
        compare yet with why."""
        guided = self.guided
        project = guided.projects.get(project_id)
        method = working_method(project, False)
        if method == "guided" or project.get("backend_id") and method not in UNITS:
            _, native = guided.record(project_id)
            guided.require_preparation(project_id, native)
            if native.get("collection_error"):
                raise ValueError(native["collection_error"])
            return Game("guided", project_id, native["id"], native["source"], native)
        if method not in UNITS:
            raise ValueError("Choose how to translate this game first.")
        root = project["source"]
        if method == "manual":
            from .project import MANUAL_UNITS

            if not project_path(root, MANUAL_UNITS, exists=False).is_file():
                raise ValueError(UNLOADED)
            return Game(method, project_id, project_id, root, units=MANUAL_UNITS)
        return Game(
            method,
            project_id,
            project_id,
            root,
            units=self._organized(project_id, root),
        )

    def _organized(self, project_id, root):
        """The units file the game's newest Assistant-led run was organized
        from."""
        store = self.guided.translation.jobs.store
        for job in sorted(
            (
                item
                for item in store.list(project_id)
                if item.get("kind") == "translation"
            ),
            key=lambda item: item["created"],
            reverse=True,
        ):
            try:
                _job, plan = store.load(job["id"], project_id)
                organized = read_json(project_path(root, plan["input_path"]))
                return organized["inputs"][0]
            except OSError, ValueError, KeyError, TypeError, IndexError:
                continue
        raise ValueError(UNORGANIZED)

    def _units(self, game):
        from .organize import units_input

        return units_input(read_json(project_path(game.root, game.units)))

    # Choices

    @staticmethod
    def _candidates(kind, value):
        if kind not in KINDS:
            raise ValueError("Choose Single model, Model vs model or Tune settings.")
        if not isinstance(value, list) or not value:
            raise ValueError("Add a model to compare.")
        if kind in {"single", "tune"} and len(value) != 1:
            raise ValueError("Choose one model.")
        if kind == "versus" and not 2 <= len(value) <= MODELS:
            raise ValueError(f"Add two to {MODELS} models to compare.")
        rows = []
        for item in value:
            if not isinstance(item, dict) or set(item) - {
                "connection_id",
                "model",
                "effort",
                "glossary",
                "instruction",
            }:
                raise ValueError("Choose each model from a connection.")
            connection = item.get("connection_id")
            if not isinstance(connection, str) or not connection:
                raise ValueError("Choose each model's connection.")
            row: dict[str, object] = {
                "connection_id": connection,
                "model": _model(item.get("model")),
            }
            if kind == "tune":
                if "effort" in item:
                    from dazedtl.settings.effort import checked

                    row["effort"] = checked(item["effort"])
                for key in ("glossary", "instruction"):
                    text = item.get(key)
                    if text is None:
                        continue
                    if not isinstance(text, str) or len(text) > TEXT_LIMIT:
                        raise ValueError(
                            "Keep the test glossary and instruction shorter."
                        )
                    row[key] = text
            elif set(item) - {"connection_id", "model"}:
                raise ValueError("Only Tune settings changes a model's settings.")
            rows.append(row)
        keys = [(row["connection_id"], row["model"]) for row in rows]
        if kind == "versus" and len(set(keys)) != len(keys):
            raise ValueError("Each model is in the comparison once.")
        return rows

    def _phase(self, game, file, lines):
        """The Guided task a file belongs to, or the group a unit file's
        lines have, refusing what can't be compared."""
        if type(lines) is not int or not 0 <= lines <= MAX_LINES:
            raise ValueError(f"Compare up to {MAX_LINES} lines.")
        if game.native is None:
            if not any(unit["group"] == file for unit in self._units(game)):
                raise ValueError("Choose one of the game's groups of lines.")
            return ""
        phase = next(
            (
                phase
                for phase in ("database", "dialogue")
                if file in self.guided.full_estimate.files(game.native, phase)
            ),
            None,
        )
        if phase is None:
            raise ValueError("Choose a Database files or Maps & events file.")
        return phase

    def _row(self, game, state, candidate):
        """What a model's runs freeze, by the game's method, or why it
        can't run, such as having no price, which its column shows."""
        settings = self.guided.settings
        connection = settings._connection(state, candidate["connection_id"])
        if not settings._configured(connection):
            raise ValueError("That connection is no longer set up in Settings.")
        row = {
            "label": candidate["model"],
            "connection": connection["name"],
            "connection_id": connection["id"],
            "model": candidate["model"],
            **{
                key: candidate[key]
                for key in ("effort", "glossary", "instruction")
                if key in candidate
            },
        }
        choice = Choice(
            connection["id"],
            candidate["model"],
            {"thinkingEffort": candidate["effort"]} if "effort" in candidate else None,
        )
        try:
            if game.native is None:
                configuration, _route = self.guided.translation.api_configuration(
                    LIVE, game.root, choice=choice
                )
                return {**row, "configuration": configuration}
            policy = request_policy(settings, "translate", choice)
        except ValueError as error:
            return {**row, "error": str(error)}
        return {
            **row,
            "key_name": connection["runtime_name"],
            "values": {
                "model": candidate["model"],
                "API_PROVIDER": connection["protocol"],
                "api": providers.address(connection),
                "organization": connection["organization"],
                "batchsize": policy["entriesPerRequest"],
            },
            "policy": policy,
        }

    def _plan(self, game, kind, file, lines, candidates):
        """The operation plan that estimates the comparison, with the inputs
        its approval binds."""
        from dazedtl.settings import language_pair

        from . import comment_text

        guided = self.guided
        candidates = self._candidates(kind, candidates)
        phase = self._phase(game, file, lines)
        state = guided.settings._read()
        options = {
            "projectId": game.project,
            "method": game.method,
            "kind": kind,
            "file": file,
            "lines": lines,
            "pair": language_pair.pair(guided.settings, game.root),
            "claudeCount": guided.backend.manual.allow_providers,
            "candidates": [
                {"index": index, **self._row(game, state, candidate)}
                for index, candidate in enumerate(candidates)
            ],
        }
        if game.native is None:
            root = Path(game.root)
            _record, project = guided.translation.project(game.project)
            options.update(
                workspace=str(guided.translation.workspace),
                source=game.root,
                inputPath=game.units,
                selected={**project.read()["options"], "mode": LIVE},
                quotes=guided.settings.convert_quotes(),
            )
            guard = evidence(
                root,
                [
                    game.units,
                    *(relative for relative in GUIDANCE if (root / relative).is_file()),
                    *(
                        path.relative_to(root).as_posix()
                        for path in sorted((root / ".dazedtl/skills").glob("*.md"))
                    ),
                ],
            )
            folder = guided.translation.workspace / "translation/projects" / game.owner
        else:
            native = game.native
            inputs = guided.inputs(native)
            sources = inputs.sources([file], inputs.record()["inputs"])
            folder = guided.backend.workflows.folder(native["id"])
            options.update(
                phase=phase,
                relative=sources[file]["relative"],
                markers=sorted(comment_text.markers(native["source"]))
                if phase == "dialogue" and native["phase1_comments"]
                else [],
                workflow=guided.backend.workflows.phase_workflow(native["id"], phase),
            )
            guard = guided.backend.guided_guard(native, folder)
        options["inputs"] = digest(
            {
                "version": VERSION,
                "options": {
                    key: value
                    for key, value in options.items()
                    if key not in {"claudeCount", "inputs"}
                },
                "guard": guard,
            }
        )
        return {
            "project_id": game.owner,
            "project": deepcopy(game.native) if game.native else {"source": game.root},
            "folder": str(folder),
            "guard": guard,
            "options": options,
        }

    def _start(self, plan, action):
        return self.guided.backend.operations.start(
            {**plan, "action": action, "label": label(action)}
        )

    def _prepare(self, game):
        """Installs every connection's credential and the game's languages,
        which a Guided run reads as a Translate run does."""
        if game.native is not None:
            self.guided.settings.prepare_engine(pair=self.guided.runs.pair(game.native))

    def _jobs(self, game, action):
        return sorted(
            (
                job
                for job in self.guided.backend.operations.jobs.values()
                if job["project_id"] == game.owner and job["action"] == action
            ),
            key=lambda job: job["created"],
            reverse=True,
        )

    # Methods

    def estimate(self, project_id, kind, file, lines, candidates):
        """Starts pricing each model's requests for the lines, offline."""
        self.guided.idle(isolated_workers=True)
        game = self.game(project_id)
        self._prepare(game)
        return self._start(self._plan(game, kind, file, lines, candidates), ESTIMATE)

    def translate(self, project_id, estimate_id):
        """Sends the requests an estimate priced, once: the click on its
        price approves it."""
        guided = self.guided
        guided.idle(isolated_workers=True)
        game = self.game(project_id)
        job = guided.backend.operations.jobs.get(estimate_id)
        options = self._options(game, estimate_id, ESTIMATE)
        if job["status"] != "complete" or not isinstance(job.get("result"), dict):
            raise ValueError("Estimate the comparison before translating it.")
        record = self._read(project_id)
        if estimate_id in record["used"]:
            raise ValueError("These lines were already translated. Estimate again.")
        self._prepare(game)
        candidates = [
            {
                "connection_id": row["connection_id"],
                "model": row["model"],
                **{
                    key: row[key]
                    for key in ("effort", "glossary", "instruction")
                    if key in row
                },
            }
            for row in options["candidates"]
        ]
        plan = self._plan(
            game, options["kind"], options["file"], options["lines"], candidates
        )
        if plan["options"]["inputs"] != options["inputs"]:
            raise ValueError(
                "The game, its guidance or a model's settings changed. Estimate again."
            )
        priced = {
            row["index"]
            for row in job["result"].get("models", [])
            if isinstance(row.get("estimate"), dict)
        }
        if not priced:
            raise ValueError("No model could be estimated. Check its connection.")
        plan["options"]["candidates"] = [
            row for row in plan["options"]["candidates"] if row["index"] in priced
        ]
        plan["options"]["estimate"] = estimate_id
        # Saved before the operation starts, so a second click or a retry
        # can't send the same requests again.
        record["used"][estimate_id] = ""
        self._write(project_id, record)
        try:
            started = self._start(plan, TRANSLATE)
        except Exception:
            record["used"].pop(estimate_id, None)
            self._write(project_id, record)
            raise
        record["used"][estimate_id] = started["id"]
        self._write(project_id, record)
        return started

    def marks(self, project_id, comparison_id, marks, blind, revealed):
        """Keeps the line a person picked as best in each row, and whether
        the models' names stay hidden until every row has a pick."""
        self._options(self.game(project_id), comparison_id, TRANSLATE)
        if (
            not isinstance(marks, dict)
            or len(marks) > MAX_LINES * 2
            or any(
                not isinstance(key, str)
                or type(value) is not int
                or not 0 <= value < MODELS
                for key, value in marks.items()
            )
            or type(blind) is not bool
            or type(revealed) is not bool
        ):
            raise ValueError("Pick one model's line per row.")
        record = self._read(project_id)
        record["marks"][comparison_id] = {
            "marks": marks,
            "blind": blind,
            "revealed": revealed,
        }
        self._write(project_id, record)
        return {"saved": True}

    def scenes(self, game):
        """The files or groups a comparison may translate, with their map
        names and lines, as the game's own lists count them."""
        if game.native is None:
            counts = {}
            for unit in self._units(game):
                counts[unit["group"]] = counts.get(unit["group"], 0) + 1
            return [
                {"file": group, "title": "", "lines": count}
                for group, count in counts.items()
            ]
        from . import comment_text

        guided, native = self.guided, game.native
        phases = {
            name: phase
            for phase in ("database", "dialogue")
            for name in guided.full_estimate.files(native, phase)
        }
        counts = guided.inputs(native).line_counts(
            phases,
            comment_text.markers(native["source"])
            if native["phase1_comments"]
            else frozenset(),
            [],
        )
        titles = guided.backend.guided_titles(native)
        return [
            {
                "file": name,
                "title": titles.get(name) or "",
                "lines": counts[name]["lines"],
            }
            for name in sorted(phases, key=_order)
            if counts.get(name, {}).get("lines")
        ]

    def state(self, project_id):
        """The project's comparisons, newest first: each estimate with its
        translation once approved, the lines and each model's result."""
        try:
            game = self.game(project_id)
        except ValueError as error:
            return {
                "available": False,
                "reason": str(error),
                "scenes": [],
                "glossary": "",
                "comparisons": [],
                "wholeGame": [],
            }
        record = self._read(project_id)
        jobs = self.guided.backend.operations.jobs
        rows = []
        for job in self._jobs(game, ESTIMATE):
            options = _options(self.guided.backend.operations.root, job["id"])
            if options is None:
                continue
            translated = jobs.get(record["used"].get(job["id"]) or "")
            rows.append(
                view(
                    job,
                    options,
                    translated,
                    record["marks"].get(translated["id"] if translated else "", {}),
                )
            )
            if len(rows) == HISTORY:
                break
        return {
            "available": True,
            "reason": "",
            "scenes": self.scenes(game),
            "glossary": _glossary(game.root),
            "comparisons": rows,
            "wholeGame": self.wholes(game),
        }

    def model(self, connection_id, model):
        """The thinking efforts a model on a connection may be sent, and
        whether its price is known, from what Settings has looked up."""
        settings = self.guided.settings
        connection = settings._connection(settings._read(), connection_id)
        if connection is None:
            raise ValueError("That connection is no longer in Settings.")
        model = _model(model)
        defaults = settings.connection_defaults(connection, model, cached_only=True)
        options = connection["model_options"].get(model) or {}
        rates = (
            (options.get("inputRate"), options.get("outputRate"))
            if options.get("pricing") == "custom"
            else (defaults.get("inputRate"), defaults.get("outputRate"))
        )
        efforts = defaults.get("thinkingEffort") or settings._effort(connection, model)
        return {
            "efforts": efforts.get("options", []),
            "priced": all(rate not in (None, "") for rate in rates),
        }

    def use(self, project_id, comparison_id, model):
        """Makes a compared model the one the game translates with: Settings'
        connection and model, and, from Tune settings, the effort it was sent
        with, its glossary and its instruction, saved as the game's guidance."""
        guided = self.guided
        game = self.game(project_id)
        row = self._candidate(game, comparison_id, model)
        settings = guided.settings
        described = settings.describe()
        if described.get("draft"):
            raise ValueError(
                "Save or discard your Settings changes before switching models."
            )
        if described["activeConnectionId"] != row["connection_id"]:
            described = settings.select(described["revision"], row["connection_id"])
        model_options = deepcopy(described["modelOptions"])
        if "effort" in row:
            from dazedtl.settings.preferences import DEFAULT_OPTIONS

            model_options[row["model"]] = {
                **deepcopy(model_options.get(row["model"]) or DEFAULT_OPTIONS),
                "thinkingEffort": row["effort"],
            }
        settings.save(
            described["revision"],
            row["connection_id"],
            {**described["values"], "model": row["model"]},
            model_options,
        )
        changes = {}
        if row.get("glossary") is not None:
            changes["glossary"] = lambda _text: row["glossary"]
        if (row.get("instruction") or "").strip():
            changes["game"] = lambda text: (
                (text.rstrip() + "\n\n" if text.strip() else "")
                + row["instruction"].strip()
                + "\n"
            )
        if changes and game.native is not None:
            current = guided.backend.workflows.editable(game.native["id"])
            guided.save_documents(
                project_id,
                {
                    name: {"text": change((current.get(name) or {}).get("text") or "")}
                    for name, change in changes.items()
                },
            )
        elif changes:
            service = guided.translation
            current = service.documents(project_id)
            for name, change in changes.items():
                document = current.get(name) or {}
                service.save_document(
                    project_id,
                    name,
                    document.get("revision", ""),
                    change(document.get("text") or ""),
                )
        return {"saved": True}

    def whole_game(self, project_id, comparison_id, model):
        """Starts the game's cost estimate for a compared model: Context's
        Cost estimate of every Translate task for a Guided game, every unit
        left to translate for an Assistant-led or Manual one."""
        guided = self.guided
        guided.idle(isolated_workers=True)
        game = self.game(project_id)
        row = self._candidate(game, comparison_id, model)
        choice = {
            "connection_id": row["connection_id"],
            "model": row["model"],
            **({"effort": row["effort"]} if "effort" in row else {}),
        }
        self._prepare(game)
        if game.native is None:
            plan = self._plan(game, "single", None, 0, [choice])
            if "error" in plan["options"]["candidates"][0]:
                raise ValueError(plan["options"]["candidates"][0]["error"])
            plan["options"]["choice"] = choice
            return self._start(plan, WHOLE_GAME)
        from .full_estimate import PHASES

        native = game.native
        event_text = guided.event_text.status(project_id, native)
        if event_text["enabled"] and event_text["errors"]:
            raise ValueError(
                "Fix the event text source choices first: "
                + " ".join(event_text["errors"])
            )
        engine = self._row(game, guided.settings._read(), choice)
        if "error" in engine:
            raise ValueError(engine["error"])
        full = guided.full_estimate
        tasks = [
            {
                "phase": phase,
                "files": []
                if phase == "advanced" and not event_text["enabled"]
                else full.files(native, phase),
            }
            for phase in PHASES
        ]
        names = [name for task in tasks for name in task["files"]]
        inputs = guided.inputs(native)
        sources = inputs.sources(names, inputs.record()["inputs"])
        folder = guided.backend.workflows.folder(native["id"])
        return self._start(
            {
                "project_id": native["id"],
                "project": deepcopy(native),
                "folder": str(folder),
                "guard": guided.backend.guided_guard(native, folder),
                "options": {
                    # Read by its own page only, never as the game's estimate.
                    "fingerprint": "",
                    "shape": "",
                    "configuration": {},
                    "model": row["model"],
                    "batchSupported": False,
                    "policy": engine["policy"],
                    "engine": {
                        "values": engine["values"],
                        "key_name": engine["key_name"],
                    },
                    "choice": choice,
                    "claudeCount": guided.backend.manual.allow_providers,
                    "files": {name: sources[name]["relative"] for name in names},
                    "tasks": [
                        {
                            **task,
                            "noSources": task["phase"] == "advanced"
                            and not task["files"],
                            "workflow": guided.backend.workflows.phase_workflow(
                                native["id"], task["phase"]
                            ),
                        }
                        for task in tasks
                    ],
                },
            },
            WHOLE_GAME,
        )

    def _options(self, game, identity, action):
        """The options a comparison operation of the game froze."""
        job = self.guided.backend.operations.jobs.get(identity)
        options = (
            _options(self.guided.backend.operations.root, identity)
            if job and job["action"] == action and job["project_id"] == game.owner
            else None
        )
        if options is None:
            raise ValueError("This comparison is no longer available.")
        return options

    def _candidate(self, game, comparison_id, model):
        """A comparison's model, as its estimate froze it."""
        row = next(
            (
                item
                for item in self._options(game, comparison_id, ESTIMATE)["candidates"]
                if item["index"] == model
            ),
            None,
        )
        if row is None:
            raise ValueError("This comparison is no longer available.")
        return row

    def wholes(self, game):
        """The whole-game estimates started for compared models, newest
        first."""
        rows = []
        for job in self._jobs(game, WHOLE_GAME)[:HISTORY]:
            options = _options(self.guided.backend.operations.root, job["id"])
            if options is None:
                continue
            choice = options["choice"]
            result = job.get("result") if job["status"] == "complete" else None
            tasks = [task for task in (result or {}).get("tasks", []) if task["files"]]
            batch = [task.get("batchCost") for task in tasks]
            rows.append(
                {
                    "connectionId": choice["connection_id"],
                    "model": choice["model"],
                    **({"effort": choice["effort"]} if "effort" in choice else {}),
                    "jobId": job["id"],
                    "status": job["status"],
                    "message": job.get("message", ""),
                    **(
                        {
                            "cost": round(
                                sum(float(task.get("liveCost") or 0) for task in tasks),
                                6,
                            ),
                            # Batch only where every task's route runs one.
                            "batchCost": round(sum(batch), 6)
                            if batch and all(cost for cost in batch)
                            else None,
                        }
                        if result
                        else {}
                    ),
                }
            )
        return rows

    def request(self, project_id, comparison_id, model, index):
        """One request a model's translation sent, as Show request shows it."""
        game = self.game(project_id)
        self._options(game, comparison_id, TRANSLATE)
        job = self.guided.backend.operations.jobs[comparison_id]
        found = next(
            (
                row
                for row in (job.get("result") or {}).get("models", [])
                if row.get("index") == model
            ),
            None,
        )
        requests = (found or {}).get("requests") or []
        if type(index) is not int or not 0 <= index < len(requests):
            raise ValueError("This request is no longer available.")
        return requests[index]


def _model(value):
    from dazedtl.settings.preferences import text

    return text(value, "model ID", required=True)


def _order(name):
    """Database files first, then maps in their number's order."""
    import re

    found = re.fullmatch(r"Map(\d+)\.json", name)
    return (1, int(found[1]), name) if found else (0, 0, name)


def _glossary(source):
    from util.paths import GAME_GLOSSARY_RELATIVE

    from dazedtl.compatibility.compare_units import editable

    path = project_path(source, GAME_GLOSSARY_RELATIVE.as_posix(), exists=False)
    try:
        return editable(system.read_bytes(path).decode("utf-8-sig"))
    except OSError:
        return ""


def _validate(value):
    if (
        not isinstance(value, dict)
        or value.get("version") != VERSION
        or not isinstance(value.get("used"), dict)
        or not isinstance(value.get("marks"), dict)
    ):
        raise ValueError("The saved comparisons can't be read.")
    return value


def _options(root, identity):
    try:
        return json.loads(system.read_bytes(root / identity / "plan.json"))["options"]
    except OSError, ValueError, KeyError, TypeError:
        return None


def view(estimate, options, translated, marks):
    """How a comparison reads on the page."""
    models = {
        row["index"]: row for row in (estimate.get("result") or {}).get("models", [])
    }
    results = {
        row["index"]: row
        for row in ((translated or {}).get("result") or {}).get("models", [])
    }
    candidates = []
    for row in options["candidates"]:
        priced = models.get(row["index"], {})
        done = results.get(row["index"], {})
        error = done.get("error") or priced.get("error") or row.get("error")
        candidates.append(
            {
                "index": row["index"],
                "connection": row["connection"],
                "connectionId": row["connection_id"],
                "model": row["model"],
                **({"effort": row["effort"]} if "effort" in row else {}),
                **({"glossary": row["glossary"]} if "glossary" in row else {}),
                **({"instruction": row["instruction"]} if "instruction" in row else {}),
                **(
                    {"estimate": _price(priced["estimate"])}
                    if isinstance(priced.get("estimate"), dict)
                    else {}
                ),
                **({"error": error} if error else {}),
                **(
                    {
                        "cost": done.get("cost", 0),
                        "seconds": done.get("seconds", 0),
                        "requests": done.get("requestCount", 0),
                    }
                    if done and not done.get("error")
                    else {}
                ),
            }
        )
    # A translation running has no result yet; its estimate read the lines.
    source = (translated or {}).get("result") or estimate.get("result") or {}
    lines = []
    for line in source.get("lines", []):
        lines.append(
            {
                **line,
                "translations": [
                    (results.get(row["index"], {}).get("lines") or {}).get(line["id"])
                    for row in options["candidates"]
                ],
                "problems": [
                    (results.get(row["index"], {}).get("problems") or {}).get(
                        line["id"], []
                    )
                    for row in options["candidates"]
                ],
            }
        )
    return {
        "id": estimate["id"],
        "translationId": translated["id"] if translated else None,
        "kind": options["kind"],
        "file": options["file"],
        "lines": options["lines"],
        "created": estimate["created"],
        "stage": "translation" if translated else "estimate",
        "status": translated["status"] if translated else estimate["status"],
        "message": (translated or estimate).get("message", ""),
        "candidates": candidates,
        "rows": lines,
        "marks": marks.get("marks", {}),
        "blind": marks.get("blind", False),
        "revealed": marks.get("revealed", False),
    }


def _price(estimate):
    """A model's estimate as its Translate button prices it: Live."""
    return {
        "cost": float(estimate.get("live_cost") or 0),
        "requests": int(estimate.get("requests") or 0),
    }
