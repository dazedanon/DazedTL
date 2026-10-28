"""The release playtest, which the assistant runs through the project
helper, and the Assistant-led Playtest tab runs again.

The app plays the game in a hidden window and keeps one report; it writes
nothing into the game. Findings in text QA's lines go to QA's review, and
the rest name the task that fixes them. The assistant's fixes for the game's
own code, such as a crash or a window sized for the Japanese, go in through
one plugin once a play with it in place breaks nothing new, as a checkpoint
of their own.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dazedtl.storage import write_json

from .files import digest, read_json

if TYPE_CHECKING:
    from .guided import Guided
    from .text_qa import TextQA

# `checkpoint` does nothing, now that the fixes go in as their own
# checkpoint; an assistant started before then still runs it.
STEPS = ("status", "report", "run", "fix", "checkpoint", "layout")


def game_fixes(playtest, kept):
    """What a `game` problem is and how the assistant fixes it, in both
    methods' prompts: `playtest` is the helper's playtest command and `kept`
    says how the fixes are kept once they are in the game."""
    return (
        "a crash, a script that fails, Japanese the game's own code draws, or "
        "text running past a window sized for the Japanese. Fix it in the fixes "
        f"plugin, the working copy `fixes.file` names in what {playtest} prints: "
        "plain JavaScript that js/main.js loads after the game's plugins. Give "
        "each fix its own block, starting with a comment naming the problem, and "
        "override the plugin's or engine's functions there, such as a window's "
        "width or its scene's layout, rather than changing other files. Then run "
        f"`{playtest} --fix --wait 20`: DazedTL plays the game with the plugin in "
        "place and writes it into the game only when nothing new breaks and "
        "something the last playtest found is gone; otherwise it says why and "
        "writes nothing, so revise and run it again. Editing or emptying the "
        "working copy alone changes nothing in the game. That play becomes the latest "
        f"report, and {kept} Fix crashes the translation causes; one the original "
        "game's own code causes stays as it is, in your report."
    )


def final_check(playtest, plugins, qa):
    """The playtest's part of the copied Text QA task for an RPG Maker MV/MZ
    game: the final check the assistant runs with QA, given the helper's
    playtest, plugins and qa commands."""
    return f"""
## Playtest

For this RPG Maker MV/MZ game, this task is also the final check: DazedTL plays the game and you fix what it finds. Do it while QA's workers review, so the playtest's findings in translated text join their review. Never ask the user to play the game or look at it.
Below, PLAYTEST stands for `{playtest}`, PLUGINS for `{plugins}` and QA for `{qa}`; each alone prints where its work stands.

1. Run `PLAYTEST --run --wait 20`. DazedTL checks the game's files and plays it in a hidden window for a few minutes, up to ten on a system without a GPU, and writes nothing into the game. `PLAYTEST --report` names the report file; read its problems, and look at the capture each problem the tour saw names, an image in the report folder's captures.
2. Each problem names its fix:
   - `text-qa`: text QA corrects it, since the playtest hands it to this task's review; nothing more to do while QA reviews.
   - `plugin-files`: Japanese in a plugin, which Plugin files decides. Run `PLUGINS --task`: it hands out only what is left, such as text Plugin files kept in Japanese that the playtest saw drawn, which it decides again with that evidence, or says nothing is. Follow the task it prints until it reports complete, then run `PLUGINS --apply` to put the checked files into the game. Text Plugin files kept on purpose that the playtest did not see stays as it decided.
   - `translate`: game data that was never translated; translating it is a Translate run the user starts, so report it.
   - `game`: {game_fixes("PLAYTEST", "History can restore the fixes.")} Text too long for its window may instead be shortened: record a translated line as an observation for QA's review, as the README's coordinator steps describe, and send plugin text to Plugin files.
