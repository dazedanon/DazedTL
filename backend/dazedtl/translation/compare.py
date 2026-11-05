"""Compare models: the same lines of one game file translated by up to four
models, or by one model with changed settings, to choose between them in
equal conditions.

A comparison is two operations (compatibility/compare). Its estimate prices
each model's requests offline, built as the game's own method builds them:
Guided's engine run of the file, or Assistant-led's and Manual's requests of
their units. The Translate button carries that price, and its click approves
it once: the translate operation starts only from a finished estimate whose
inputs are unchanged and that no translate used before. Results are the
operations' own records; the best line a person picks in each row, and
whether model names stay hidden, are kept beside them here.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import NamedTuple

from util.guidance_documents import GAME_CONTEXT, GLOSSARY

from dazedtl import system
from dazedtl.actions import label
from dazedtl.compatibility.compare import ACTIONS, ESTIMATE, TRANSLATE, UNITS
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
# What a Tune test changes in a model's settings.
TUNED = ("effort", "glossary", "glossary_revision", "instruction")
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
                *TUNED,
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
                if "glossary" in row:
                    revision = item.get("glossary_revision")
                    if not isinstance(revision, str):
                        raise ValueError("Edit the test glossary again.")
                    row["glossary_revision"] = revision
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
            **{key: candidate[key] for key in TUNED if key in candidate},
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
            # Where the game's records are, such as the original it stages.
            "workspace": str(guided.translation.workspace),
            "candidates": [
                {"index": index, **self._row(game, state, candidate)}
                for index, candidate in enumerate(candidates)
            ],
        }
        if kind == "tune":
            # What Use these settings may save over, as the test read it.
            documents = _guidance(game.root)
            edited = candidates[0].get("glossary_revision")
            if edited is not None and edited != documents[GLOSSARY.key]["revision"]:
                raise ValueError(
                    "The game's glossary changed in Context since you edited "
                    "this test's glossary. Edit it again from the game's."
                )
            options["revisions"] = {
                name: documents[name]["revision"]
                for name in (GLOSSARY.key, GAME_CONTEXT.key)
            }
        if game.native is None:
            root = Path(game.root)
            _record, project = guided.translation.project(game.project)
            options.update(
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

    def operations(self, project_id):
        """The project's comparison operations, newest first, whichever
        method filed them: under its Guided record or itself (Game.owner)."""
        owners = {project_id, self.guided.projects.get(project_id).get("backend_id")}
        return sorted(
            (
                job
                for job in self.guided.backend.operations.jobs.values()
                if job["project_id"] in owners and job["action"] in ACTIONS
            ),
            key=lambda job: job["created"],
            reverse=True,
        )

    def stop(self, project_id, operation_id):
        """Stops the project's running comparison operation, in any method;
        a translation keeps what its models finished."""
        if not any(job["id"] == operation_id for job in self.operations(project_id)):
            raise ValueError("This comparison is no longer running.")
        return self.guided.backend.operations.stop(operation_id)

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
                **{key: row[key] for key in TUNED if key in row},
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
        options = self._options(self.game(project_id), comparison_id, TRANSLATE)
        jobs = self.guided.backend.operations.jobs
        rows = {
            line["id"]
            for line in _lines(jobs.get(options["estimate"]) or {}, jobs[comparison_id])
        }
        models = {row["index"] for row in options["candidates"]}
        # A row of this comparison each, picking one of its models.
        if (
            not isinstance(marks, dict)
            or any(
                key not in rows or type(value) is not int or value not in models
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
                "glossaryRevision": "",
                "comparisons": [],
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
        glossary = _guidance(game.root)[GLOSSARY.key]
        return {
            "available": True,
            "reason": "",
            "scenes": self.scenes(game),
            "glossary": glossary["text"],
            "glossaryRevision": glossary["revision"],
            "comparisons": rows,
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
        with, its glossary and its instruction, saved as the game's guidance.
        Everything is checked before anything is written."""
        guided = self.guided
        # As Settings' own saves, never under a running translation.
        guided.idle()
        game = self.game(project_id)
        row = self._candidate(game, comparison_id, model)
        jobs = guided.backend.operations.jobs
        translated = jobs.get(self._read(project_id)["used"].get(comparison_id) or "")
        if not _finished(translated, _result(translated, model)):
            raise ValueError(
                "Only a model that translated every line can be used. "
                "Translate the lines again."
            )
        changes = self._guidance_changes(
            game, row, self._options(game, comparison_id, ESTIMATE)
        )
        settings = guided.settings
        switch = (
            settings.describe()["revision"],
            row["connection_id"],
            row["model"],
            {"thinkingEffort": row["effort"]} if "effort" in row else None,
        )
        settings.use_model(*switch, check=True)
        if changes and game.native is not None:
            guided.save_guidance(game.native, changes)
        elif changes:
            guided.translation.engine.documents_save(game.root, changes)
        settings.use_model(*switch)
        return {"saved": True}

    @staticmethod
    def _guidance_changes(game, row, options):
        """The guidance documents a Tune test's settings change, as
        documents_save takes them, at the revisions its estimate froze; a
        document edited since refuses, as the test didn't read it."""
        from desktop.backend.guidance import holds

        wanted = {}
        if row.get("glossary") is not None:
            wanted[GLOSSARY.key] = lambda _text: row["glossary"]
        instruction = (row.get("instruction") or "").strip()
        if instruction:
            # Added once: a game context already holding it stays as it is.
            wanted[GAME_CONTEXT.key] = lambda text: (
                text
                if instruction in text
                else (
                    (text.rstrip() + "\n\n" if text.strip() else "")
                    + instruction
                    + "\n"
                )
            )
        if not wanted:
            return {}
        current = _guidance(game.root)
        frozen = options.get("revisions") or {}
        changes = {}
        for name, change in wanted.items():
            document = current[name]
            if document["state"] == "unreadable":
                raise ValueError(document["reason"])
            text = change(document["text"])
            if holds(name, document, text):
                continue
            if document["revision"] != frozen.get(name):
                raise ValueError(
                    f"The {document['title']} changed since this test. "
                    "Run the test again."
                )
            changes[name] = {"revision": document["revision"], "text": text}
        return changes

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

    def request(self, project_id, comparison_id, model, index):
        """One request a model's translation sent, as Show request shows it."""
        game = self.game(project_id)
        self._options(game, comparison_id, TRANSLATE)
        job = self.guided.backend.operations.jobs[comparison_id]
        requests = _result(job, model).get("requests") or []
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


