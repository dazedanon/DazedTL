"""Text QA steps the assistant runs through the project helper, and the
Text QA task in the app.

The engine reviews and makes findings; the app applies them as a reviewed
text batch through the Guided publication flow, which History can restore
and which, as every write to the game does, is its own checkpoint. Open
questions wait for the user's choice, and an applied correction can be
undone, and applied again, one at a time.
No step writes game files itself, and pushing or publishing stays the user's.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from dazedtl import system
from dazedtl.storage import write_json

from .files import read_json
from .project import WORK

if TYPE_CHECKING:
    from .guided import Guided

# `checkpoint` does nothing, now that each apply is its own checkpoint; an
# assistant started before then still runs it.
STEPS = (
    "status",
    "report",
    "prepare",
    "apply",
    "checkpoint",
    "undo",
    "reapply",
    "choose",
)
# What an Assistant-led assistant does about labels QA can't correct. A
# capture taken again keeps the review only until the corrections change the
# game's text, so it comes before qa --apply.
LABELS_STEP = (
    "labels lists text the game squeezes or cuts off on QA's captures of its "
    "screens that QA holds no line of, such as a plugin's menu command. Before "
    "qa --apply, shorten each where its plugin file, js/plugins.js or a file in "
    "js/plugins, holds it, keeping its meaning; save a checkpoint with that file "
    "in the runtime manifest, then run qa --prepare, which keeps QA's review and "
    "captures the screens again. Keep a label only when no shorter English keeps "
    "its meaning or no plugin file holds it, and note why in status.md."
)
# Where an Assistant-led assistant finds the never-translated text it
# translates (untranslated), and what it does about it. Guided's user
# translates what Text QA's report lists through Event text or Plugin files.
UNTRANSLATED_FILE = WORK + "/work/qa-untranslated.json"
UNTRANSLATED_STEP = (
    "untranslated counts text players can reach that the census counts and "
    "the game still holds untranslated, so QA could not review it; "
    f"{UNTRANSLATED_FILE} lists each by file and JSON pointer, which in "
    "js/plugins.js starts with the plugin's name and reads its settings as "
    "the JSON they hold. Before qa "
    "--apply or reporting the qa phase, translate it through your extraction "
    "and injection steps: extract it as units, organize, translate, and write "
    "it into the game with each file in the runtime manifest. If you played "
    "the game, run playtest --run --wait 20 again, so QA takes the new "
    "report's findings; then run qa --prepare, which reads the game again. "
    "Text the census sets aside and lines you declined are not counted."
)


def untranslated(
    sources: list[dict[str, Any]],
    counted: dict[tuple[str, str], set[str]],
    declined: Callable[[], list[str]],
    data: str,
    language: str,
) -> list[dict[str, str]]:
    """The never-translated texts of a QA task's preflight *sources*
    (rpgmaker_qa_preflight.read_sources) an Assistant-led assistant
    translates: those players may see that hold a run the census counts in
    their file and are no part of a line the assistant declined, by their
    path in the game, whose data folder is *data*.

    *counted* is the census's runs no rule sets aside (census.in_scope), and
    *declined* gives the source text of the lines the assistant declined,
    read only once a text counts. A census file
    is the source's own: the plugin list for a plugin's settings, and the
    data file of the same name for the rest, whatever its format, as a VX
    Ace game's census reads Data's rvdata2 files that QA reads as JSON.
    Everything else stays reported only, so translating these always ends
    the step."""
    from util.rpgmaker_qa_preflight import TEXT_LIMIT, may_show

    from .census import runs

    plugins: set[str] = set()
    files: dict[str, set[str]] = {}
    for (kind, file), found in counted.items():
        path = PurePosixPath(file)
        if kind.endswith(":plugins"):
            plugins |= found
        elif path.parent.name.casefold() == "data":
            files.setdefault(path.stem.casefold(), set()).update(found)
    folder = PurePosixPath(data)
    result = []
    lines = None
    for source in sources:
        if not may_show(source):
            continue
        plugin = source["kind"] == "plugin"
        scope = (
            plugins
            if plugin
            else files.get(PurePosixPath(source["file"]).stem.casefold(), set())
        )
        if not scope:
            continue
        for text in source["texts"]:
            value = text["text"]
            found = runs(value, language)
            # Preflight cuts a long text short, and its last run with it.
            cut = len(value) > TEXT_LIMIT and value.endswith("…")
            if not any(
                run in scope
                or cut
                and index == len(found) - 1
                and any(whole.startswith(run) for whole in scope)
                for index, run in enumerate(found)
            ):
                continue
            if lines is None:
                lines = declined()
            part = value.removesuffix("…") if cut else value
            if not any(part in line for line in lines):
                result.append(
                    {
                        "file": (
                            folder.parent / "js/plugins.js"
                            if plugin
                            else folder / source["file"]
                        ).as_posix(),
                        "pointer": text["pointer"],
                        "kind": text["kind"],
                        "text": value,
                    }
                )
    return result


def _unreadable_step(qa) -> str:
    """What the assistant does about a prepared task the app can't read."""
    problem = qa["unreadable"]
    return (
        f"DazedTL can't use the QA task {problem['path']}: {problem['error']}. "
        "If its files lost DazedTL's access, such as files saved from an elevated "
        "shell, restore that access and run qa again; otherwise run qa --prepare, "
        "which sets the task aside and prepares a fresh one."
    )