3. The report's gaps and stops not reached name what the tour could not reach. For places only the game's events lead to, such as story scenes, other maps or a recollection room, find the map, event or common event in the game's data and add stops: write a JSON list such as `[{{"title": "Recollection room", "do": "map", "map": 12, "x": 8, "y": 6}}]` and run `PLAYTEST --run --stops FILE --wait 20`. A stop does `map` (map, x, y), `event` (event, with map, x and y to go there first), `common-event` (id), `battle` (troop), `scene` (scene) or `script` (script), and may set `switches` and `variables` ({{"id": value}}) first. DazedTL saves the stops, and every later run visits them; give `[]` to clear them.
4. A fix or a Plugin files apply changes the game's plugins, so text QA reads outdated until it captures the game's screens again: run `QA --prepare`, which resumes the same task with its review, before `QA --apply`.
5. After `QA --apply` puts QA's corrections into the game, run `PLAYTEST --run --wait 20` again and repeat steps 2 to 4 for what it finds. QA is complete by then, so `PLAYTEST` counts its text problems as `waiting`: run `QA --prepare`, which starts QA's next round with them and reviews only text not reviewed before or changed since, review that round as before, run `QA --apply`, and play the game again.
6. Finish when no playtest is running, the latest report played the game as it now is, and it holds only gaps nothing in the game's data leads to and problems you can't fix here; DazedTL shows the task as finished then. A latest report of the game as it now is that could not play it, such as for a game without its engine's scripts, ends the check too once it names no crash for you to fix and no text problem waits for QA; say why it could not play. End with a short report: what the playtest reached, what you fixed in the fixes plugin and through Plugin files, and what stays, each with why.
"""


# The operations that play the game: a playtest, and a check of the
# assistant's fixes.
PLAYS = ("release_playtest", "playtest_fix")


def stopping(state):
    """Crashes that stop the game before the playtest can play it, which the
    assistant fixes, so the check is not done with until they are; a report
    that played the game lists its crashes with its other problems."""
    if state.get("played"):
        return []
    return [
        problem
        for problem in state["problems"]
        if problem["kind"] == "crash" and problem["fix"] == "game"
    ]


def waiting(state):
    """Problems in translated text a complete QA task does not hold, which
    QA's next round reviews; a report the game outgrew holds none."""
    if not state["current"]:
        return 0
    return sum(problem.get("review") == "waiting" for problem in state["problems"])


def settled(state, running):
    """The playtest's half of an MV/MZ final check is done: nothing plays the
    game now, the latest report is of the game as it is, and no problem in
    translated text waits for QA's next round. QA's apply changes the game's
    data, so a current report played it with QA's corrections. A report that
    could not play the game settles it too once no crash stops it for the
    assistant to fix, as for a game without its engine's scripts."""
    return (
        not running
        and bool(state.get("report"))
        and state["current"]
        and not state.get("unreadable")
        and not waiting(state)
        and not stopping(state)
    )


def described(state, running):
    """The playtest's state with what both methods' QA tasks and Playtest
    panels and the helper read from it: whether it settled, and its crash and
    waiting counts."""
    return {
        **state,
        "settled": settled(state, running),
        "stopping": len(stopping(state)),
        "waiting": waiting(state),
    }


