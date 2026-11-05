"""Translation files carry a project's lines out of DazedTL and back, and a
Manual project translates the one its own extractor wrote."""

import json
import unittest
from pathlib import Path

from dazedtl.api.contracts.validation import check_response
from dazedtl.storage import write_json
from dazedtl.translation import progress_report, translation_file, unit_results
from dazedtl.translation.exchange import Exchange
from dazedtl.translation.files import read_json
from dazedtl.translation.game_update import ABSENT
from dazedtl.translation.manual import Manual
from dazedtl.translation.manual import loaded as loaded_file
from dazedtl.translation.project import WORK
from dazedtl.translation.results import Results

from tests import test_workflow

PAIR = {"source": "Japanese", "target": "English"}


def line(identity, source, translation=None, **fields):
    return {
        "id": identity,
        "scene": identity.split("/")[0],
        "source": source,
        "translation": translation,
        **fields,
    }


class TranslationFileTests(unittest.TestCase):
    prepared = test_workflow.WorkflowTests.prepared

    def setUp(self):
        test_workflow.WorkflowTests.setUp(self)
        # Game-shaped, so the suite's write check holds the glossary an
        # import adds to the game-write gateway.
        (self.game / "data").mkdir()

    def file(self, name, lines, **extra):
        path = self.root / name
        translation_file.write(
            path,
            {
                **translation_file.document(
                    {"source": "Japanese", "target": "English"}, lines
                ),
                **extra,
            },
        )
        return path

    def accept(self, run, translations):
        """Saves a provider's reply to each of the run's requests."""
        _job, plan = self.service.jobs.store.load(run, self.identity)
        for request in plan["requests"]:
            Results(self.game).accept(
                request,
                {identity: translations[identity] for identity in request["sources"]},
                {"kind": "fixture"},
            )

    def test_a_manual_project_translates_its_own_file_and_exports_every_line(self):
        # A Manual game has no Git baseline and no census: its own extractor
        # decides the scope and writes the game.
        self.engine.git_status = lambda *_args: {}
        self.projects.choose_method(self.identity, "manual")
        # Options Assistant-led saved as Assistant only, which Manual lacks.
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        manual = Manual(self.service)
        # The example Text saves for the user's own extractor loads as is.
        example = manual.example(self.identity, str(self.root / "example.json"))
        check_response("manual_example", example)
        shown = manual.load(self.identity, example["path"])
        self.assertEqual(
            (shown["loaded"]["lines"], shown["added"], shown["glossary"]["added"]),
            (2, 1, 1),
        )
        source = self.file(
            "extracted.json",
            [
                line("a/1", "はい。", "Yes.", kind="dialogue", speaker="リリ"),
                line("b/1", "いいえ。", kind="dialogue", speaker="リリ"),
                line("b/2", "「……」"),
            ],
        )
        loaded = manual.load(self.identity, str(source))
        check_response("manual_load", loaded)
        self.assertEqual(
            (loaded["added"], loaded["empty"], loaded["loaded"]["lines"]), (1, 2, 3)
        )
        self.assertEqual(
            self.service.state(self.identity)["manual"]["loaded"]["scenes"], 2
        )
        organized = self.prepared(manual.estimate(self.identity))
        run = organized["run"]["id"]
        # Only the line without a translation is sent; the file's own
        # translation and the punctuation-only line need no request.
        self.assertEqual(organized["run"]["requests"], 1)
        self.assertEqual(
            (organized["summary"]["translated"], organized["summary"]["converted"]),
            (1, 1),
        )
        _job, plan = self.service.jobs.store.load(run, self.identity)
        self.assertEqual(plan["method"], "manual")
        # Its estimate reads current, so Approve takes it.
        view = next(
            job for job in self.service.state(self.identity)["jobs"] if job["id"] == run
        )
        self.assertFalse(view["settings_changed"] or view["pricing_changed"])
        self.service.validate_current(self.identity, plan, compiled=False)
        # Estimating again after a settings change prepares a Manual run again.
        self.settings_data["connections"][0]["endpoint"] = "https://other.invalid/v1"
        run = self.prepared(self.service.reestimate(self.identity, run))["run"]["id"]
        _job, plan = self.service.jobs.store.load(run, self.identity)
        self.assertEqual(
            (plan["method"], plan["configuration"]["endpoint"]),
            ("manual", "https://other.invalid/v1"),
        )
        self.accept(run, {"b/1": "No."})
        self.assertFalse(progress_report.kept(self.profile, self.identity).exists())
        exchange = Exchange(self.service, None)
        exported = exchange.export(self.identity, str(self.root / "out.json"))
        check_response("project_translation_export", exported)
        self.assertEqual((exported["lines"], exported["translated"]), (3, 3))
        written = read_json(self.root / "out.json")
        self.assertEqual(
            [(row["id"], row["translation"]) for row in written["lines"]],
            [("a/1", "Yes."), ("b/1", "No."), ("b/2", '"……"')],
        )
        self.assertEqual(written["lines"][0]["speaker"], "リリ")
        with self.assertRaisesRegex(ValueError, "outside the game folder"):
            exchange.export(self.identity, str(self.game / "out.json"))
        # A new extraction keeps each line's translation while its ID and
        # source stay; a changed source is translated again.
        manual.load(
            self.identity,
            str(
                self.file(
                    "again.json",
                    [line("a/1", "はい。"), line("b/1", "いいや。")],
                )
            ),
        )
        again = self.prepared(manual.estimate(self.identity))
        self.assertEqual(
            (again["run"]["requests"], again["summary"]["translated"]), (1, 1)
        )
        store = self.service.jobs.store
        # The new file discarded the first file's estimate, and Progress
        # leaves that run to History.
        self.assertEqual(store.record(run, self.identity)["status"], "canceled")
        views = {job["id"]: job for job in self.service.state(self.identity)["jobs"]}
        self.assertFalse(views[run]["own"])
        self.assertTrue(views[again["run"]["id"]]["own"])
        # An approved run stopped before it finished. While the provider may
        # still answer one of its requests, a load that changes its lines is
        # refused before it writes anything.
        stopped = store.record(again["run"]["id"], self.identity)
        store.authorize(stopped)
        stopped = store.record(again["run"]["id"], self.identity)
        request = next(iter(stopped["states"]))
        stopped["states"][request]["state"] = "queued"
        stopped["status"] = "stopped"
        store.save(stopped)
        mine = self.file(
            "mine.json", [line("a/1", "はい。"), line("b/1", "いいや。", "Nope, mine.")]
        )
        with self.assertRaisesRegex(ValueError, "may still be answered"):
            manual.load(self.identity, str(mine))
        self.assertEqual(loaded_file(self.game)["name"], "again.json")
        # So is one whose glossary the game-write gateway refuses, such as
        # during a stopped game update.
        stopped["states"][request]["state"] = "pending"
        store.save(stopped)

        def refused(*_args):
            raise ValueError("Finish or cancel the game update first.")

        self.engine.glossary_add = refused
        glossary = [{"section": "Game Terms", "source": "村", "translation": "Village"}]
        with self.assertRaisesRegex(ValueError, "game update"):
            manual.load(
                self.identity,
                str(
                    self.file(
                        "terms.json",
                        [line("a/1", "はい。"), line("b/1", "いいや。", "Nope, mine.")],
                        glossary=glossary,
                    )
                ),
            )
        self.assertEqual(loaded_file(self.game)["name"], "again.json")
        self.assertNotIn("superseded", store.record(again["run"]["id"], self.identity))
        del self.engine.glossary_add
        # Once it holds none, the load supersedes it, so neither its approval
        # nor Resume pays for the line again or replaces it.
        manual.load(self.identity, str(mine))
        self.assertTrue(store.record(again["run"]["id"], self.identity)["superseded"])
        with self.assertRaisesRegex(ValueError, "sends nothing more"):
            self.service.start(self.identity, again["run"]["id"])
        # Assistant-led's pages leave Manual's runs to History.
        self.projects.choose_method(self.identity, "len")
        views = {job["id"]: job for job in self.service.state(self.identity)["jobs"]}
        self.assertFalse(views[run]["own"])

    def test_a_manual_projects_gameupdate_box_copies_it_into_the_game(self):
        self.engine.git_status = lambda *_args: {}
        manual = Manual(self.service)
        # Assistant-led's assistant installs GameUpdate itself.
        with self.assertRaisesRegex(ValueError, "isn't translated Manually"):
            manual.gameupdate(self.identity, True)
        self.projects.choose_method(self.identity, "manual")
        # Manual has none, so ticking the box copies GameUpdate into the game
        # at once, whatever its engine, and unticking takes it out; the
        # player README stays.
        # The engine's status says whether the game holds GameUpdate.
        self.engine.game_update = lambda source, *_args: {
            **ABSENT,
            "installed": (Path(source) / "gameupdate/patch.sh").is_file(),
        }
        shown = manual.gameupdate(self.identity, True)
        check_response("manual_gameupdate", shown)
        self.assertTrue(shown["installed"])
        self.assertTrue((self.game / "gameupdate/patch.sh").is_file())
        self.assertFalse(manual.gameupdate(self.identity, False)["installed"])
        self.assertFalse((self.game / "GameUpdate.bat").exists())
        self.assertFalse((self.game / "gameupdate").exists())
        self.assertTrue((self.game / "README.md").is_file())

    def test_an_import_lands_on_lines_whose_id_and_source_match(self):
        selected = self.project.read()
        self.service.save(
            self.identity,
            selected["revision"],
            {**selected["options"], "mode": "agent"},
        )
        units = WORK + "/work/source-units.json"
        write_json(
            self.game / units,
            {
                "version": 1,
                "units": [
                    {"id": "a/1", "scene": "a", "source": "\\C[2]はい\\C[0]。"},
                    {"id": "a/2", "scene": "a", "source": "いいえ。"},
                    {"id": "a/3", "scene": "a", "source": "ー第一章ー"},
                    {"id": "b/1", "scene": "b", "source": "うん。"},
                ],
            },
        )
        run = self.prepared(self.service.organize(self.identity, units))["run"]["id"]
        self.accept(
            run,
            {
                "a/1": "\\C[2]Yes\\C[0].",
                "a/2": "No.",
                "a/3": "-Chapter One-",
                "b/1": "Yeah.",
            },
        )
        (self.game / ".dazedtl").mkdir(exist_ok=True)
        (self.game / ".dazedtl/glossary.txt").write_text(
            "# Game Characters\nリリ (Lili) - female\n\n# Speakers\nサキ (Saki)\n",
            encoding="utf-8",
        )
        exchange = Exchange(self.service, None)
        exchange.export(self.identity, str(self.root / "shared.json"))
        shared = read_json(self.root / "shared.json")
        self.assertEqual(
            shared["glossary"],
            [
                {
                    "section": "Game Characters",
                    "source": "リリ",
                    "translation": "Lili",
                    "note": "female",
                },
                {
                    "section": "Speakers",
                    "source": "サキ",
                    "translation": "Saki",
                    "note": "",
                },
            ],
        )
        rows = {row["id"]: row for row in shared["lines"]}
        rows["a/1"]["translation"] = "Sure."  # drops its colour codes
        rows["a/2"]["translation"] = "Nope."
        # A spreadsheet read "-Chapter One-" as a formula.
        rows["a/3"]["translation"] = "#NAME?"
        rows["b/1"]["source"] = "うんうん。"
        shared["lines"].append(line("c/1", "ほう。", "Oh."))
        shared["glossary"] += [
            {"section": "Game Characters", "source": "ミカ", "translation": "Mika"},
            # A name another section holds stays the game's, since the
            # character section would outrank it in requests.
            {"section": "Game Characters", "source": "サキ", "translation": "Sakki"},
        ]
        path = self.root / "edited.json"
        path.write_text(json.dumps(shared, ensure_ascii=False), encoding="utf-8")
        preview = exchange.preview(self.identity, str(path))
        check_response("project_translation_preview", preview)
        self.assertEqual(
            {
                key: preview[key]
                for key in ("replaced", "refused", "changed", "unknown", "unchanged")
            },
            {"replaced": 1, "refused": 2, "changed": 1, "unknown": 1, "unchanged": 0},
        )
        self.assertEqual(
            [row["id"] for row in preview["skipped"]], ["b/1", "c/1", "a/1", "a/3"]
        )
        self.assertIn("control codes", preview["skipped"][2]["reason"])
        self.assertIn("spreadsheet", preview["skipped"][3]["reason"])
        self.assertEqual(preview["glossary"], {"added": 1, "same": 2, "differs": 1})
        with self.assertRaisesRegex(ValueError, "changed after it was checked"):
            exchange.apply(self.identity, str(path), "0" * 64)
        check_response(
            "project_translation_import",
            exchange.apply(self.identity, str(path), preview["sha256"]),
        )
        exchange.export(self.identity, str(self.root / "after.json"))
        exported = {
            row["id"]: row["translation"]
            for row in read_json(self.root / "after.json")["lines"]
        }
        self.assertEqual(
            exported,
            {
                "a/1": "\\C[2]Yes\\C[0].",
                "a/2": "Nope.",
                "a/3": "-Chapter One-",
                "b/1": "Yeah.",
            },
        )
        glossary = (self.game / ".dazedtl/glossary.txt").read_text(encoding="utf-8")
        self.assertIn("ミカ (Mika)", glossary)
        self.assertIn("リリ (Lili) - female", glossary)
        self.assertNotIn("Sakki", glossary)
        # Importing an earlier file again wins over a later one, as its
        # newest import.
        later = self.file("later.json", [line("a/2", "いいえ。", "Nah.")])
        for name in (later, path):
            exchange.apply(
                self.identity,
                str(name),
                exchange.preview(self.identity, str(name))["sha256"],
            )
        exchange.export(self.identity, str(self.root / "again.json"))
        self.assertEqual(
            {
                row["id"]: row["translation"]
                for row in read_json(self.root / "again.json")["lines"]
            }["a/2"],
            "Nope.",
        )
        # A later organize keeps the imported line, and its request reads as
        # a run's does, to review or correct it.
        again = self.prepared(self.service.organize(self.identity, units))["run"]["id"]
        _job, plan = self.service.jobs.store.load(again, self.identity)
        imported = [
            fingerprint
            for fingerprint, value in plan["reused"]["requests"].items()
            if value["id"].startswith("imported-")
        ]
        self.assertTrue(imported)
        fingerprint = imported[0]
        self.assertTrue(
            self.service.request(self.identity, again, request_sha256=fingerprint)
        )
        # A correction through that run keeps the request, even once the
        # index beside the receipts is lost.
        held = unit_results.held(
            self.service.jobs.store, self.identity, {fingerprint}, self.game
        )[fingerprint]
        fix = WORK + "/work/fix.json"
        write_json(
            self.game / fix,
            {
                "request_sha256": fingerprint,
                "translations": {"a/2": "Nah, fixed."},
                "replaces_sha256": Results(self.game).get(held)["result_sha256"],
            },
        )
        self.service.accept(
            self.identity, again, plan["reused"]["requests"][fingerprint]["id"], fix
        )
        (self.game / unit_results.INDEX).unlink()
        self.assertTrue(
            self.service.request(self.identity, again, request_sha256=fingerprint)
        )
        # The corrected import is read like a run's with the index lost.
        self.assertEqual(
            unit_results.translations(
                self.service.jobs.store,
                self.identity,
                self.game,
                [
                    {
                        "id": "a/2",
                        "source": "いいえ。",
                        "kind": "unknown",
                        "speaker": None,
                        "constraints": {},
                    }
                ],
                "Japanese",
                "English",
            ),
            {"a/2": "Nah, fixed."},
        )


class FileFormatTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory

        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_csv_carries_multiline_japanese_and_reads_back_as_written(self):
        lines = [
            line("a/1", "一行目\n二行目", 'He said, "Hi."\nThen left.', speaker="リリ"),
            line("a/2", "メニュー", None, kind="ui", max_characters=12),
        ]
        path = self.root / "lines.csv"
        translation_file.write(
            path,
            translation_file.document(
                {"source": "Japanese", "target": "English"}, lines
            ),
        )
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        read = translation_file.read(path)
        self.assertIsNone(read["languages"])
        self.assertEqual(
            [
                {key: value for key, value in row.items() if value is not None}
                for row in read["lines"]
            ],
            [
                {
                    "id": "a/1",
                    "scene": "a",
                    "speaker": "リリ",
                    "source": "一行目\n二行目",
                    "translation": 'He said, "Hi."\nThen left.',
                },
                {
                    "id": "a/2",
                    "scene": "a",
                    "kind": "ui",
                    "source": "メニュー",
                    "max_characters": 12,
                },
            ],
        )
        self.assertEqual(len(translation_file.units(read["lines"])), 2)

    def test_a_file_that_is_not_one_is_refused_with_what_to_fix(self):
        cases = [
            ("bad.csv", "id,source,transaltion\na,は,Yes\n", "Found transaltion"),
            (
                "twice.json",
                json.dumps(
                    {
                        "format": translation_file.FORMAT,
                        "version": 1,
                        "lines": [line("a", "は"), line("a", "ひ")],
                    }
                ),
                "unique: a",
            ),
            (
                "newer.json",
                json.dumps({"format": translation_file.FORMAT, "version": 2}),
                "newer DazedTL",
            ),
            ("other.json", json.dumps({"lines": []}), "not a translation file"),
        ]
        for name, text, problem in cases:
            with self.subTest(name):
                (self.root / name).write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, problem):
                    translation_file.read(self.root / name)
        units = self.root / "units.json"
        write_json(
            units,
            {"version": 1, "units": [{"id": "x", "scene": "s", "source": "は"}]},
        )
        self.assertEqual(translation_file.read(units)["lines"][0]["translation"], None)
        with self.assertRaisesRegex(ValueError, "this game translates Japanese"):
            translation_file.check_languages(
                {"source": "Japanese", "target": "Spanish"},
                {"source": "Japanese", "target": "English"},
            )