def _guidance(root):
    """The game's guidance documents, as the Context editor reads them."""
    from desktop.backend.guidance import read

    return read(root)


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
    candidates = []
    for row in options["candidates"]:
        priced = models.get(row["index"], {})
        done = _result(translated, row["index"])
        # As written: Blind hides it with the names (compareView).
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
                **({"finished": True} if _finished(translated, done) else {}),
                # What it spent shows even when it failed or was stopped.
                **({"cost": done["cost"]} if "cost" in done else {}),
                **({"seconds": done["seconds"]} if "seconds" in done else {}),
                **(
                    {"requests": done["requestCount"]} if "requestCount" in done else {}
                ),
                # Show request pages only these: a result keeps the first
                # KEPT_REQUESTS (compatibility/compare).
                **(
                    {"keptRequests": len(done["requests"])}
                    if isinstance(done.get("requests"), list)
                    else {}
                ),
            }
        )
    lines = []
    for line in _lines(estimate, translated):
        lines.append(
            {
                **line,
                "translations": [
                    (_result(translated, row["index"]).get("lines") or {}).get(
                        line["id"]
                    )
                    for row in options["candidates"]
                ],
                "problems": [
                    (_result(translated, row["index"]).get("problems") or {}).get(
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


def _result(translated, index):
    """What a comparison's translation brought back for one of its models."""
    return next(
        (
            row
            for row in ((translated or {}).get("result") or {}).get("models", [])
            if row.get("index") == index
        ),
        {},
    )


def _finished(translated, result):
    """Whether a model translated a comparison's lines whole, so it can be
    used: its translation ended and it came back without an error. A model
    that failed or was stopped keeps its cost and finished lines, but not
    this."""
    return (
        bool(translated)
        and translated["status"] != "running"
        and "cost" in result
        and not result.get("error")
    )


def _lines(estimate, translated):
    """The lines a comparison shows: its translation's, or, while it runs
    and has no result yet, those its estimate read."""
    source = (translated or {}).get("result") or estimate.get("result") or {}
    return source.get("lines", [])


def _price(estimate):
    """A model's estimate as its Translate button prices it: Live."""
    return {
        "cost": float(estimate.get("live_cost") or 0),
        "requests": int(estimate.get("requests") or 0),
    }