class Playtest:
    def __init__(self, guided: Guided, text_qa: TextQA):
        self.guided = guided
        self.text_qa = text_qa
        # Each game's seen plugin text, by its latest report's pointer:
        # Plugin files asks on every poll.
        self.seen: dict[str, tuple[Any, dict[str, Any]]] = {}

    def run(self, project_id, step, stops=None, widths=None):
        if step not in STEPS:
            raise ValueError("Choose a playtest step: " + ", ".join(STEPS) + ".")
        native = self.native(project_id)
        if step == "run":
            self.start(project_id, stops)
        if step == "fix":
            self.fix(project_id, native)
        if step == "layout":
            self.check_layout(project_id, widths)
        return self.status(project_id, native, report=step == "report")

    def native(self, project_id):
        """The game's Guided workspace, which keeps the playtest's reports;
        an Assistant-led game gets the one Guided would use."""
        project = self.guided.projects.get(project_id)
        if not project.get("backend_id"):
            engine = self.guided.backend.describe(project["source"])["engine"]
            if engine != "MVMZ":
                raise ValueError(
                    "The release playtest plays RPG Maker MV and MZ games."
                )
            self.guided.open(project_id)
        native = self.guided.record(project_id)[1]
        if native["engine"] != "MVMZ":
            raise ValueError("The release playtest plays RPG Maker MV and MZ games.")
        return native

    def start(self, project_id, stops):
        """Plays the game; the stops given replace the saved ones, which every
        later run visits too, so a run started from the app reaches what the
        assistant added."""
        if stops is not None and not isinstance(stops, list):
            raise ValueError("Give the playtest's stops as a list.")
        saved = self.stops(project_id)
        preview = self.guided.preview(
            project_id,
            "release_playtest",
            None,
            {
                "stops": saved if stops is None else stops,
                "focus": self.text_qa.focus(project_id),
            },
        )
        if stops is not None:
            write_json(self.guided.path(project_id, "playtest-stops"), stops)
        job = self.guided.execute(project_id, preview["token"])
        write_json(
            self.guided.path(project_id, "playtest-operation"), {"id": job["id"]}
        )

    def stops(self, project_id):
        """The places the assistant added to every run."""
        path = self.guided.path(project_id, "playtest-stops")
        return read_json(path) if path.exists() else []

    def fix(self, project_id, native):
        """Plays the game with the assistant's fixes plugin in place, then
        writes it into the game once nothing new breaks."""
        from dazedtl.compatibility.playtest import fixes_copy

        copy = fixes_copy(Path(native["source"]), Path(native["data"]).parent)
        preview = self.guided.preview(
            project_id,
            "playtest_fix",
            None,
            {
                "stops": self.stops(project_id),
                "focus": self.text_qa.focus(project_id),
                "fixes": digest(copy.read_bytes()),
            },
        )
        job = self.guided.execute(project_id, preview["token"])
        write_json(
            self.guided.path(project_id, "playtest-operation"), {"id": job["id"]}
        )

    def check_layout(self, project_id, widths):
        """Shows prose in the game's target language at the given widths in
        the game's own windows; it keeps its own report, never the
        playtest's."""
        preview = self.guided.preview(
            project_id, "layout_capture", None, {"widths": widths}
        )
        job = self.guided.execute(project_id, preview["token"])
        write_json(self.guided.path(project_id, "layout-operation"), {"id": job["id"]})

    def check_labels(self, project_id, plan):
        """Captures the screens of Plugin files' shortened labels with its
        working copies served in place of the game's files; it keeps its own
        report, never the playtest's."""
        preview = self.guided.preview(project_id, "label_capture", None, plan)
        job = self.guided.execute(project_id, preview["token"])
        write_json(self.guided.path(project_id, "label-operation"), {"id": job["id"]})

    def seen_plugin_text(self, project_id):
        """Japanese the latest playtest saw a plugin draw, for Plugin files;
        a game without a Guided workspace has none."""
        from dazedtl.compatibility.playtest import POINTER, seen_plugin_text

        none: dict[str, Any] = {"report": "", "texts": []}
        project = self.guided.projects.get(project_id)
        native = self.guided.backend.workflows.projects.get(project.get("backend_id"))
        if not native:
            return none
        folder = Path(self.guided.backend.workflows.folder(native["id"]))
        try:
            stat = (folder / POINTER).stat()
        except OSError:
            return none
        key = (stat.st_mtime_ns, stat.st_size)
        saved = self.seen.get(project_id)
        if not saved or saved[0] != key:
            saved = self.seen[project_id] = (key, seen_plugin_text(folder))
        return saved[1]

    def labels(self, project_id):
        """The latest label check, with the operation that makes it, or None."""
        from dazedtl.compatibility.playtest import latest_labels

        native = self.guided.record(project_id)[1]
        operation = self.operation(project_id, "label-operation")
        try:
            saved = latest_labels(self.guided.backend.workflows.folder(native["id"]))
        except OSError, ValueError, KeyError, TypeError:
            saved = None
        if not operation and not saved:
            return None
        return {**(saved or {}), **({"operation": operation} if operation else {})}

    def layout(self, project_id, native):
        """The latest layout check: each window's fit and its capture."""
        from util.playtest.run import LAYOUT_SCHEMA

        from dazedtl.compatibility.playtest import latest_layout

        operation = self.operation(project_id, "layout-operation")
        try:
            saved = latest_layout(self.guided.backend.workflows.folder(native["id"]))
        except OSError, ValueError, KeyError, TypeError:
            saved = None
        # An earlier release's check judged fits without headroom.
        if saved and saved.get("schema") != LAYOUT_SCHEMA:
            saved = None
        if not operation and not saved:
            return None
        result: dict[str, Any] = {"operation": operation} if operation else {}
        if saved:
            files = {capture["name"]: capture["file"] for capture in saved["captures"]}
            result.update(
                finished_at=saved["finished_at"],
                widths=saved["widths"],
                probes=[
                    {
                        **{
                            key: probe[key]
                            for key in (
                                "title",
                                "fits",
                                "widest",
                                "room",
                                "spare",
                                "lines",
                                "rows",
                            )
                        },
                        # A probe the window drew no text in has neither.
                        **{
                            key: probe[key]
                            for key in ("spareCharacters", "suggested")
                            if key in probe
                        },
                        **(
                            {
                                "capture": str(
                                    Path(saved["folder"]) / files[probe["capture"]]
                                )
                            }
                            if probe.get("capture") in files
                            else {}
                        ),
                    }
                    for probe in saved["probes"]
                ],
                missing=saved["missing"],
                # A check an earlier release saved has neither.
                **{key: saved[key] for key in ("headroom", "fallback") if key in saved},
                **(
                    {"unavailable": saved["unavailable"]}
                    if saved.get("unavailable")
                    else {}
                ),
            )
        return result

    def operation(self, project_id, pointer="playtest-operation"):
        """The last playtest started, with its current state."""
        path = self.guided.path(project_id, pointer)
        if not path.exists():
            return None
        identity = read_json(path)["id"]
        operations = self.guided.backend.operations
        job = operations.jobs.get(identity) or {}
        state = job.get("status", "interrupted")
        # A job reports its end before its worker exits.
        if operations.active == identity:
            state = "running"
        return {
            "id": identity,
            "status": state,
            "message": str(job.get("message") or ""),
        }

    def status(self, project_id, native, report=False):
        text = self.guided.backend.guided_text_state(
            native, self.text_qa.focus(project_id)
        )
        state = text["playtest"]
        operation = self.operation(project_id)
        problems = state["problems"]
        held = state["waiting"]
        stops = (state.get("coverage") or {}).get("stops", [])
        assistant = self.guided.projects.get(project_id).get("method") == "len"
        fixes = self.fixes(native)
        if operation and operation["status"] == "running":
            following = "The playtest is running; wait with playtest --wait MINUTES or check again."
        elif fixes.get("other_in_game"):
            following = (
                "The game runs other fixes than the working copy fixes.file names, "
                "such as an older copy; changing or emptying the working copy alone "
                "changes nothing in the game. To put the working copy in, run "
                "playtest --fix. To take the game's fixes out, "
                + (
                    "remove the fixes plugin and its loading line in js/main.js "
                    "from the game and save a checkpoint."
                    if assistant
                    else "the user restores their batch, Apply playtest fixes, in "
                    "the project's History; say so in your report."
                )
            )
        elif not state.get("report"):
            following = "Run playtest --run."
        elif not state["current"]:
            following = "The game changed after the last playtest; run playtest --run."
        elif held:
            following = (
                (
                    f"QA is complete, so {held} text problem(s) wait for its next round"
                    if text["qa"]["status"]
                    else f"{held} text problem(s) wait for text QA"
                )
                + ": run qa --prepare, review it and run qa --apply, then run "
                "playtest --run again."
            )
        elif state["stopping"]:
            following = (
                "The game stops before the playtest can play it: fix that crash in "
                "the fixes file and run playtest --fix."
            )
        elif not state.get("played"):
            following = (
                "The playtest could not play the game, and its report names no "
                "crash for you to fix"
                + (f" ({state['gaps'][0].rstrip('.')})" if state["gaps"] else "")
                + ", so it ends without a play: handle the report's other "
                "problems, then report why it could not play."
            )
        elif problems or state["gaps"]:
            following = (
                "Read the report: write fixes for crashes and windows sized for the "
                "Japanese in the fixes file and run playtest --fix, "
                + (
                    "translate plugin text through your extraction and injection "
                    "steps, "
                    if assistant
                    else "send plugin text to Plugin files, "
                )
                + "let text QA correct its lines, and add stops for what the tour "
                "could not reach with playtest --run --stops FILE."
            )
        else:
            following = (
                "The playtest found nothing to fix; report it with its coverage."
            )
        result = {
            "current": state["current"],
            "finished_at": state.get("finished_at", ""),
            "problems": dict(Counter(problem["fix"] for problem in problems)),
            "waiting": held,
            "settled": state["settled"],
            "seen": sum(bool(problem.get("seen")) for problem in problems),
            "gaps": len(state["gaps"]),
            "reached": f"{sum(stop['status'] == 'done' for stop in stops)} of {len(stops)}",
            "next": following,
            "stops": len(self.stops(project_id)),
            "fixes": fixes,
            **({"operation": operation} if operation else {}),
        }
        layout = self.layout(project_id, native)
        if layout:
            result["layout"] = layout
        if report and state.get("report"):
            from dazedtl.compatibility.playtest import STORAGE

            result["report"] = str(
                Path(self.guided.backend.workflows.folder(native["id"]))
                / STORAGE
                / state["report"]
                / "report.json"
            )
        return result

    def fixes(self, native):
        """The fixes plugin's working copy and latest check."""
        from dazedtl.compatibility.playtest import fixes_state

        return fixes_state(
            self.guided.backend.workflows.folder(native["id"]),
            Path(native["source"]),
            Path(native["data"]).parent,
        )

    def capture(self, project_id, name):
        from dazedtl.compatibility.playtest import capture

        native = self.guided.record(project_id)[1]
        return capture(self.guided.backend.workflows.folder(native["id"]), name)