def _command(code, *parameters, indent=0, **extra):
    return {"code": code, "indent": indent, "parameters": list(parameters), **extra}


def _map(commands):
    return {
        "displayName": "",
        "events": [
            None,
            {"id": 1, "name": "EV001", "note": "", "pages": [{"list": commands}]},
        ],
    }


# A map as the game ships it: a named two-row message, a choice, and a
# message left untranslated.
ORIGINAL = _map(
    [
        _command(101, "", 0, 0, 2, "リリ"),
        _command(401, "こんにちは。"),
        _command(401, "元気？"),
        _command(102, ["はい", "いいえ"], 1, 0, 2, 0),
        _command(402, 0, "はい"),
        _command(0, indent=1),
        _command(402, 1, "いいえ"),
        _command(0, indent=1),
        _command(404),
        _command(101, "", 0, 0, 2, ""),
        _command(401, "さようなら。"),
        _command(0),
    ]
)
# The same map as Guided translated it: the first message joined into one
# row, so every command after it moved up one.
TRANSLATED = _map(
    [
        _command(101, "", 0, 0, 2, "Lili", _original="リリ"),
        _command(401, "Hello.\nHow are you?", _original="こんにちは。\n元気？"),
        _command(102, ["Yes", "No"], 1, 0, 2, 0, _original=["はい", "いいえ"]),
        _command(402, 0, "Yes"),
        _command(0, indent=1),
        _command(402, 1, "No"),
        _command(0, indent=1),
        _command(404),
        _command(101, "", 0, 0, 2, ""),
        _command(401, "さようなら。"),
        _command(0),
    ]
)


