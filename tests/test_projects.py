"""Project identity and selection must survive navigation and failed saves."""

import json
import shutil
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.projects import location
from dazedtl.projects.languages import ProjectLanguages
from dazedtl.projects.location import UNRECOGNIZED, Locations
from dazedtl.projects.store import SCHEMA_VERSION, Projects


class ProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.projects = Projects(self.root)

    def game(self, name):
        path = self.root / name
        path.mkdir(exist_ok=True)
        return {"source": str(path), "engine": "MVMZ"}

    def test_reopening_and_switching_preserve_job_ownership(self):
        detected = self.game("first")
        identity = "1" * 32
        original = {
            "version": 1,
            "current_id": identity,
            "screen": "guided",
            "projects": [
                {
                    "id": identity,
                    "name": "first",
                    "source": detected["source"],
                    "engine": "MVMZ",
                    "method": "guided",
                    "backend_id": "saved-job-owner",
                    "phase": "dialogue",
                }
            ],
        }
        self.projects.path.write_text(json.dumps(original), encoding="utf-8")
        original_bytes = self.projects.path.read_bytes()
        self.projects = Projects(self.root)
        self.assertEqual(self.projects.data["screen"], "translation")
        self.assertEqual(
            next((self.root / "backups").iterdir()).read_bytes(), original_bytes
        )
        reopened = self.projects.open(
            {**detected, "source": detected["source"] + "/."}, "len"
        )
        self.assertEqual(reopened["id"], identity)
        self.assertEqual(reopened["method"], "guided")
        self.projects.navigate("translation")
        self.projects.navigate("guided")
        self.projects.navigate("manual")
        self.projects.navigate("settings")
        second = self.projects.open(self.game("second"), "len")
        self.assertNotEqual(second["id"], identity)
        # The chosen method survives reopening; only the two methods qualify.
        self.projects.choose_method(identity, "len")
        with self.assertRaises(ValueError):
            self.projects.choose_method(identity, "translation")
        self.assertEqual(self.projects.open(detected)["method"], "len")
        self.projects.select(identity)
        restored = Projects(self.root)
        self.assertEqual(restored.data["version"], SCHEMA_VERSION)
        self.assertEqual(len(restored.data["projects"]), 2)
        self.assertEqual(restored.current["id"], identity)
        self.assertEqual(restored.current["backend_id"], "saved-job-owner")
        self.assertEqual(restored.current["phase"], "dialogue")

    def test_version_four_overview_opens_on_the_project_page(self):
        self.projects.path.write_text(
            json.dumps(
                {
                    "version": 4,
                    "current_id": "",
                    "screen": "overview",
                    "projects": [],
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(Projects(self.root).data["screen"], "project")

    def test_removed_game_leaves_the_list_and_keeps_its_work(self):
        first = self.projects.open(self.game("first"), "len")
        second = self.projects.open(self.game("second"), "len")

        def recent():
            return [project["id"] for project in self.projects.state()["recent"]]

        self.projects.remove(second["id"])
        self.assertIsNone(self.projects.current)
        self.assertEqual(self.projects.data["screen"], "project")
        self.assertEqual(recent(), [first["id"]])
        self.projects.remove(first["id"])
        self.assertEqual(recent(), [])
        # Saved runs and Batches still find their owner after a restart.
        restored = Projects(self.root)
        self.assertEqual(restored.get(second["id"])["source"], second["source"])
        # Opening the game again brings back the same project.
        self.assertEqual(restored.open(self.game("second"))["id"], second["id"])
        self.projects = restored
        self.assertEqual(recent(), [second["id"]])

    def test_invalid_navigation_cannot_switch_or_modify_projects(self):
        self.projects.open(self.game("first"), "len")
        before = deepcopy(self.projects.data)
        saved = self.projects.path.read_bytes()
        for action in (
            lambda: self.projects.select("missing"),
            lambda: self.projects.remove("missing"),
            lambda: self.projects.navigate("missing"),
        ):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    action()
                self.assertEqual(self.projects.data, before)
                self.assertEqual(self.projects.path.read_bytes(), saved)

    def test_failed_selection_or_creation_keeps_current_project(self):
        first = self.projects.open(self.game("first"), "guided")
        self.projects.open(self.game("second"), "len")
        third = self.game("third")
        for action in (
            lambda: self.projects.select(first["id"]),
            lambda: self.projects.remove(first["id"]),
            lambda: self.projects.open(third, "guided"),
            lambda: self.projects.navigate("settings"),
        ):
            with self.subTest(action=action):
                before = deepcopy(self.projects.data)
                saved = self.projects.path.read_bytes()
                with (
                    patch(
                        "dazedtl.projects.store.write_json",
                        side_effect=OSError("No space"),
                    ),
                    self.assertRaises(OSError),
                ):
                    action()
                self.assertEqual(self.projects.path.read_bytes(), saved)
                self.assertEqual(self.projects.data, before)


class LocationTests(unittest.TestCase):
    """Opening a moved game continues its project; a copy is a new one."""

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.projects = Projects(self.root / "profile")
        self.worked, self.moves, self.running = set(), [], False
        self.locations = Locations(
            self.projects,
            detect=lambda root: (
                "MVMZ" if (Path(root) / "data/System.json").is_file() else UNRECOGNIZED
            ),
            has_work=lambda project: project["id"] in self.worked,
            busy=lambda: self.running,
            relocate=lambda project, before: self.moves.append(
                (project["id"], before, project["source"])
            ),
        )

    def game(self, path, repository=True):
        folder = self.root / path
        (folder / "data").mkdir(parents=True)
        (folder / "data/System.json").write_text("{}", encoding="utf-8")
        if repository:
            (folder / ".git").mkdir()
        return folder

    def move(self, before, after):
        after = self.root / after
        after.parent.mkdir(parents=True, exist_ok=True)
        return (self.root / before).rename(after)

    @staticmethod
    def progress(game, work, project_id):
        """Saved Plugin files or Images progress, which names its project."""
        (game / work).mkdir(parents=True)
        (game / work / "state.json").write_text(
            json.dumps({"version": 1, "projectId": project_id}), encoding="utf-8"
        )

    def test_a_moved_game_continues_its_project_and_a_copy_starts_another(self):
        first = self.locations.open(self.game("first"))
        self.assertEqual(
            location.marked(self.root / "first", self.locations.known), first["id"]
        )
        # Renamed, its marker names the project, which follows it there.
        renamed = self.move("first", "renamed")
        self.assertFalse(self.locations.holds(self.projects.get(first["id"])))
        moved = self.locations.open(renamed)
        self.assertEqual(moved["id"], first["id"])
        self.assertEqual(moved["source"], str(renamed))
        self.assertEqual(moved["name"], "first")
        self.assertEqual(
            self.moves, [(first["id"], str(self.root / "first"), str(renamed))]
        )
        self.assertEqual(len(self.projects.data["projects"]), 1)
        # A copy opens as a project of its own while the game is still there,
        # and its marker then names that project.
        copy = self.root / "copy"
        shutil.copytree(renamed, copy)
        other = self.locations.open(copy)
        self.assertNotEqual(other["id"], first["id"])
        self.assertEqual(location.marked(copy, self.locations.known), other["id"])
        self.assertEqual(self.projects.get(first["id"])["source"], str(renamed))
        # A folder no project names opens as a new project too.
        unknown = self.locations.open(self.game("unknown"))
        self.assertNotIn(unknown["id"], {first["id"], other["id"]})
        # Another profile opening the game names its own project there, which
        # this profile doesn't know: the game is still where it was.
        location.mark(renamed, "f" * 32)
        self.assertTrue(self.locations.holds(self.projects.get(first["id"])))
        self.assertEqual(self.locations.open(renamed)["id"], first["id"])

    def test_a_game_moved_inside_its_old_folder_replaces_an_empty_project_there(self):
        # The user's layout: the game moved into a Game folder inside its old
        # one, saved before the marker, so only its Plugin files progress names
        # its project, and the new folder already opened as an empty project.
        old = self.game("RJ01", repository=False)
        project = self.locations.open(old)
        self.progress(old, ".dazedtl/plugin-work", project["id"])
        (old / ".git").mkdir()
        self.move("RJ01", "moving")
        old.mkdir()
        new = self.move("moving", "RJ01/Game")
        empty = self.projects.open({"source": str(new), "engine": "MVMZ"})
        self.projects.remove(project["id"])
        self.assertFalse(self.locations.holds(self.projects.get(project["id"])))
        # Picking the empty project from the list opens the game's own, once
        # no run is executing; until then the pick opens what it names.
        self.running = True
        picked = self.locations.open(new, self.projects.get(empty["id"]))
        self.assertEqual(picked["id"], empty["id"])
        self.assertIsNone(location.marked(new, self.locations.known))
        self.running = False
        moved = self.locations.open(new, self.projects.get(empty["id"]))
        self.assertEqual((moved["id"], moved["source"]), (project["id"], str(new)))
        self.assertTrue(self.projects.get(empty["id"])["hidden"])
        self.assertEqual(self.projects.at(new)["id"], project["id"])
        self.assertEqual(
            [p["id"] for p in self.projects.state()["recent"]], [project["id"]]
        )

    def test_a_moved_game_whose_old_folder_was_opened_again_is_found(self):
        # The user's 2.33.1 layout: a Guided project's game moved into a Game
        # folder inside its old one, the old folder opened again first, and
        # Game opened as an empty project that its marker then named.
        for name, find in (("RJ01", True), ("RJ02", False)):
            with self.subTest(find=find):
                old = self.game(name, repository=False)
                project = self.locations.open(old)
                self.progress(old, ".dazedtl/plugin-work", project["id"])
                (old / ".git").mkdir()
                self.move(name, "moving")
                old.mkdir()
                new = self.move("moving", f"{name}/Game")
                (old / ".dazedtl/image_manager").mkdir(parents=True)
                self.assertEqual(self.locations.open(old)["engine"], "MVMZ")
                # Earlier versions saved the old folder's label over its engine.
                data = deepcopy(self.projects.data)
                record = self.projects._get(data, project["id"])
                record.update(
                    engine=UNRECOGNIZED, backend_id="b" * 32, phase="dialogue"
                )
                self.projects._commit(data)
                self.assertFalse(self.locations.holds(self.projects.get(project["id"])))
                empty = self.projects.open({"source": str(new), "engine": "MVMZ"})
                location.mark(new, empty["id"])
                moved = (
                    self.locations.find(project["id"], new)
                    if find
                    else self.locations.open(new)
                )
                self.assertEqual(
                    (moved["id"], moved["source"], moved["engine"]),
                    (project["id"], str(new), "MVMZ"),
                )
                self.assertTrue(self.projects.get(empty["id"])["hidden"])
                self.assertEqual(
                    location.marked(new, self.locations.known), project["id"]
                )
        # A project that never linked a game still counts a folder there that
        # names no project, such as an Assistant-led game of another engine.
        other = self.root / "other"
        other.mkdir()
        unknown = self.locations.open(other)
        self.assertEqual(unknown["engine"], UNRECOGNIZED)
        self.assertTrue(self.locations.holds(unknown))

    def test_a_project_with_work_at_the_new_folder_keeps_it(self):
        old = self.game("old", repository=False)
        project = self.locations.open(old)
        self.progress(old, ".dazedtl/image_manager/guided", project["id"])
        new = self.move("old", "new")
        there = self.projects.open({"source": str(new), "engine": "MVMZ"})
        self.worked.add(there["id"])
        self.assertEqual(self.locations.open(new)["id"], there["id"])
        self.assertEqual(self.projects.get(project["id"])["source"], str(old))
        self.assertFalse(self.projects.get(there["id"]).get("hidden"))
        self.assertEqual(self.moves, [])
        with self.assertRaisesRegex(ValueError, "saved work uses that folder"):
            self.locations.find(project["id"], new)

    def test_find_game_folder_moves_only_to_the_same_game_while_nothing_runs(self):
        project = self.locations.open(self.game("old"))
        new = self.move("old", "drive/old")
        stranger = self.locations.open(self.game("stranger"))
        with self.assertRaisesRegex(ValueError, "another project's game"):
            self.locations.find(project["id"], self.root / "stranger")
        with self.assertRaisesRegex(ValueError, "doesn't hold this project's game"):
            self.locations.find(project["id"], self.root / "drive")
        self.running = True
        with self.assertRaisesRegex(ValueError, "running work"):
            self.locations.find(project["id"], new)
        self.assertEqual(self.projects.current["id"], stranger["id"])
        self.running = False
        found = self.locations.find(project["id"], new)
        self.assertEqual((found["id"], found["source"]), (project["id"], str(new)))
        self.assertEqual(self.projects.current["id"], project["id"])

    def test_recent_games_whose_folder_is_gone_read_unavailable(self):
        """The recent list marked only the open project's missing folder; each
        other folder is looked at again only once its last look is stale."""
        here = {"id": "here", "source": str(self.game("here"))}
        gone = {"id": "gone", "source": str(self.game("gone"))}
        folders = location.RecentFolders(wait=5)
        marked = folders.mark([here, gone], None, False)
        self.assertEqual([row["available"] for row in marked], [True, True])
        shutil.rmtree(gone["source"])
        self.assertTrue(folders.mark([gone], None, False)[0]["available"])
        folders.fresh = 0
        unavailable = folders.mark([here, gone], here, False)
        self.assertEqual(
            [(row["available"], row.get("status")) for row in unavailable],
            [(False, "Game folder unavailable")] * 2,
        )

    def test_a_games_languages_change_until_it_has_work_then_stay(self):
        """Set up's choice of a game's languages, and the pair a game with
        work keeps when Settings' default pair changes."""
        settings = SimpleNamespace(
            source_language=lambda: "Japanese", language=lambda: "English"
        )
        languages = ProjectLanguages(
            self.projects,
            settings,
            holds=self.locations.holds,
            has_work=lambda project: project["id"] in self.worked,
        )
        old = self.locations.open(self.game("old", repository=False))
        new = self.locations.open(self.game("new", repository=False))
        japanese = {"source": "Japanese", "target": "English", "characters": False}
        self.assertEqual(languages.view(new), japanese)
        languages.change(new["id"], "english", "Japanese")
        self.assertEqual(
            languages.view(new),
            {"source": "English", "target": "Japanese", "characters": True},
        )
        with self.assertRaisesRegex(ValueError, "same script"):
            languages.change(new["id"], "English", "French")
        self.assertEqual(languages.locked(new), "")
        self.worked.update((old["id"], new["id"]))
        # Set up reads the same refusal before Save as Save gives.
        self.assertIn("English into Japanese", languages.locked(new))
        with self.assertRaisesRegex(ValueError, "can't change"):
            languages.change(new["id"], "Japanese", "English")
        # A game set up before pairs were recorded keeps the pair its work
        # reads once Settings' defaults change.
        languages.keep_every()
        settings.source_language = lambda: "English"
        settings.language = lambda: "Japanese"
        self.assertEqual(languages.view(old), japanese)
        # A game not set up yet starts with the pair Settings name.
        fresh = self.locations.open(self.game("fresh", repository=False))
        self.assertEqual(
            languages.view(fresh),
            {"source": "English", "target": "Japanese", "characters": True},
        )
