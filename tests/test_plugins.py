"""Protect exact edit scope, pristine lookup evidence and reviewed publication recovery."""

import json
import shutil
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.api.contracts.validation import check_response
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.foreign_work import ForeignWorkError
from dazedtl.plugins import PluginService, ruby
from dazedtl.plugins.documents import Documents, occurrences, replace_leaf, validate
from dazedtl.plugins.service import (
    event_script_keys,
    kept_literals,
    kept_settings,
    safe_name,
)
from dazedtl.projects.store import Projects
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.backups import snapshot, store_path
from dazedtl.translation.files import digest, read_json
from dazedtl.translation.operations import lifecycle_path


class PluginTests(unittest.TestCase):
    identity_keys = ("version", "kind", "projectId", "requestId", "binding")

    @classmethod
    def setUpClass(cls):
        # One parser for the class parses each identical fixture file once.
        cls.documents = Documents()

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "game"
        self.profile = self.root / "profile"
        self.prefix = "www/"
        encoded = json.dumps(
            [
                json.dumps({"Text": "目的地", "Key": "go"}, ensure_ascii=False),
                json.dumps({"Text": "目的地", "Key": "stop"}, ensure_ascii=False),
            ],
            ensure_ascii=False,
        )
        entries = [
            {
                "name": "PluginA",
                "status": True,
                "description": "説明",
                "parameters": {
                    "Label": "開始",
                    "List": encoded,
                    "Help": "Return to the title screen",
                },
            },
            {"name": "PluginB", "status": False, "description": "", "parameters": {}},
        ]
        self.write(
            "www/js/plugins.js",
            "var $plugins = " + json.dumps(entries, ensure_ascii=False) + ";\r\n",
        )
        self.write(
            "www/js/plugins/PluginA.js",
            "/* @default 既定\r\n * @desc 編集専用\r\n */\r\nconst caption = '開始';\r\ndrawText(caption);\r\nconst key = '薬草';\r\nlookup(key);\r\nconst label = `残り ${actor.name} 個`;\r\ndrawText(label);\r\nloadJSON('data/PluginN.json');\r\n",
        )
        self.write("www/js/plugins/PluginB.js", "drawText('隠れた文字');\r\n")
        write_json(
            self.game / "www/data/Items.json",
            [None, {"id": 1, "name": "薬草", "note": "<所持金消費:1>"}],
        )
        write_json(
            self.game / "www/data/Map001.json",
            {
                "events": [
                    {
                        "name": "イベント",
                        "note": "",
                        "list": [{"code": 401, "parameters": ["大きい"]}],
                    }
                ]
            },
        )
        write_json(
            self.game / "www/data/PluginN.json", {"caption": "収集", "id": "archive"}
        )
        write_bytes(self.game / ".dazedtl/glossary.txt", b"Terms\n")
        self.projects = Projects(self.profile)
        self.project = self.projects.open({"source": str(self.game), "engine": "MVMZ"})
        self.identity = self.project["id"]
        self.translation = SimpleNamespace(
            workspace=self.profile,
            idle=lambda _: None,
            clean_drafts=lambda _: None,
            writable=lambda _: None,
        )
        self.backend = SimpleNamespace(source=self.root / "engine")
        self.service = PluginService(
            self.projects, self.translation, self.backend, documents=self.documents
        )
        saved = snapshot(self.game, store_path(self.game), source_game=True)
        write_json(
            lifecycle_path(self.profile, self.identity),
            {"version": 1, "source_backup": saved},
        )

    def write(self, path, value):
        write_bytes(self.game / path, value.encode())

    def investigation(self, task=None, *, advance=True, only=None, kept=()):
        """Answers a copied task's investigation for every file, or `only`
        those, with the `kept` values found editor-only, and continues the
        task unless told not to."""
        task = task or self.service.action(self.identity, "plugin_task")
        request = read_json(task["request"])
        rows = []
        for asked in request["files"]:
            if only is not None and asked["path"] not in only:
                continue
            rows.append(
                {
                    "path": asked["path"],
                    "sourceHash": asked["sourceHash"],
                    "examined": True,
                    "evidence": "Complete recursive/source fixture audit",
                    "occurrences": [
                        {
                            "id": item["id"],
                            "disposition": "editor_only"
                            if item["value"] in kept
                            else "latent"
                            if item["latent"]
                            else "visible",
                            "safe": True,
                            "evidence": "Fixture drawText consumer checked; keys remain read-only",
                            "reason": "Player-visible static label",
                        }
                        for item in asked["occurrences"]
                    ],
                }
            )
        report = {key: request[key] for key in self.identity_keys}
        report.update(files=rows, complete=True, dependencies=[])
        write_json(request["report"], report)
        result = (
            self.service.continue_task(self.identity, request["requestId"])
            if advance
            else None
        )
        return request, report, result

    def candidate(self, path, targets):
        value = self.service.load(self.identity)
        row = value["files"][path]
        prepared = row["prepared"]
        raw = (self.game / prepared["original"]).read_bytes()
        parsed = self.service.documents.parse(
            [{"path": path, "source": raw.decode(), "kind": row["kind"]}]
        )[path]
        by_token = {}
        for item in row["occurrences"]:
            if item["id"] in targets:
                by_token.setdefault(item["token"], []).append(item)
        changes = []
        for index, items in by_token.items():
            literal = parsed["literals"][index]
            value = literal["value"]
            for item in items:
                value = replace_leaf(value, item["logical"], targets[item["id"]])
            if literal["kind"] == "default":
                replacement = value
            elif literal["raw"][0] == "`":
                replacement = "`" + value + "`"
            elif literal["raw"][0] == "'":
                replacement = (
                    "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
                )
            else:
                replacement = json.dumps(value, ensure_ascii=False)
            changes.append((literal["start"], literal["end"], replacement.encode()))
        for start, end, replacement in sorted(changes, reverse=True):
            raw = raw[:start] + replacement + raw[end:]
        write_bytes(self.game / prepared["candidate"], raw)
        return raw

    def translate(self, task, only=None):
        """Translates a translation request's files, or `only` those, into
        their working copies and saves the report."""
        request = read_json(task["request"])
        rows = []
        for asked in request["files"]:
            if only is not None and asked["path"] not in only:
                continue
            targets = {
                item["id"]: item["value"]
                .replace("開始", "Start")
                .replace("目的地", "Destination")
                .replace("残り", "Remaining")
                .replace(" 個", " units")
                for item in asked["occurrences"]
            }
            raw = self.candidate(asked["path"], targets)
            rows.append(
                {
                    "path": asked["path"],
                    "sourceHash": asked["sourceHash"],
                    "candidateHash": digest(raw),
                    "targets": targets,
                    "evidence": "Synthetic Japanese/English review; runtime playtest not performed",
                }
            )
        report = {key: request[key] for key in self.identity_keys}
        report.update(files=rows, complete=True)
        write_json(request["report"], report)
        return request, report

    def translated(self):
        _request, _report, task = self.investigation()
        self.assertEqual(task["stage"], "translation")
        request, report = self.translate(task)
        done = self.service.continue_task(self.identity, request["requestId"])
        self.assertEqual(done["stage"], "complete")
        return request, report

    def status(self, path):
        value = self.service.load(self.identity)
        return self.service.row_status(value, value["files"][path])

    def test_recursive_parameters_pristine_keys_and_retained_hidden_scope(self):
        # Already translated runtime DB must not erase original lookup guards.
        write_json(
            self.game / "www/data/Items.json",
            [None, {"id": 1, "name": "Herb", "note": "<所持金消費:1>"}],
        )
        self.write("www/js/plugins/Keys.js", "lookup('薬草');\r\n")
        before = (self.game / "www/js/plugins.js").read_bytes()
        request, _report, _task = self.investigation()
        value = self.service.load(self.identity)
        item = next(
            item
            for item in value["files"]["www/js/plugins/PluginA.js"]["occurrences"]
            if item["value"] == "薬草"
        )
        self.assertTrue(item["protected"])
        asked = {item["id"] for row in request["files"] for item in row["occurrences"]}
        self.assertNotIn(item["id"], asked)
        # A file holding only protected text leaves the assistant nothing to decide.
        self.assertNotIn(
            "www/js/plugins/Keys.js", [row["path"] for row in request["files"]]
        )
        self.assertEqual(self.status("www/js/plugins/Keys.js"), "none")
        labels = [
            item
            for item in value["files"]["www/js/plugins.js"]["occurrences"]
            if item["value"] == "目的地"
        ]
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(item["finding"]["safe"] for item in labels))
        # Confirmed active leaves are included without anyone choosing them;
        # the disabled plugin's text is not.
        self.assertEqual(self.service.state(self.identity)["counts"]["selected"], 4)
        self.assertEqual((self.game / "www/js/plugins.js").read_bytes(), before)
        restarted = PluginService(
            self.projects,
            self.translation,
            self.backend,
            documents=self.service.documents,
        )
        self.assertEqual(restarted.state(self.identity)["counts"]["selected"], 4)
        self.assertNotIn(
            "www/data/Map001.json", [row["path"] for row in request["files"]]
        )

    def test_repeated_plugin_entries_follow_the_games_loader(self):
        # Games list empty divider plugins many times. The game loads a
        # plugin's first enabled entry and skips later ones.
        divider = {"name": "----", "status": True, "description": "", "parameters": {}}
        entries = [
            divider,
            {"name": "PluginB", "status": False, "description": "", "parameters": {}},
            {"name": "PluginA", "status": True, "parameters": {"Label": "開始"}},
            {"name": "PluginA", "status": True, "parameters": {"Label": "二度目"}},
            divider,
            {"name": "PluginB", "status": True, "description": "", "parameters": {}},
        ]
        self.write(
            "www/js/plugins.js",
            "var $plugins = " + json.dumps(entries, ensure_ascii=False) + ";\r\n",
        )
        self.write("www/js/plugins/----.js", "")
        self.service.action(self.identity, "plugin_task")
        files = self.service.load(self.identity)["files"]
        self.assertTrue(files["www/js/plugins/PluginB.js"]["enabled"])
        self.assertEqual(
            {
                item["value"]: item["latent"]
                for item in files["www/js/plugins.js"]["occurrences"]
            },
            {"開始": False, "二度目": True},
        )
        self.assertEqual(self.status("www/js/plugins/----.js"), "none")
        # MZ compares file names, so a second folder's copy never loads.
        self.write("www/js/rmmz_core.js", "")
        self.write("www/js/plugins/Other/PluginB.js", "drawText('別');\r\n")
        entries.append({**entries[-1], "name": "Other/PluginB"})
        self.write(
            "www/js/plugins.js",
            "var $plugins = " + json.dumps(entries, ensure_ascii=False) + ";\r\n",
        )
        _prefix, rows, _config = self.service.inventory(self.identity)
        self.assertTrue(rows["www/js/plugins/PluginB.js"]["enabled"])
        self.assertFalse(rows["www/js/plugins/Other/PluginB.js"]["enabled"])

    def test_undecided_text_stays_with_the_assistant_until_settled(self):
        request, report, _ = self.investigation(advance=False)
        answers = {row["path"]: row for row in report["files"]}
        uncertain = next(
            item
            for item in answers["www/js/plugins/PluginA.js"]["occurrences"]
            if item["disposition"] == "visible"
        )
        uncertain.update(
            disposition="unresolved", safe=False, reason="Display use is ambiguous"
        )
        omitted = answers["www/js/plugins.js"]["occurrences"].pop(0)
        write_json(request["report"], report)
        followup = self.service.continue_task(self.identity, request["requestId"])
        # Accepted findings stay; only the undecided text is asked again.
        self.assertEqual(followup["stage"], "investigation")
        self.assertEqual(
            {
                (row["path"], item["id"])
                for row in read_json(followup["request"])["files"]
                for item in row["occurrences"]
            },
            {
                ("www/js/plugins/PluginA.js", uncertain["id"]),
                ("www/js/plugins.js", omitted["id"]),
            },
        )
        selection = self.service.load(self.identity)["selection"]
        self.assertTrue({uncertain["id"], omitted["id"]}.isdisjoint(selection))
        self.assertEqual(len(selection), 2)
        state = self.service.state(self.identity)
        # Real rows and a bound request must match what the renderer validates.
        check_response("plugins_state", state)
        self.assertTrue(state["awaiting"])
        self.assertEqual(state["counts"]["investigated"], state["counts"]["files"] - 2)
        # Copying the task again hands out the same open request.
        self.assertEqual(
            self.service.action(self.identity, "plugin_task")["requestId"],
            followup["requestId"],
        )
        runtime = {
            path: (self.game / path).read_bytes()
            for path in self.service.load(self.identity)["files"]
        }
        _, _, task = self.investigation(followup)
        self.assertEqual(task["stage"], "translation")
        self.assertEqual(len(self.service.load(self.identity)["selection"]), 4)
        self.assertTrue(
            all((self.game / path).read_bytes() == raw for path, raw in runtime.items())
        )
        self.assertTrue(
            all(
                (self.game / row["candidate"]).is_file()
                for row in read_json(task["request"])["files"]
            )
        )
        # A retained path must not advertise a deleted copy as available to the agent.
        (self.game / read_json(task["request"])["files"][0]["candidate"]).unlink()
        with self.assertRaisesRegex(ValueError, "missing files"):
            self.service.action(self.identity, "plugin_task")

    def test_kept_text_the_playtest_saw_drawn_is_decided_again_once(self):
        _request, _report, task = self.investigation(kept=("開始",))
        self.assertEqual(task["stage"], "translation")
        self.service.seen = lambda _project: {
            "report": "r1",
            "texts": [{"text": "開始", "where": "Seen on Scene_Title"}],
        }
        again = self.service.action(self.identity, "plugin_task")
        self.assertEqual(again["stage"], "investigation")
        asked = [
            item
            for row in read_json(again["request"])["files"]
            for item in row["occurrences"]
        ]
        self.assertTrue(asked)
        self.assertTrue(
            all(item["value"] == "開始" and item["seen"] for item in asked), asked
        )
        self.assertIn("drawn on screen", again["text"])
        # Kept again with the evidence, it is not asked a third time.
        _request, _report, task = self.investigation(again, kept=("開始",))
        self.assertEqual(task["stage"], "translation")
        request, _report = self.translate(task)
        self.service.continue_task(self.identity, request["requestId"])
        # The final check's assistant gets only what is left, never Copy's
        # recheck of every decision.
        left = self.service.action(self.identity, "plugin_task", {"recheck": False})
        self.assertEqual(left["stage"], "complete")
        self.assertNotIn("request", left)

    def test_foreign_duplicate_traversal_and_stale_reports_are_atomic(self):
        # MZ plugin subfolders are valid names; traversal and empty parts are not.
        self.assertEqual(safe_name("Author/Plugin"), "Author/Plugin")
        for name in ("../Plugin", "Author/../Plugin", "Author//Plugin", "./Plugin"):
            with self.assertRaises(ValueError):
                safe_name(name)
        with self.assertRaisesRegex(ValueError, "Copy a plugin task"):
            self.service.continue_task(self.identity, "0" * 32)
        request, report, _ = self.investigation(advance=False)
        prior = deepcopy(self.service.load(self.identity))
        for mutate in (
            lambda r: r.update(projectId="foreign"),
            lambda r: r["files"].append(deepcopy(r["files"][0])),
            lambda r: r["files"][0].update(path="../outside.js"),
        ):
            invalid = deepcopy(report)
            mutate(invalid)
            write_json(request["report"], invalid)
            with self.assertRaises(ValueError):
                self.service.continue_task(self.identity, request["requestId"])
            self.assertEqual(self.service.load(self.identity), prior)
        changed = deepcopy(prior)
        changed["requests"]["investigation"]["binding"] = "forged"
        self.service.save(self.identity, changed)
        write_json(request["path"], changed["requests"]["investigation"])
        with self.assertRaisesRegex(ValueError, "scoped request changed"):
            self.service.continue_task(self.identity, request["requestId"])
        self.service.save(self.identity, prior)
        write_json(request["path"], request)
        write_json(request["report"], report)
        self.write("www/js/plugins/PluginA.js", "drawText('変更');")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            self.service.continue_task(self.identity, request["requestId"])

    def test_unrelated_code_interpolation_controls_and_extra_files_are_rejected(self):
        request, report = self.translated()
        path = "www/js/plugins/PluginA.js"
        row = next(row for row in report["files"] if row["path"] == path)
        candidate = (
            self.game
            / self.service.load(self.identity)["files"][path]["prepared"]["candidate"]
        )
        good = candidate.read_bytes()
        current = request
        for raw in (
            good + b"\nmalicious();",
            good.replace(b"actor.name", b"actor.secret"),
            good.replace(b"lookup(key)", b"lookup('changed')"),
        ):
            write_bytes(candidate, raw)
            row["candidateHash"] = digest(raw)
            report = {key: current[key] for key in self.identity_keys}
            report.update(files=[row])
            write_json(current["report"], report)
            # A failed check hands the file back for repair, with the reason.
            again = self.service.continue_task(self.identity, current["requestId"])
            self.assertIn("Failed checks", again["message"])
            current = read_json(again["request"])
            [asked] = current["files"]
            self.assertEqual(asked["path"], path)
            self.assertTrue(asked["failedCheck"])
            result = self.service.load(self.identity)["files"][path]["result"]
            self.assertEqual(result["status"], "needs_revision")
            self.assertFalse(result["checks"])
        forged = self.service.load(self.identity)
        forged["files"][path]["result"]["status"] = "ready"
        self.service.save(self.identity, forged)
        # A result that failed its checks stays out of the game whatever its
        # status says.
        applied = self.service.action(self.identity, "apply")
        self.assertEqual([item["path"] for item in applied["blocked"]], [path])
        self.assertNotIn(path, [item["path"] for item in applied["receipt"]["files"]])
        write_bytes(candidate, good)
        row["candidateHash"] = digest(good)
        report["files"].append({"path": "www/js/plugins/New.js", "sourceHash": "x"})
        write_json(current["report"], report)
        with self.assertRaisesRegex(ValueError, "out-of-scope"):
            self.service.continue_task(self.identity, current["requestId"])

    def test_apply_checks_rolls_back_and_restores_after_review(self):
        _, _, task = self.investigation(kept={"目的地"})
        first = read_json(task["request"])
        paths = [row["path"] for row in first["files"]]
        # Files translated under an earlier request stay publishable while a
        # later request asks only for the rest.
        self.translate(task, only=paths[:1])
        rest = self.service.continue_task(self.identity, first["requestId"])
        self.assertNotEqual(rest["requestId"], first["requestId"])
        self.assertEqual(
            [row["path"] for row in read_json(rest["request"])["files"]], paths[1:]
        )
        request, _report = self.translate(rest)
        self.assertEqual(
            self.service.continue_task(self.identity, request["requestId"])["stage"],
            "complete",
        )
        before = {path: (self.game / path).read_bytes() for path in paths}
        self.assertEqual(self.service.state(self.identity)["counts"]["ready"], 2)
        # Text QA leaves out the settings the assistant keeps in Japanese, by
        # plugin, parameter path and the value it decided on.
        kept = [
            {"plugin": "PluginA", "path": ["List", index, "Text"], "value": "目的地"}
            for index in (0, 1)
        ]
        self.assertEqual(kept_settings(self.game), kept)
        # The playtest leaves out strings in plugin code kept the same way, by
        # file, line and value; text still to translate stays in.
        code = "www/js/plugins/PluginA.js"
        literals = [
            {"file": code, "line": 1, "kind": "default", "value": "既定"},
            {"file": code, "line": 4, "kind": "literal", "value": "開始"},
            {"file": code, "line": 6, "kind": "literal", "value": "薬草"},
            {
                "file": "www/js/plugins/PluginB.js",
                "line": 1,
                "kind": "literal",
                "value": "隠れた文字",
            },
        ]
        self.assertEqual(kept_literals(self.game), literals)
        # A game edit under a translation not applied yet goes back to the
        # assistant, along with what it kept; once applied, later edits are
        # expected.
        edited = before[paths[0]] + b"\n// edited"
        write_bytes(self.game / paths[0], edited)
        counts = self.service.state(self.identity)["counts"]
        self.assertLess(counts["investigated"], counts["files"])
        self.assertEqual(kept_settings(self.game), [])
        write_bytes(self.game / paths[0], before[paths[0]])
        write_bytes(self.game / code, before[code] + b"\n// edited")
        self.assertEqual(kept_literals(self.game), literals[3:])
        write_bytes(self.game / code, before[code])
        # Apply checks each file again; a working copy changed after its
        # checks stays out of the game.
        saved = self.service.load(self.identity)["files"]
        candidates = {
            candidate: candidate.read_bytes()
            for candidate in (
                self.game / saved[path]["prepared"]["candidate"] for path in paths
            )
        }
        for candidate, raw in candidates.items():
            write_bytes(candidate, raw + b" ")
        with self.assertRaisesRegex(
            ValueError, "Nothing was applied.*Working copy changed"
        ):
            self.service.action(self.identity, "apply")
        self.assertTrue(
            all((self.game / path).read_bytes() == raw for path, raw in before.items())
        )
        for candidate, raw in candidates.items():
            write_bytes(candidate, raw)
        original_publish = self.service._publish_file
        calls = []

        def fail(root, path, content):
            calls.append(path)
            original_publish(root, path, content)
            if len(calls) == 2:
                raise OSError("Injected second publication failure after its write")

        with (
            patch.object(self.service, "_publish_file", side_effect=fail),
            self.assertRaisesRegex(ValueError, "rollback attempted"),
        ):
            self.service.action(self.identity, "apply")
        # A game update's stopped merge holds every write back: one written
        # then left Versions unable to cancel the update.
        with (
            patch.object(
                self.translation, "writable", side_effect=ValueError("unfinished Git")
            ),
            self.assertRaisesRegex(ValueError, "unfinished Git"),
        ):
            self.service.action(self.identity, "apply")
        self.assertTrue(
            all((self.game / path).read_bytes() == raw for path, raw in before.items())
        )
        result = self.service.action(self.identity, "apply")
        # Receipts keep recovery-only fields away from the renderer.
        check_response("plugins_action", result)
        self.assertEqual(result["blocked"], [])
        self.assertTrue(result["receipt"]["restorable"])
        self.assertEqual(result["state"]["counts"]["applied"], 2)
        # Applied files are done, not left unchanged by a later apply.
        with self.assertRaisesRegex(ValueError, "No plugin file is ready"):
            self.service.action(self.identity, "apply")
        applied = (self.game / paths[0]).read_bytes()
        write_bytes(self.game / paths[0], applied + b"\n// edited")
        counts = self.service.state(self.identity)["counts"]
        self.assertEqual(
            (counts["applied"], counts["investigated"]), (2, counts["files"])
        )
        self.assertEqual(kept_settings(self.game), kept)
        write_bytes(self.game / paths[0], applied)
        settled = (self.game / code).read_bytes()
        write_bytes(self.game / code, settled + b"\n// edited")
        self.assertEqual(kept_literals(self.game), literals)
        write_bytes(self.game / code, settled)
        saved = self.service.load(self.identity)
        original_saved = deepcopy(saved)
        saved["receipts"][-1]["files"][0]["backup"] = saved["files"][paths[0]][
            "prepared"
        ]["candidate"]
        self.service.save(self.identity, saved)
        with self.assertRaisesRegex(ValueError, "exact approved publication"):
            self.service.action(
                self.identity, "preview_restore", {"receipt": result["receipt"]["id"]}
            )
        self.service.save(self.identity, original_saved)
        restore = self.service.action(
            self.identity, "preview_restore", {"receipt": result["receipt"]["id"]}
        )["preview"]
        check_response("plugins_action", {"preview": restore})
        # A game file edited after the restore was reviewed is not overwritten.
        write_bytes(self.game / paths[0], applied + b"\n// edited")
        with self.assertRaisesRegex(ValueError, "changed after review"):
            self.service.action(self.identity, "restore", {"token": restore["token"]})
        write_bytes(self.game / paths[0], applied)
        restore = self.service.action(
            self.identity, "preview_restore", {"receipt": result["receipt"]["id"]}
        )["preview"]
        self.service.action(self.identity, "restore", {"token": restore["token"]})
        with self.assertRaisesRegex(ValueError, "already used"):
            self.service.action(self.identity, "restore", {"token": restore["token"]})
        self.assertTrue(
            all((self.game / path).read_bytes() == raw for path, raw in before.items())
        )
        # A restored application no longer offers another restore, and its
        # checked translations wait to be applied again.
        state = self.service.state(self.identity)
        self.assertFalse(any(receipt["restorable"] for receipt in state["receipts"]))
        self.assertEqual(state["counts"]["ready"], 2)
        self.assertEqual(self.service.action(self.identity, "apply")["completed"], 2)

    def test_labels_text_qa_found_too_long_hold_the_task_until_applied(self):
        # QA can't write plugin files, so its squeezed plugin labels must
        # reach the assistant here, keep the task open and go into the game
        # only through a checked copy.
        self.translated()
        self.service.action(self.identity, "apply")
        capture = lambda task, *texts: (
            lambda _project: {
                "task": task,
                "labels": [
                    {
                        "text": text,
                        "title": "Menu",
                        "capture": "/qa/menu.png",
                        "squeezed": 0.75,
                    }
                    for text in texts
                ],
            }
        )
        # "Start" was translated here, the help text was English already and
        # a label in no plugin file stays with QA.
        self.service.labels = capture(
            "qa-1", "Start", "Return to the title screen", "Status Effects"
        )
        state = self.service.state(self.identity)
        self.assertEqual(state["counts"]["labels"], 2)
        self.assertEqual(
            [row["state"] for row in state["labels"]],
            ["waiting", "waiting", "elsewhere"],
        )
        task = self.service.action(self.identity, "plugin_task")
        self.assertEqual(task["stage"], "fit")
        request = read_json(task["request"])
        found = {row["path"]: row for row in request["files"]}
        config = found["www/js/plugins.js"]
        go = next(item for item in config["candidates"] if item["value"] == "Start")
        help_text = next(
            item for item in config["candidates"] if item["value"].startswith("Return")
        )
        raw = (self.game / config["candidate"]).read_bytes()
        literal = self.service.documents.parse(
            [{"path": "x", "source": raw.decode(), "kind": "parameters"}]
        )["x"]["literals"][go["token"]]
        edited = raw[: literal["start"]] + b'"Go"' + raw[literal["end"] :]
        write_bytes(self.game / config["candidate"], edited)
        decisions = [
            {"text": "Start", "decision": "shortened", "evidence": "Menu capture"},
            {
                "text": "Return to the title screen",
                "decision": "kept",
                "evidence": "Menu capture",
                "reason": "Its window scrolls the help text",
            },
        ]
        answer = {
            "path": config["path"],
            "sourceHash": config["sourceHash"],
            "candidateHash": digest(edited),
            "evidence": "Shorter menu command",
            "targets": {go["id"]: "Go", help_text["id"]: "Back"},
        }
        report = {key: request[key] for key in self.identity_keys}
        report.update(labels=decisions, files=[answer], complete=True)
        # Text for a label the assistant kept is refused.
        write_json(request["report"], report)
        with self.assertRaises(ValueError):
            self.service.continue_task(self.identity, request["requestId"])
        answer["targets"] = {go["id"]: "Go"}
        write_json(request["report"], report)
        # A shorter label counts once the game shows it fitting, on its
        # screen captured with the copy served in place of the game's file.
        held = read_json(
            self.service.continue_task(self.identity, request["requestId"])["request"]
        )
        self.assertIn("plugins --capture", held["files"][0]["failedCheck"])
        plans = []
        self.service.capture_labels = lambda _project, plan: plans.append(plan)
        self.service.capture(self.identity, start=True)
        (plan,) = plans
        self.assertEqual([row["serve"] for row in plan["files"]], ["js/plugins.js"])
        self.assertEqual(
            [(row["text"], row["shows"]) for row in plan["labels"]], [("Start", ["Go"])]
        )
        self.service.captured = lambda _project: {
            "report": "check",
            "finished_at": "now",
            "files": {row["path"]: row["hash"] for row in plan["files"]},
            "labels": [
                {
                    "text": "Start",
                    "title": "Menu",
                    "shows": ["Go"],
                    "fits": True,
                    "note": "The game draws Go in full.",
                    "capture": "/check/menu.png",
                }
            ],
        }
        view = self.service.capture(self.identity)
        check_response("plugins_capture", view)
        self.assertTrue(view["current"])
        report.update(
            {key: held[key] for key in self.identity_keys}, labels=decisions[:1]
        )
        write_json(held["report"], report)
        done = self.service.continue_task(self.identity, held["requestId"])
        self.assertEqual(done["stage"], "complete")
        self.assertEqual(
            self.service.load(self.identity)["labels"]["Start"]["capture"],
            "/check/menu.png",
        )
        state = self.service.state(self.identity)
        self.assertEqual(
            [row["state"] for row in state["labels"]], ["ready", "kept", "elsewhere"]
        )
        self.assertEqual(
            (
                state["counts"]["labels"],
                state["counts"]["ready"],
                state["counts"]["shortened"],
            ),
            (0, 1, 1),
        )
        self.assertNotIn(b'"Go"', (self.game / "www/js/plugins.js").read_bytes())
        self.service.action(self.identity, "apply")
        self.assertIn(b'"Go"', (self.game / "www/js/plugins.js").read_bytes())
        self.assertEqual(self.status("www/js/plugins.js"), "applied")
        restarted = PluginService(
            self.projects, self.translation, self.backend, documents=self.documents
        )
        restarted.labels = self.service.labels
        self.assertEqual(
            [row["state"] for row in restarted.state(self.identity)["labels"]],
            ["applied", "kept", "elsewhere"],
        )
        # A newer capture that finds the shorter text still too long hands it
        # out again; a kept label stays kept.
        restarted.labels = capture("qa-2", "Go", "Return to the title screen")
        self.assertEqual(
            [row["state"] for row in restarted.state(self.identity)["labels"]],
            ["waiting", "kept"],
        )
        # The game draws an applied file's own bytes, so a label an edit made
        # after the apply put there is found there, not in the working copy.
        game = self.game / "www/js/plugins.js"
        write_bytes(game, game.read_bytes().replace(b'"Go"', b'"Begin game"'))
        restarted.labels = capture("qa-3", "Begin game")
        self.assertEqual(
            [row["state"] for row in restarted.state(self.identity)["labels"]],
            ["waiting"],
        )

    def test_partial_results_are_handed_back_until_complete(self):
        _, _, task = self.investigation()
        request, report = self.translate(task)
        answer = report["files"][0]
        answer["targets"].pop(next(iter(answer["targets"])))
        # A changed value omitted from the report is not accepted as a partial result.
        write_json(request["report"], report)
        again = self.service.continue_task(self.identity, request["requestId"])
        self.assertIn("Failed checks", again["message"])
        self.assertEqual(
            [row["path"] for row in read_json(again["request"])["files"]],
            [answer["path"]],
        )
        self.assertEqual(self.status(answer["path"]), "translate")
        self.assertEqual(self.service.state(self.identity)["counts"]["translated"], 1)
        # Inactive and default-only text never joins the translation.
        latent = {
            item["id"]
            for row in self.service.load(self.identity)["files"].values()
            for item in row["occurrences"]
            if item["latent"]
        }
        self.assertTrue(latent)
        self.assertTrue(
            latent.isdisjoint(
                item["id"]
                for row in read_json(request["path"])["files"]
                for item in row["occurrences"]
            )
        )

    def test_literal_byte_offsets_escaped_tokens_and_same_prefix_lookup(self):
        original = (
            'const emoji="😀"; drawText("所持金\\n\\\\C[1] 日本語");\r\n'.encode()
        )
        candidate = original.replace("所持金".encode(), b"Money").replace(
            "日本語".encode(), b"Japanese"
        )
        parser = Documents()
        parsed = parser.parse(
            [
                {"path": "a.js", "source": original.decode(), "kind": "source"},
                {"path": "b.js", "source": candidate.decode(), "kind": "source"},
            ]
        )
        approved = occurrences("a.js", original, parsed["a.js"])
        targets = {approved[0]["id"]: "Money\n\\C[1] Japanese"}
        self.assertTrue(
            validate(
                original, candidate, parsed["a.js"], parsed["b.js"], approved, targets
            )["controlTokens"]
        )
        changed = candidate.replace(b"\\n", b"")
        p = parser.parse(
            [{"path": "b.js", "source": changed.decode(), "kind": "source"}]
        )["b.js"]
        with self.assertRaises(ValueError):
            validate(
                original,
                changed,
                parsed["a.js"],
                p,
                approved,
                {approved[0]["id"]: "Money\\C[1] Japanese"},
            )
        # An unchanged version never starts Node again, and each caller
        # changes only its own copy.
        parsed["a.js"]["literals"].clear()
        with patch(
            "dazedtl.plugins.documents.subprocess.run",
            side_effect=AssertionError("An unchanged version started Node again."),
        ):
            again = parser.parse(
                [{"path": "a.js", "source": original.decode(), "kind": "source"}]
            )["a.js"]
        self.assertTrue(again["literals"])
        context = self.service.original_context(self.identity, "www/")
        self.assertIn("所持金消費", context["keys"])
        self.assertNotIn("所持金", context["keys"])
        self.assertNotIn("大きい", context["keys"])

    def test_only_a_leading_tag_the_code_matches_may_stay_japanese(self):
        original = (
            'if (s.startsWith("ア:")) say(s.slice(2));\nplay(["ア:むね", "地:風"]);\n'
        )
        candidate = original.replace("むね", "Chest")
        parsed = Documents().parse(
            [
                {"path": "a.js", "source": original, "kind": "source"},
                {"path": "b.js", "source": candidate, "kind": "source"},
                {
                    "path": "c.js",
                    "source": candidate.replace("風", "Wind"),
                    "kind": "source",
                },
            ]
        )
        tagged, plain = [
            row
            for row in occurrences("a.js", original.encode(), parsed["a.js"])
            if row["value"] != "ア:"
        ]
        targets = {tagged["id"]: "ア:Chest"}
        self.assertTrue(
            validate(
                original.encode(),
                candidate.encode(),
                parsed["a.js"],
                parsed["b.js"],
                [tagged],
                targets,
            )
        )
        # No code reads 地:, so it is untranslated text rather than a tag.
        with self.assertRaisesRegex(ValueError, "still contains Japanese"):
            validate(
                original.encode(),
                candidate.replace("風", "Wind").encode(),
                parsed["a.js"],
                parsed["c.js"],
                [tagged, plain],
                {**targets, plain["id"]: "地:Wind"},
            )

    def test_missing_originals_and_dynamic_configuration_never_authorize_edits(self):
        lifecycle_path(self.profile, self.identity).unlink()
        # Without the original Japanese, lookup values cannot be protected.
        with self.assertRaisesRegex(ValueError, "Back up the original"):
            self.service.action(self.identity, "plugin_task")
        self.assertEqual(self.service.state(self.identity)["counts"]["selected"], 0)
        self.write("www/js/plugins.js", "var $plugins = dangerous();")
        with self.assertRaisesRegex(ValueError, "static literal"):
            self.service.action(self.identity, "plugin_task")
        malformed = Documents().parse(
            [{"path": "bad.json", "source": '{"Text": "日本語"', "kind": "json"}]
        )["bad.json"]
        self.assertTrue(malformed["issues"])
        self.assertEqual(malformed["literals"], [])
        from dazedtl.plugins.documents import leaves

        # Data that looks like JSON but does not decode stays one leaf the app
        # protects, without blocking the rest of its file; scripts such as
        # `[{}];` look like that too.
        self.assertEqual(
            list(leaves('{"Text": "日本語"')), [([], '{"Text": "日本語"', True)]
        )
        self.assertEqual(
            list(leaves('{"DataScript": "[{}];", "Text": "開始"}')),
            [
                (["$decode", "DataScript"], "[{}];", True),
                (["$decode", "Text"], "開始", False),
            ],
        )

    def test_copying_a_current_plugin_task_again_keeps_its_request(self):
        # A second copy must not orphan the saved report of an unchanged task.
        first = self.service.action(self.identity, "plugin_task")["requestId"]
        again = self.service.action(self.identity, "plugin_task")["requestId"]
        self.assertEqual(again, first)
        self.write("www/js/plugins/PluginA.js", "drawText('残り');")
        changed = self.service.action(self.identity, "plugin_task")["requestId"]
        self.assertNotEqual(changed, first)
        # Once nothing is left, a copy asks the assistant to recheck every
        # decision, listing its earlier findings.
        self.translated()
        recheck = read_json(
            self.service.action(self.identity, "plugin_task")["request"]
        )
        self.assertEqual(recheck["kind"], "investigation")
        self.assertTrue(
            all(
                "finding" in item
                for row in recheck["files"]
                for item in row["occurrences"]
            )
        )
        self.assertIn("recheck", recheck["instructions"])

    def test_unreadable_plugin_files_can_be_kept_and_return_when_fixed(self):
        # A file the app cannot read must not hold up the task for good, and a
        # fixed or removed file must not stay reported as unreadable.
        path = "www/js/plugins/PluginB.js"
        source = "drawText('隠れた文字');\r\n"
        write_bytes(self.game / path, source.encode("shift_jis"))
        self.translated()
        unreadable = {"path": path, "issue": "Plugin files must be UTF-8 text."}
        state = self.service.state(self.identity)
        self.assertEqual(state["unreadable"], [{**unreadable, "kept": False}])
        self.assertEqual(state["counts"]["investigated"], state["counts"]["files"])
        with self.assertRaisesRegex(ValueError, "cannot read"):
            self.service.action(
                self.identity,
                "keep_unreadable",
                {"paths": ["www/js/plugins/PluginA.js"]},
            )
        state = self.service.action(
            self.identity, "keep_unreadable", {"paths": [path]}
        )["state"]
        self.assertEqual(state["unreadable"], [{**unreadable, "kept": True}])
        # Fixed, it counts for the assistant again instead of dropping out.
        self.write(path, source)
        state = self.service.state(self.identity)
        self.assertEqual(state["unreadable"], [])
        self.assertLess(state["counts"]["investigated"], state["counts"]["files"])
        # Removed, it has nothing to translate, and the next scan drops it.
        (self.game / path).unlink()
        self.assertEqual(self.service.state(self.identity)["unreadable"], [])
        self.service.action(self.identity, "plugin_task")
        self.assertNotIn(path, self.service.load(self.identity)["files"])

    def test_a_scan_saved_under_older_rules_is_read_again(self):
        # A problem an earlier version reported must not linger and invite
        # keeping a readable file unchanged.
        self.translated()
        value = self.service.load(self.identity)
        value["files"]["www/js/plugins.js"]["issue"] = "An older complaint."
        value["scanRules"] = 1
        self.service.save(self.identity, value)
        self.assertEqual(self.service.state(self.identity)["unreadable"], [])

    def test_explicit_loaded_json_needs_new_investigation_then_exact_leaf_checks(self):
        task = self.service.action(self.identity, "plugin_task")
        request, report, _ = self.investigation(task, advance=False)
        loader = next(
            row for row in request["files"] if row["path"].endswith("/PluginA.js")
        )
        with self.assertRaisesRegex(ValueError, "replaced"):
            self.service.continue_task(self.identity, "foreign-request")
        literal = loader["loaderLiterals"][0]
        report["dependencies"] = [
            {
                "path": literal["value"],
                "sourceFile": loader["path"],
                "literalId": literal["id"],
                "evidence": "Exact static fixture loadJSON call",
            }
        ]
        write_json(request["report"], report)
        followup = self.service.continue_task(self.identity, request["requestId"])
        self.assertEqual(followup["stage"], "investigation")
        self.assertEqual(
            [row["path"] for row in read_json(followup["request"])["files"]],
            ["www/data/PluginN.json"],
        )
        # A lost reply returns the existing successor, without creating another request.
        self.assertEqual(
            self.service.continue_task(self.identity, request["requestId"])[
                "requestId"
            ],
            followup["requestId"],
        )
        _, _, result = self.investigation(followup)
        self.assertEqual(result["stage"], "translation")
        path = "www/data/PluginN.json"
        row = self.service.load(self.identity)["files"][path]
        request = read_json(result["request"])
        others = [item["path"] for item in request["files"] if item["path"] != path]
        _, report = self.translate(result, only=others)
        asked = next(item for item in request["files"] if item["path"] == path)
        targets = {item["id"]: "Archive" for item in asked["occurrences"]}
        candidate = self.candidate(path, targets)
        answer = {
            "path": path,
            "sourceHash": asked["sourceHash"],
            "candidateHash": digest(candidate),
            "targets": targets,
            "evidence": "Synthetic fixture display field",
        }
        report["files"].append(answer)
        write_json(request["report"], report)
        done = self.service.continue_task(self.identity, request["requestId"])
        self.assertEqual(done["stage"], "complete")
        self.assertEqual(self.status(path), "ready")
        self.assertEqual(self.service.state(self.identity)["counts"]["applied"], 0)
        altered = candidate.replace(b'"id"', b'"renamed"')
        write_bytes(self.game / row["prepared"]["candidate"], altered)
        answer["candidateHash"] = digest(altered)
        write_json(request["report"], report)
        current = read_json(
            self.service.continue_task(self.identity, request["requestId"])["request"]
        )
        self.assertEqual([item["path"] for item in current["files"]], [path])
        self.assertEqual(self.status(path), "translate")
        write_bytes(self.game / row["prepared"]["candidate"], candidate)
        answer["candidateHash"] = digest(candidate)
        report = {key: current[key] for key in self.identity_keys}
        report.update(files=[answer])
        write_json(current["report"], report)
        write_bytes(self.game / row["prepared"]["copyRoot"] / "New.js", b"malicious();")
        with self.assertRaisesRegex(ValueError, "New or missing"):
            self.service.continue_task(self.identity, current["requestId"])
        # Only the request before the active one counts as a lost reply.
        with self.assertRaisesRegex(ValueError, "replaced"):
            self.service.continue_task(self.identity, followup["requestId"])

    def test_another_projects_work_is_taken_over_on_request_or_set_aside(self):
        # A copied game, a new profile or a reinstall opens this folder as a
        # new project; its saved work waits for the user's choice.
        request, _report = self.translated()
        original = {
            row["path"]: (self.game / row["path"]).read_bytes()
            for row in request["files"]
        }
        receipt = self.service.action(self.identity, "apply")["receipt"]["id"]

        def reopened(name):
            profile = self.root / name
            projects = Projects(profile)
            project = projects.open({"source": str(self.game), "engine": "MVMZ"})
            translation = SimpleNamespace(
                workspace=profile,
                idle=lambda _: None,
                clean_drafts=lambda _: None,
                writable=lambda _: None,
            )
            service = PluginService(
                projects, translation, self.backend, documents=self.documents
            )
            return project["id"], service

        def foreign(identity, service):
            with self.assertRaises(ForeignWorkError) as raised:
                service.state(identity)
            return raised.exception.summary

        identity, service = reopened("fresh-profile")
        saved = foreign(identity, service)
        self.assertEqual((saved["applied"], saved["restorable"]), (2, 2))
        with self.assertRaisesRegex(ValueError, "changed since it was shown"):
            service.adopt(identity, "0" * 64)
        reply = service.adopt(identity, saved["binding"])
        check_response("plugins_adopt", reply)
        self.assertEqual(reply["state"]["counts"]["applied"], 2)
        # The earlier project and its copied task no longer act on this work.
        foreign(self.identity, self.service)
        with self.assertRaisesRegex(ValueError, "Copy a plugin task"):
            service.continue_task(identity, request["requestId"])
        # A verified application stays restorable through its own review.
        restore = service.action(identity, "preview_restore", {"receipt": receipt})
        service.action(identity, "restore", {"token": restore["preview"]["token"]})
        for path, raw in original.items():
            self.assertEqual((self.game / path).read_bytes(), raw)

        # Only the project that was interrupted can reconcile its publication.
        identity, service = reopened("reinstalled-profile")
        state = self.game / ".dazedtl/plugin-work/state.json"
        value = read_json(state)
        write_json(state, {**value, "pending": ["0" * 32]})
        saved = foreign(identity, service)
        with self.assertRaisesRegex(ValueError, "interrupted"):
            service.adopt(identity, saved["binding"])
        service.start_over(identity, saved["binding"])
        [archived] = (self.game / ".dazedtl/archived").iterdir()
        self.assertTrue(archived.name.startswith("plugin-work-"))
        self.assertEqual(read_json(archived / "state.json")["pending"], ["0" * 32])
        self.assertEqual(service.state(identity)["counts"]["files"], 0)

    def test_interrupted_publication_reconciles_exact_bytes_and_rejects_tampered_journal(
        self,
    ):
        _request, _report = self.translated()
        publish = self.service._publish_file
        count = 0

        def interrupt(root, path, raw):
            nonlocal count
            count += 1
            if count == 2:
                raise KeyboardInterrupt("Injected process interruption")
            publish(root, path, raw)

        with (
            patch.object(self.service, "_publish_file", side_effect=interrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.service.action(self.identity, "apply")
        [publication] = self.service.load(self.identity)["pending"]
        journal = self.service.path(
            self.identity, "publications/" + publication + "/approval.json"
        )
        original = journal.read_bytes()
        document = read_json(journal)
        document["files"][0]["afterHash"] = "0" * 64
        write_json(journal, document)
        restarted = PluginService(
            self.projects,
            self.translation,
            self.backend,
            documents=self.service.documents,
        )
        with self.assertRaisesRegex(ValueError, "journal changed"):
            restarted.state(self.identity)
        write_bytes(journal, original)
        state = restarted.state(self.identity)
        receipt = state["receipts"][-1]
        self.assertEqual(receipt["status"], "recovered")
        self.assertEqual(len(receipt["files"]), 1)
        restore = restarted.action(
            self.identity, "preview_restore", {"receipt": receipt["id"]}
        )["preview"]
        restarted.action(self.identity, "restore", {"token": restore["token"]})
        self.assertEqual(restarted.state(self.identity)["counts"]["applied"], 0)


class AceScriptTests(unittest.TestCase):
    """VX Ace keeps its player text in Ruby scripts, which Plugin files reads
    without running Ruby."""

    def test_ruby_literals_follow_rubys_own_reading(self):
        # Comments, =begin blocks, regular expressions and __END__ hold no
        # text; `/`, `%` and `?` after a value are operators; a lookup key,
        # compared value or when clause keeps its Japanese.
        source = (
            '# 説明 "コメント"\r\n'
            "=begin\r\n'ブロック'\r\n=end\r\n"
            "x = a / 2 # 'まだ'\r\n"
            'RE = /"(名前)"/i\r\n'
            'TITLE = "音量 \\"設定\\"\\\\G\\e"\r\n'
            "PAGES = %w(前の\\ ページ 次)\r\n"
            'label = cond ? "はい" : "いいえ"\r\n'
            'room = "#{name}の部屋"\r\n'
            "said = 'It\\'s 文字'\r\n"
            'show(<<-EOS, "後")\r\n  本文\r\n  EOS\r\n'
            "class <<self; end\r\n"
            "y = 10 % 3; quote = %Q(引用)\r\n"
            'case x\r\nwhen "選択",\r\n  "次も"\r\nend\r\n'
            'same = x == "比較"\r\n'
            'KEYS = { "鍵" => 1 }; h["索引"] = "値"\r\n'
            "inner = \"#{'内側'}\"\r\n"
            'line.start_with?("ア:")\r\n'
            "__END__\r\n'無視'\r\n"
        )
        parsed = ruby.parse("Menu.rb", source)
        self.assertEqual(parsed["issues"], [])
        raw = source.encode()
        for literal in parsed["literals"]:
            self.assertEqual(
                raw[literal["start"] : literal["end"]].decode(), literal["raw"]
            )
        self.assertEqual(
            [
                (item["value"], item["kind"], item["protected"], item["matcher"])
                for item in parsed["literals"]
            ],
            [
                ('音量 "設定"\\G\x1b', "literal", False, False),
                ("前の ページ", "word", False, False),
                ("次", "word", False, False),
                ("はい", "literal", False, False),
                ("いいえ", "literal", False, False),
                ("#{name}の部屋", "template", False, False),
                ("It's 文字", "literal", False, False),
                ("後", "literal", False, False),
                ("  本文\n", "heredoc", False, False),
                ("引用", "literal", False, False),
                ("選択", "literal", True, False),
                ("次も", "literal", True, False),
                ("比較", "literal", True, False),
                ("鍵", "literal", True, False),
                ("索引", "literal", True, False),
                ("値", "literal", False, False),
                ("#{'内側'}", "template", True, False),
                ("ア:", "literal", False, True),
            ],
        )
        # Text an event script compares keeps its Japanese in the scripts.
        keys = set()
        event_script_keys(
            {
                "list": [
                    {"code": 355, "parameters": ["if $game_variables[1] =="]},
                    {"code": 655, "parameters": ["  '満月'"]},
                    {"code": 355, "parameters": ["$game_message.add('表示')"]},
                    {"code": 111, "parameters": [12, "$game_variables[2] == '新月'"]},
                ]
            },
            keys,
        )
        self.assertEqual(keys, {"満月", "新月"})

    def test_scripts_are_investigated_translated_checked_and_applied(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        game, profile = root / "game", root / "profile"
        fixture = Path(__file__).resolve().parent / "fixtures/ace"
        shutil.copytree(fixture / "Data", game / "Data")
        shutil.copytree(
            fixture / "ace_json",
            game / "ace_json",
            ignore=shutil.ignore_patterns("*Vocab*"),
        )
        script = "ace_json/scripts/200_メニュー.rb"
        write_bytes(
            game / script,
            (
                "module Menu\r\n"
                '  TITLE = "音量設定"\r\n'
                "  PAGES = ['前のページ', '次のページ']\r\n"
                '  GOLD = "お金を %s\\\\G 手に入れた！"\r\n'
                '  ROOM = "#{name}の部屋"\r\n'
                # An item's original name is a lookup key.
                '  SHOP = "ポーション"\r\n'
                "  HELP = <<-EOS\r\n    音量を調整します\r\n  EOS\r\n"
                "end\r\n"
            ).encode(),
        )
        write_bytes(game / ".dazedtl/glossary.txt", b"Terms\n")
        projects = Projects(profile)
        project = projects.open({"source": str(game), "engine": "ACE"})
        identity = project["id"]
        packed = []
        service = PluginService(
            projects,
            SimpleNamespace(
                workspace=profile,
                idle=lambda _: None,
                clean_drafts=lambda _: None,
                writable=lambda _: None,
                engine=SimpleNamespace(
                    ace_data=TranslationEngine.ace_data,
                    ace_script_order=TranslationEngine.ace_script_order,
                ),
            ),
            SimpleNamespace(
                source=root / "engine",
                guided_ace_blocked=lambda _root: None,
                guided_ace_pack=lambda source, _native, touched: packed.append(
                    (source, touched)
                ),
            ),
        )
        write_json(
            lifecycle_path(profile, identity),
            {
                "version": 1,
                "source_backup": snapshot(game, store_path(game), source_game=True),
            },
        )
        task = service.action(identity, "plugin_task")
        self.assertIn("Ruby scripts", task["text"])
        request = read_json(task["request"])
        self.assertEqual(request["gameData"], str(game / "ace_json"))
        # Each script with Japanese text is asked about, apart from lookup keys.
        [asked] = request["files"]
        self.assertEqual(asked["plugin"], "メニュー")
        self.assertEqual(
            [item["value"] for item in asked["occurrences"]],
            [
                "音量設定",
                "前のページ",
                "次のページ",
                "お金を %s\\G 手に入れた！",
                "#{name}の部屋",
                "    音量を調整します\n",
            ],
        )
        report = {key: request[key] for key in PluginTests.identity_keys}
        report.update(
            complete=True,
            dependencies=[],
            files=[
                {
                    "path": row["path"],
                    "sourceHash": row["sourceHash"],
                    "examined": True,
                    "evidence": "Drawn by the menu scene",
                    "occurrences": [
                        {
                            "id": item["id"],
                            "disposition": "visible",
                            "safe": True,
                            "evidence": "draw_text",
                            "reason": "Menu text",
                        }
                        for item in row["occurrences"]
                    ],
                }
                for row in request["files"]
            ],
        )
        write_json(request["report"], report)
        task = service.continue_task(identity, request["requestId"])
        request = read_json(task["request"])
        self.assertEqual(request["kind"], "translation")
        [asked] = request["files"]
        targets = dict(
            zip(
                [item["id"] for item in asked["occurrences"]],
                [
                    'Volume "Settings"',
                    "Previous Page",
                    "Next's Page",
                    "Got %s\\G gold!",
                    "#{name}'s Room",
                    "    Adjust the volume\n",
                ],
            )
        )
        candidate = game / asked["candidate"]
        good = (
            "module Menu\r\n"
            '  TITLE = "Volume \\"Settings\\""\r\n'
            "  PAGES = ['Previous Page', 'Next\\'s Page']\r\n"
            '  GOLD = "Got %s\\\\G gold!"\r\n'
            '  ROOM = "#{name}\'s Room"\r\n'
            '  SHOP = "ポーション"\r\n'
            "  HELP = <<-EOS\r\n    Adjust the volume\r\n  EOS\r\n"
            "end\r\n"
        ).encode()
        answer = {
            "path": script,
            "sourceHash": asked["sourceHash"],
            "evidence": "Reviewed",
            "targets": targets,
        }
        # Quotes left unescaped end the string early, which the check catches
        # and hands back with Ruby's escaping rules.
        for raw in (good.replace(b'\\"Settings\\"', b'"Settings"'), good):
            write_bytes(candidate, raw)
            report = {key: request[key] for key in PluginTests.identity_keys}
            report.update(
                complete=True, files=[{**answer, "candidateHash": digest(raw)}]
            )
            write_json(request["report"], report)
            task = service.continue_task(identity, request["requestId"])
            if raw != good:
                self.assertIn("escape quotes", task["message"])
        self.assertEqual(task["stage"], "complete")
        applied = service.action(identity, "apply")
        self.assertFalse(applied["blocked"])
        self.assertEqual((game / script).read_bytes(), good)
        # The game reads its scripts only from Data/Scripts.rvdata2.
        self.assertEqual(packed, [(game.resolve(), [script])])
        state = service.state(identity)
        self.assertTrue(state["scripts"])
        self.assertEqual(state["counts"]["applied"], 1)