class _Inputs:
    """Guided's working copies of one game (guided_inputs), in a folder."""

    def __init__(self, folder, game, original):
        self.folder, self.game, self.original = folder, game, original

    def path(self, group, name):
        return self.folder / group / name

    def saved(self, group, name):
        return self.path(group, name).is_file()

    def newest(self, name):
        for group in ("translated", "files"):
            if self.saved(group, name):
                return self.path(group, name)
        return self.game / "data" / name

    def original_document(self, _name):
        return self.original

    def drawn_variables(self, _names):
        return frozenset()

    def prepare(self, names):
        for name in names:
            self.path("files", name).parent.mkdir(parents=True, exist_ok=True)
            self.path("files", name).write_bytes(
                (self.game / "data" / name).read_bytes()
            )


class _Guided:
    def __init__(self, game, folder):
        self.native = {"source": str(game), "phase1_comments": False}
        self.working = _Inputs(folder, game, ORIGINAL)
        self.backend = type(
            "Backend", (), {"phase_files": lambda _self, _native, phase: []}
        )()
        self.idled = 0

    def record(self, _project_id):
        return {}, self.native

    def inputs(self, _native):
        return self.working

    def supported_files(self, _native):
        return {"Map001.json"}

    def idle(self):
        self.idled += 1


class GuidedLineTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory

        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def game(self, name, document):
        game = self.root / name
        write_json(game / "data/Map001.json", document)
        return _Guided(game, self.root / (name + "-work"))

    def test_a_translated_and_an_untranslated_copy_name_their_lines_alike(self):
        from dazedtl.translation.guided_lines import GuidedLines

        mine = GuidedLines(self.game("mine", TRANSLATED), "mine", PAIR, True)
        theirs = GuidedLines(self.game("theirs", ORIGINAL), "theirs", PAIR, True)
        exported = {row["id"]: row for row in mine.lines()}
        head = "Map001.json#/events/1/pages/0/list"
        self.assertEqual(
            {identity: row["translation"] for identity, row in exported.items()},
            {
                f"{head}/0/parameters/4": "Lili",
                f"{head}/0": "Hello.\nHow are you?",
                f"{head}/3/parameters/0/0": "Yes",
                f"{head}/3/parameters/0/1": "No",
                f"{head}/9": None,
            },
        )
        self.assertEqual(exported[f"{head}/0"]["speaker"], "リリ")
        self.assertEqual(
            {row["id"]: row["source"] for row in theirs.lines()},
            {identity: row["source"] for identity, row in exported.items()},
        )
        # Their copy takes the translations into its working copy, as a run's
        # output, keeping each source as Guided does.
        current = {
            row["id"]: {"source": row["source"], "translation": row["translation"]}
            for row in theirs.lines()
        }
        write, summary = translation_file.matched(
            [{**row, "translation": row["translation"]} for row in exported.values()],
            current,
            theirs.problems,
        )
        self.assertEqual((summary["added"], summary["empty"]), (4, 1))
        # A line the file adds is written as Guided writes a reply's, its
        # corner brackets as quotes.
        write[f"{head}/9"] = "「Goodbye.」"
        theirs.save(write, "mine.json")
        working = read_json(self.root / "theirs-work/translated/Map001.json")
        commands = working["events"][1]["pages"][0]["list"]
        self.assertEqual(
            (commands[0]["parameters"][4], commands[0]["_original"]), ("Lili", "リリ")
        )
        self.assertEqual(
            [commands[1]["parameters"][0], commands[2]["parameters"][0]],
            ["Hello.", "How are you?"],
        )
        self.assertEqual(commands[1]["_original"], "こんにちは。\n元気？")
        self.assertEqual(commands[3]["_original"], ["はい", "いいえ"])
        self.assertEqual(commands[10]["parameters"][0], '"Goodbye."')
        self.assertEqual(
            {row["id"]: row["translation"] for row in theirs.lines()},
            {
                **{identity: row["translation"] for identity, row in exported.items()},
                f"{head}/9": '"Goodbye."',
            },
        )