class TextQA:
    def __init__(self, guided: Guided):
        self.guided = guided
        # Each Guided game's latest QA task, by the pointer file naming it.
        self.pointed: dict[str, tuple[Any, Path]] = {}
        # Each task's latest capture labels, by the capture they come from.
        self.outside: dict[Path, tuple[Any, tuple[int, list[dict[str, Any]]]]] = {}
        # The last Assistant-led project's never-translated sources and
        # census scope, by the files they are read from.
        self.reported: tuple[Any, Any] | None = None

    def untranslated_texts(self, project_id, native, task) -> list[dict[str, str]]:
        """The never-translated text of an Assistant-led project's current QA
        *task* that its assistant translates (untranslated), saved where
        UNTRANSLATED_STEP names it, and none without a current task. The
        task's report and the census are read again only when they or the
        scope rules change."""
        from util.rpgmaker_qa_preflight import read_sources

        from .census import counted_language, in_scope
        from .operations import census_path
        from .run_compiler import SCOPE_RULES, scope_rules

        translation = self.guided.translation
        root = translation.project(project_id)[1].root
        listed = root / UNTRANSLATED_FILE
        if not task:
            # Its pointers may name other lines once the game changed.
            system.unlink(listed, missing_ok=True)
            return []
        inputs = (
            Path(task) / "preflight.json",
            census_path(translation.workspace, project_id),
            root / SCOPE_RULES,
        )
        key = (project_id,) + tuple(
            (stat.st_mtime_ns, stat.st_size)
            if path.is_file() and (stat := path.stat())
            else None
            for path in inputs
        )
        saved = self.reported
        if not saved or saved[0] != key:
            read = None
            # Without a census, nothing says what the assistant translates.
            if key[1] and key[2]:
                census = read_json(inputs[1])
                try:
                    rules = scope_rules(root, census)
                except ValueError:
                    # Organize refuses these rules, so none set text aside.
                    rules = []
                read = (
                    read_sources(read_json(inputs[0])),
                    in_scope(census, rules),
                    counted_language(census),
                )
            saved = self.reported = (key, read)
        found = []
        data = Path(native["data"]).resolve()
        if saved[1] and data.is_relative_to(root):
            sources, counted, language = saved[1]
            found = untranslated(
                sources,
                counted,
                lambda: translation.jobs.store.declined_sources(project_id),
                data.relative_to(root).as_posix(),
                language,
            )
        value = {"task": Path(task).name, "texts": found}
        if not found:
            system.unlink(listed, missing_ok=True)
        elif not listed.is_file() or read_json(listed) != value:
            listed.parent.mkdir(parents=True, exist_ok=True)
            write_json(listed, value)
        return found

    def plugin_labels(self, project_id):
        """Labels the latest QA task of a Guided game, whatever its focus,
        found squeezed or cut off on a captured screen that QA holds no line
        of, such as a plugin's menu command, for Plugin files to shorten.
        Read on every observation, so the task's files are read again only
        when they change."""
        from dazedtl.compatibility.text import qa_pointed_task, qa_pointers

        none: dict[str, Any] = {"task": "", "labels": []}
        project = self.guided.projects.get(project_id)
        native = self.guided.backend.workflows.projects.get(project.get("backend_id"))
        if project.get("method") != "guided" or not native:
            return none
        folder = self.folder(native)
        try:
            signed = [
                (stat.st_mtime_ns, stat.st_size, path)
                for path in qa_pointers(folder)
                if path.is_file() and (stat := path.stat())
            ]
            if not signed:
                return none
            pointer = max(signed)
            saved = self.pointed.get(project_id)
            if saved and saved[0] == pointer:
                task = saved[1]
            else:
                task = qa_pointed_task(folder, pointer[2])
                self.pointed[project_id] = (pointer, task)
            number, labels = self.labels(task)
            return {
                # A capture taken again is another capture, whose labels
                # Plugin files hands out again.
                "task": task.name if number == 1 else f"{task.name}/{number}",
                "labels": labels,
            }
        except OSError, ValueError, KeyError, TypeError:
            return none

    def labels(self, task: Path) -> tuple[int, list[dict[str, Any]]]:
        """The round of a prepared task's latest capture and the labels it
        found squeezed or cut off that QA holds no line of, each with its
        screen, capture and how short of room it is; the task's files are
        read again only when that capture changes."""
        from dazedtl.compatibility.text import qa_capture, qa_outside

        captured = qa_capture(task)
        stat = (
            captured["listing"].stat()
            if captured and captured["listing"].is_file()
            else None
        )
        key = (
            captured and captured["round"],
            stat and (stat.st_mtime_ns, stat.st_size),
        )
        saved = self.outside.get(task)
        if not saved or saved[0] != key:
            saved = (
                key,
                (
                    captured["round"] if captured else 1,
                    [
                        {
                            field: row[field]
                            for field in (
                                "text",
                                "title",
                                "capture",
                                "squeezed",
                                "clipped",
                            )
                            if field in row
                        }
                        for row in qa_outside(task)
                    ],
                ),
            )
            self.outside[task] = saved
        return saved[1]

    def run(
        self,
        project_id,
        step,
        findings=None,
        question="",
        choice="",
        since="",
        everything=False,
    ):
        if step not in STEPS:
            raise ValueError("Choose a text QA step: " + ", ".join(STEPS) + ".")
        native = self.native(project_id)
        if step == "prepare":
            self.prepare(project_id, since, everything)
        elif step == "apply":
            self.apply(project_id, native)
        elif step in {"undo", "reapply"}:
            self.batch(project_id, native, findings, step)
        elif step == "choose":
            self.choose(project_id, native, question, choice)
        return self.status(project_id, native, report=step == "report")

    def native(self, project_id):
        """The game's QA workspace; an Assistant-led game gets the one Guided
        would use, which holds its QA tasks and text batches."""
        project = self.guided.projects.get(project_id)
        if not project.get("backend_id"):
            engine = self.guided.backend.describe(project["source"])["engine"]
            if engine not in {"MVMZ", "ACE"}:
                raise ValueError(
                    "Text QA reads RPG Maker MV/MZ and VX Ace data; check this engine "
                    "with Len's runtime QA instead."
                )
            self.guided.open(project_id)
        return self.guided.record(project_id)[1]

    def folder(self, native) -> Path:
        return Path(self.guided.backend.workflows.folder(native["id"]))

    def focus(self, project_id):
        return self.guided.saved_form(project_id)["text"]["focus"]

    def qa(self, project_id, native):
        return self.guided.backend.guided_text_state(native, self.focus(project_id))[
            "qa"
        ]

    def prepare(self, project_id, since="", everything=False):
        """Prepare or resume the task; *since* names a version or revision
        whose text was checked before, which QA then reads only as context,
        and *everything* reviews all text again."""
        preview = self.guided.preview(
            project_id,
            "qa_prepare",
            None,
            {
                "focus": self.focus(project_id),
                **({"since": since} if since else {}),
                **({"everything": True} if everything else {}),
            },
        )
        self.started(
            project_id, "prepare", self.guided.execute(project_id, preview["token"])
        )

    def apply(self, project_id, native):
        """Every finding, and each proposal the user chose, as one reviewed
        text batch, once no question waits for the user. After an earlier
        apply, only what QA made since, such as a follow-up round's findings;
        undone corrections wait for Apply again."""
        qa = self.qa(project_id, native)
        if qa.get("unreadable"):
            raise ValueError(_unreadable_step(qa))
        if not qa.get("task") or qa["status"].get("stage") != "complete":
            raise ValueError("Finish QA review first; apply follows a complete task.")
        if not qa["current"]:
            raise ValueError(qa["message"])
        if qa["applied"]:
            raise ValueError("This task's findings are already applied.")
        waiting = [row for row in qa["questions"] if "choice" not in row]
        if waiting:
            raise ValueError(
                f"{len(waiting)} question(s) wait for the user's choice in DazedTL's "
                "Text QA task; apply follows their answers."
            )
        chosen = [row["id"] for row in qa["findings"] if not row.get("state")]
        proposals = [
            row["id"]
            for row in qa["questions"]
            if row["choice"] == "use" and not row.get("state")
        ]
        if not chosen + proposals:
            raise ValueError("QA found nothing to correct.")
        preview = self.guided.preview(
            project_id,
            "qa_apply",
            None,
            {
                "focus": self.focus(project_id),
                "task": qa["task"],
                "findings": chosen,
                "proposals": proposals,
            },
        )
        self.started(
            project_id, "apply", self.guided.execute(project_id, preview["token"])
        )

    def batch(self, project_id, native, findings, kind):
        """Puts back the lines of applied corrections, or applies undone ones
        again, as a batch of its own."""
        qa = self.qa(project_id, native)
        if qa.get("unreadable"):
            raise ValueError(_unreadable_step(qa))
        if not qa.get("task"):
            raise ValueError("No QA task is prepared; run qa --prepare.")
        if not any(row.get("state") for row in qa["findings"] + qa["questions"]):
            raise ValueError(
                "QA has applied no corrections yet; run qa --apply once review is complete."
            )
        if (
            not isinstance(findings, list)
            or not findings
            or any(not isinstance(value, str) for value in findings)
        ):
            raise ValueError(
                "Choose the corrections to "
                + ("undo." if kind == "undo" else "apply again.")
            )
        questions = {row["id"] for row in qa["questions"]}
        preview = self.guided.preview(
            project_id,
            "qa_undo" if kind == "undo" else "qa_apply",
            None,
            {
                "focus": self.focus(project_id),
                "task": qa["task"],
                "findings": [value for value in findings if value not in questions],
                "proposals": [value for value in findings if value in questions],
            },
        )
        self.started(
            project_id, kind, self.guided.execute(project_id, preview["token"])
        )

    def choose(self, project_id, native, question, choice):
        """The user's answer to an open question: keep the line, or use the
        proposal the reviewer gave."""
        from util import rpgmaker_qa

        qa = self.qa(project_id, native)
        row = next((row for row in qa["questions"] if row["id"] == question), None)
        if row is None:
            raise ValueError("That question is no longer open.")
        # A follow-up round after an apply asks again until its answers apply.
        if qa["applied"] or row.get("state") == "applied":
            raise ValueError("This task's findings are already applied.")
        rpgmaker_qa.answer(qa["task"], question, choice)

    def report(self, project_id):
        from dazedtl.compatibility.text import qa_report

        native = self.native(project_id)
        return qa_report(
            {
                "project_id": native["id"],
                "project": native,
                "folder": str(self.folder(native)),
                "guard": self.guided.backend.guided_guard(native, self.folder(native)),
                "options": {"focus": self.focus(project_id)},
            }
        )

    def started(self, project_id, kind, job):
        write_json(
            self.guided.path(project_id, "text-qa-operation"),
            {"kind": kind, "id": job["id"], "runner": "native"},
        )

    def operation(self, project_id) -> dict[str, Any] | None:
        """The last QA step the helper started, with its current state."""
        path = self.guided.path(project_id, "text-qa-operation")
        if not path.exists():
            return None
        saved = read_json(path)
        if saved["runner"] == "native":
            operations = self.guided.backend.operations
            job = operations.jobs.get(saved["id"]) or {}
            state, message = job.get("status", "interrupted"), job.get("message", "")
            # A job reports its end before its worker exits, and the next
            # step waits for the worker.
            if operations.active == saved["id"]:
                state = "running"
        else:
            # A checkpoint run before each apply was its own checkpoint.
            job = self.guided.translation.run(project_id, saved["id"])
            state, message = job["status"], job.get("message", "")
        return {
            "kind": saved["kind"],
            "id": saved["id"],
            "status": state,
            "message": str(message or ""),
        }

    def status(self, project_id, native, report=False):
        from dazedtl.compatibility.text import qa_capture_outdated

        qa = self.qa(project_id, native)
        stage = str(qa["status"].get("stage") or "")
        waiting = [row for row in qa["questions"] if "choice" not in row]
        # What apply would put in, as apply chooses it.
        unapplied = [row for row in qa["findings"] if not row.get("state")] + [
            row
            for row in qa["questions"]
            if row.get("choice") == "use" and not row.get("state")
        ]
        operation = self.operation(project_id)
        if qa.get("unreadable"):
            following = _unreadable_step(qa)
        elif not qa.get("task"):
            following = "Run qa --prepare."
        elif qa["applied"]:
            following = "Findings are applied; report the qa phase complete."
        elif qa.get("rules_changed") and stage not in {"", "screen", "complete"}:
            # Its finished screening may carry over to a task under the new
            # rules; a complete task's review does anyway, as later tasks
            # build on it.
            following = (
                f"{qa['message']} Its screening is finished, so run rebuild-deep as "
                f"{Path(qa['task']) / 'README.md'} says, which keeps that review "
                "when the current rules screen the same bundles; then run qa --prepare."
            )
        elif not qa["current"]:
            following = qa["message"] + " Run qa --prepare."
        elif stage not in {"", "complete"} and qa_capture_outdated(
            qa["task"], native["data"]
        ):
            # The assistant's own fixes, such as the playtest's, change the
            # game's plugins during review.
            following = (
                "The game's plugins changed since QA captured its screens; run "
                "qa --prepare, which captures them again and keeps the review."
            )
        elif stage == "complete" and waiting:
            following = (
                "The user answers the open questions in DazedTL; run qa --apply "
                "--wait <minutes>, which applies once they have."
            )
        elif stage == "complete" and unapplied:
            following = "Run qa --apply."
        elif stage == "complete":
            following = "Nothing waits to be applied; report the qa phase complete."
        elif (qa.get("activity") or {}).get("one_at_a_time"):
            following = (
                "Bundles wait while QA reviews one at a time; start four workers as "
                "the task README's Coordinator section says, and review until status "
                "reports complete."
            )
        else:
            following = (
                "Review with the task README's commands until status reports complete."
            )
        assistant = (
            self.guided.translation.project(project_id)[0].get("method") == "len"
        )
        task = qa.get("task") if qa["current"] else ""
        # Guided's Plugin files shortens these; an Assistant-led assistant
        # writes the game's plugin files itself.
        labels = (
            self.labels(Path(task))[1]
            if assistant and task and not qa["applied"]
            else []
        )
        if labels:
            following = LABELS_STEP + " " + following
        # Guided's user translates these through Event text or Plugin files.
        missed = self.untranslated_texts(project_id, native, task) if assistant else []
        if missed:
            following = UNTRANSLATED_STEP + " " + following
        state = {
            "focus": self.focus(project_id),
            "task": qa.get("task", ""),
            "stage": stage,
            "current": qa["current"],
            "applied": qa["applied"],
            "findings": len(qa["findings"]),
            "questions": len(waiting),
            "message": qa["message"],
            "next": following,
            "progress": qa["status"],
            **({"labels": labels} if labels else {}),
            **({"untranslated": len(missed)} if missed else {}),
            **({"operation": operation} if operation else {}),
        }
        if report and qa.get("task"):
            state["report"] = str(Path(qa["task"]) / "findings.json")
        return state
