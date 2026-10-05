"""Protect exact edit scope, pristine lookup evidence and reviewed publication recovery."""

import json
import unittest
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.plugins import PluginService
from dazedtl.plugins.documents import Documents, occurrences, replace_leaf, validate
from dazedtl.projects.store import Projects
from dazedtl.storage import write_bytes, write_json
from dazedtl.translation.backups import snapshot, store_path
from dazedtl.translation.files import digest, read_json
from dazedtl.translation.operations import lifecycle_path


class FixtureDocuments:
    """Reuse real parse results only for identical fixture inputs."""

    @lru_cache(maxsize=64)
    def _parse(self, path, kind, source):
        return Documents().parse([{"path": path, "kind": kind, "source": source}])[path]

    def parse(self, files):
        # Services and later tests must never share mutable parser results.
        return {row["path"]: deepcopy(self._parse(**row)) for row in files}


class PluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = FixtureDocuments()
        cls.addClassCleanup(cls.documents._parse.cache_clear)

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
                "parameters": {"Label": "開始", "List": encoded},
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
            workspace=self.profile, idle=lambda _: None, clean_drafts=lambda _: None
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

    def investigation(self, task=None, *, refresh=True):
        result = task or self.service.action(self.identity, "investigate")
        request = read_json(result["request"])
        rows = []
        for asked in request["files"]:
            rows.append(
                {
                    "path": asked["path"],
                    "sourceHash": asked["sourceHash"],
                    "examined": not asked["issue"],
                    "evidence": "Complete recursive/source fixture audit",
                    "occurrences": [
                        {
                            "id": item["id"],
                            "disposition": "protected"
                            if item["protected"]
                            else "latent"
                            if item["latent"]
                            else "visible",
                            "safe": not item["protected"],
                            "evidence": "Fixture drawText consumer checked; keys remain read-only",
                            "reason": "Player-visible static label"
                            if not item["protected"]
                            else "Original Japanese item lookup",
                        }
                        for item in asked["occurrences"]
                    ],
                }
            )
        report = {
            key: request[key]
            for key in ("version", "kind", "projectId", "requestId", "binding")
        }
        report.update(files=rows, complete=True, dependencies=[])
        write_json(request["report"], report)
        if refresh:
            self.service.action(self.identity, "refresh_findings")
        return request, report

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

    def translated(self):
        self.investigation()
        result = self.service.action(self.identity, "translation_task")
        request = read_json(result["request"])
        rows = []
        for asked in request["files"]:
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
        report = {
            key: request[key]
            for key in ("version", "kind", "projectId", "requestId", "binding")
        }
        report.update(files=rows, complete=True)
        write_json(request["report"], report)
        self.service.action(self.identity, "refresh_results")
        return request, report

    def test_recursive_parameters_pristine_keys_and_retained_hidden_scope(self):
        # Already translated runtime DB must not erase original lookup guards.
        write_json(
            self.game / "www/data/Items.json",
            [None, {"id": 1, "name": "Herb", "note": "<所持金消費:1>"}],
        )
        request, _ = self.investigation()
        value = self.service.load(self.identity)
        item = next(
            item
            for row in value["files"].values()
            for item in row["occurrences"]
            if item["value"] == "薬草"
        )
        self.assertTrue(item["protected"])
        self.assertFalse(item["finding"]["safe"])
        labels = [
            item
            for item in value["files"]["www/js/plugins.js"]["occurrences"]
            if item["value"] == "目的地"
        ]
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(item["finding"]["safe"] for item in labels))
        selected = self.service.state(self.identity)["counts"]["selected"]
        self.assertEqual(
            selected, 4
        )  # Confirmed active leaves are included without a recommendation click.
        self.assertFalse(any(row.get("prepared") for row in value["files"].values()))
        state = self.service.state(self.identity)
        self.service.update(
            self.identity,
            state["revision"],
            {"view": {"query": "PluginB", "currentFile": "www/js/plugins/PluginA.js"}},
        )
        self.assertEqual(
            self.service.list(self.identity, query="PluginB")["selectedMatched"], 0
        )
        restarted = PluginService(
            self.projects,
            self.translation,
            self.backend,
            documents=self.service.documents,
        )
        self.assertEqual(restarted.state(self.identity)["counts"]["selected"], selected)
        self.assertEqual(restarted.state(self.identity)["view"]["query"], "PluginB")
        self.assertNotIn(
            "www/data/Map001.json", [row["path"] for row in request["files"]]
        )

    def test_automatic_scope_retains_exclusions_and_drops_missing_or_uncertain_evidence(
        self,
    ):
        request, report = self.investigation()
        selected = self.service.load(self.identity)["selection"]
        excluded = selected[0]
        self.service.action(
            self.identity, "select", {"ids": [excluded], "selected": False}
        )
        self.service.action(self.identity, "refresh_findings")
        self.assertNotIn(excluded, self.service.load(self.identity)["selection"])
        row = next(
            row for row in report["files"] if row["path"].endswith("/PluginA.js")
        )
        uncertain = next(
            item
            for item in row["occurrences"]
            if item["id"] in selected and item["id"] != excluded
        )
        uncertain.update(
            disposition="unresolved", safe=False, reason="Display use is ambiguous"
        )
        omitted = next(
            item
            for item in report["files"][0]["occurrences"]
            if item["id"] in selected and item["id"] != excluded
        )
        report["files"][0]["occurrences"].remove(omitted)
        write_json(request["report"], report)
        self.service.action(self.identity, "refresh_findings")
        value = self.service.load(self.identity)
        self.assertTrue(
            {excluded, uncertain["id"], omitted["id"]}.isdisjoint(value["selection"])
        )
        uncertain_files = [
            row for row in self.service.list(self.identity)["items"] if row["uncertain"]
        ]
        self.assertEqual(
            {row["path"] for row in uncertain_files},
            {"www/js/plugins.js", "www/js/plugins/PluginA.js"},
        )
        # Retired saved filters must not hide the inventory or alter text scope.
        value["view"].update(filter="retired_filter", offset=100)
        self.service.save(self.identity, value)
        state = self.service.state(self.identity)
        self.assertEqual(state["view"]["filter"], "all")
        self.assertEqual(state["view"]["offset"], 0)
        self.assertEqual(
            self.service.load(self.identity)["selection"], value["selection"]
        )
        self.assertEqual(
            self.service.list(self.identity, filter="retired_filter")["total"],
            state["counts"]["files"],
        )
        before = {path: (self.game / path).read_bytes() for path in value["files"]}
        task = self.service.action(self.identity, "translation_task")
        self.assertEqual(
            self.service.state(self.identity)["counts"]["selectedNotPrepared"], 0
        )
        self.assertTrue(
            all((self.game / path).read_bytes() == raw for path, raw in before.items())
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
            self.service.action(self.identity, "translation_task")

    def test_foreign_duplicate_traversal_and_stale_reports_are_atomic(self):
        request, report = self.investigation()
        prior = deepcopy(self.service.load(self.identity))
        with self.assertRaisesRegex(ValueError, "Copy a plugin task"):
            self.service.continue_task(self.identity, request["requestId"])
        for mutate in (
            lambda r: r.update(projectId="foreign"),
            lambda r: r["files"].append(deepcopy(r["files"][0])),
            lambda r: r["files"][0].update(path="../outside.js"),
        ):
            invalid = deepcopy(report)
            mutate(invalid)
            write_json(request["report"], invalid)
            with self.assertRaises(ValueError):
                self.service.action(self.identity, "refresh_findings")
            self.assertEqual(self.service.load(self.identity), prior)
        changed = deepcopy(prior)
        changed["requests"]["investigation"]["binding"] = "forged"
        self.service.save(self.identity, changed)
        write_json(request["path"], changed["requests"]["investigation"])
        with self.assertRaisesRegex(ValueError, "scoped request changed"):
            self.service.action(self.identity, "refresh_findings")
        self.service.save(self.identity, prior)
        write_json(request["path"], request)
        write_json(request["report"], report)
        self.write("www/js/plugins/PluginA.js", "drawText('変更');")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            self.service.action(self.identity, "refresh_findings")

    def test_unrelated_code_interpolation_controls_and_extra_files_are_rejected(self):
        request, report = self.translated()
        path = "www/js/plugins/PluginA.js"
        row = next(row for row in report["files"] if row["path"] == path)
        candidate = (
            self.game
            / self.service.load(self.identity)["files"][path]["prepared"]["candidate"]
        )
        good = candidate.read_bytes()
        for raw in (
            good + b"\nmalicious();",
            good.replace(b"actor.name", b"actor.secret"),
            good.replace(b"lookup(key)", b"lookup('changed')"),
        ):
            write_bytes(candidate, raw)
            row["candidateHash"] = digest(raw)
            write_json(request["report"], report)
            self.service.action(self.identity, "refresh_results")
            detail = self.service.detail(self.identity, path)
            self.assertEqual(detail["status"], "needs_revision")
            self.assertFalse(detail["checks"])
        forged = self.service.load(self.identity)
        forged["files"][path]["result"]["status"] = "ready"
        self.service.save(self.identity, forged)
        review = self.service.action(self.identity, "preview_apply")["preview"]
        self.assertTrue(any(item["path"] == path for item in review["blocked"]))
        self.assertNotIn(path, [item["path"] for item in review["files"]])
        write_bytes(candidate, good)
        row["candidateHash"] = digest(good)
        report["files"].append({"path": "www/js/plugins/New.js", "sourceHash": "x"})
        write_json(request["report"], report)
        with self.assertRaisesRegex(ValueError, "out-of-scope"):
            self.service.action(self.identity, "refresh_results")

    def test_apply_cancel_stale_preview_one_use_restore_and_rollback(self):
        # Keep the real, uncached parser boundary through investigation,
        # translation, Apply and restore, alongside the direct parser checks.
        self.service.documents = Documents()
        request, report = self.translated()
        before = {
            row["path"]: (self.game / row["path"]).read_bytes()
            for row in request["files"]
        }
        self.assertEqual(self.service.state(self.identity)["counts"]["ready"], 2)
        canceled = self.service.action(self.identity, "preview_apply")["preview"]
        self.assertTrue(
            all((self.game / path).read_bytes() == raw for path, raw in before.items())
        )
        path = request["files"][0]["path"]
        candidate = (
            self.game
            / self.service.load(self.identity)["files"][path]["prepared"]["candidate"]
        )
        raw = candidate.read_bytes()
        write_bytes(candidate, raw + b" ")
        with self.assertRaisesRegex(ValueError, "changed after review"):
            self.service.action(self.identity, "apply", {"token": canceled["token"]})
        write_bytes(candidate, raw)
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        original_publish = self.service._publish_file
        calls = []

        def fail(root, path, content):
            calls.append(path)
            original_publish(root, path, content)
            if len(calls) == 2:
                raise OSError("Injected second publication failure after its write")

        with patch.object(self.service, "_publish_file", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "rollback attempted"):
                self.service.action(self.identity, "apply", {"token": preview["token"]})
        self.assertTrue(
            all((self.game / path).read_bytes() == raw for path, raw in before.items())
        )
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        result = self.service.action(
            self.identity, "apply", {"token": preview["token"]}
        )
        with self.assertRaisesRegex(ValueError, "already used"):
            self.service.action(self.identity, "apply", {"token": preview["token"]})
        saved = self.service.load(self.identity)
        original_saved = deepcopy(saved)
        saved["receipts"][-1]["files"][0]["backup"] = saved["files"][path]["prepared"][
            "candidate"
        ]
        self.service.save(self.identity, saved)
        with self.assertRaisesRegex(ValueError, "exact approved publication"):
            self.service.action(
                self.identity, "preview_restore", {"receipt": result["receipt"]["id"]}
            )
        self.service.save(self.identity, original_saved)
        restore = self.service.action(
            self.identity, "preview_restore", {"receipt": result["receipt"]["id"]}
        )["preview"]
        self.service.action(self.identity, "restore", {"token": restore["token"]})
        self.assertTrue(
            all((self.game / path).read_bytes() == raw for path, raw in before.items())
        )
        copies = {
            path: deepcopy(row["prepared"])
            for path, row in self.service.load(self.identity)["files"].items()
            if row.get("prepared")
        }
        self.service.action(self.identity, "translation_task")
        self.assertEqual(self.service.state(self.identity)["counts"]["ready"], 0)
        self.assertEqual(
            copies,
            {
                path: row["prepared"]
                for path, row in self.service.load(self.identity)["files"].items()
                if row.get("prepared")
            },
        )
        self.service.action(self.identity, "clear")
        self.assertEqual(self.service.state(self.identity)["counts"]["ready"], 0)
        self.assertEqual(
            self.service.action(self.identity, "preview_apply")["preview"]["files"], []
        )

    def test_partial_results_and_manual_latent_exclusions_survive_redo(self):
        request, report = self.translated()
        answer = report["files"][0]
        answer["targets"].pop(next(iter(answer["targets"])))
        # A changed value omitted from the report is not accepted as a partial result.
        write_json(request["report"], report)
        self.service.action(self.identity, "refresh_results")
        self.assertEqual(
            self.service.detail(self.identity, answer["path"])["status"],
            "needs_revision",
        )
        value = self.service.load(self.identity)
        latent = next(
            item
            for row in value["files"].values()
            for item in row["occurrences"]
            if item["latent"] and item.get("finding", {}).get("safe")
        )
        with self.assertRaisesRegex(ValueError, "reason"):
            self.service.action(
                self.identity, "select", {"ids": [latent["id"]], "selected": True}
            )
        self.service.action(
            self.identity,
            "select",
            {
                "ids": [latent["id"]],
                "selected": True,
                "reason": "Translate this optional default",
            },
        )
        self.service.action(self.identity, "recommended")
        self.assertIn(latent["id"], self.service.load(self.identity)["selection"])
        self.service.action(
            self.identity,
            "select",
            {
                "ids": [latent["id"]],
                "selected": False,
                "reason": "Keep Japanese variant",
            },
        )
        self.service.action(self.identity, "recommended")
        self.assertNotIn(latent["id"], self.service.load(self.identity)["selection"])

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
        context = self.service.original_context(self.identity, "www/")
        self.assertIn("所持金消費", context["keys"])
        self.assertNotIn("所持金", context["keys"])
        self.assertNotIn("大きい", context["keys"])

    def test_missing_originals_and_dynamic_configuration_never_authorize_edits(self):
        lifecycle_path(self.profile, self.identity).unlink()
        request, report = self.investigation()
        self.service.action(self.identity, "recommended")
        self.assertEqual(self.service.state(self.identity)["counts"]["selected"], 0)
        with self.assertRaises(ValueError):
            self.service.action(self.identity, "prepare")
        self.write("www/js/plugins.js", "var $plugins = dangerous();")
        with self.assertRaisesRegex(ValueError, "static literal"):
            self.service.action(self.identity, "investigate")
        malformed = Documents().parse(
            [{"path": "bad.json", "source": '{"Text": "日本語"', "kind": "json"}]
        )["bad.json"]
        self.assertTrue(malformed["issues"])
        self.assertEqual(malformed["literals"], [])
        from dazedtl.plugins.documents import leaves

        with self.assertRaisesRegex(ValueError, "does not decode"):
            list(leaves('{"Text": "日本語"'))

    def test_explicit_loaded_json_needs_new_investigation_then_exact_leaf_checks(self):
        task = self.service.action(self.identity, "plugin_task")
        request, report = self.investigation(task, refresh=False)
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
        self.assertIn(
            "www/data/PluginN.json",
            [row["path"] for row in read_json(followup["request"])["files"]],
        )
        # A lost reply returns the existing successor, without creating another request.
        self.assertEqual(
            self.service.continue_task(self.identity, request["requestId"])[
                "requestId"
            ],
            followup["requestId"],
        )
        self.investigation(followup, refresh=False)
        view_revision = self.service.state(self.identity)["revision"]
        result = self.service.continue_task(self.identity, followup["requestId"])
        self.assertEqual(result["stage"], "translation")
        # Incoming agent scope must not invalidate a pending search/view edit.
        self.service.update(
            self.identity, view_revision, {"view": {"query": "PluginN"}}
        )
        self.assertEqual(self.service.state(self.identity)["view"]["query"], "PluginN")
        path = "www/data/PluginN.json"
        row = self.service.load(self.identity)["files"][path]
        request = read_json(result["request"])
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
        report = {
            key: request[key]
            for key in ("version", "kind", "projectId", "requestId", "binding")
        }
        report.update(files=[answer])
        write_json(request["report"], report)
        self.service.continue_task(self.identity, request["requestId"])
        self.assertEqual(self.service.detail(self.identity, path)["status"], "ready")
        self.assertEqual(self.service.state(self.identity)["counts"]["applied"], 0)
        altered = candidate.replace(b'"id"', b'"renamed"')
        write_bytes(self.game / row["prepared"]["candidate"], altered)
        answer["candidateHash"] = digest(altered)
        write_json(request["report"], report)
        self.service.action(self.identity, "refresh_results")
        self.assertEqual(
            self.service.detail(self.identity, path)["status"], "needs_revision"
        )
        write_bytes(self.game / row["prepared"]["candidate"], candidate)
        answer["candidateHash"] = digest(candidate)
        write_json(request["report"], report)
        write_bytes(self.game / row["prepared"]["copyRoot"] / "New.js", b"malicious();")
        with self.assertRaisesRegex(ValueError, "New or missing"):
            self.service.action(self.identity, "refresh_results")
        self.service.action(self.identity, "plugin_task")
        with self.assertRaisesRegex(ValueError, "replaced"):
            self.service.continue_task(self.identity, request["requestId"])

    def test_interrupted_publication_reconciles_exact_bytes_and_rejects_tampered_journal(
        self,
    ):
        request, report = self.translated()
        preview = self.service.action(self.identity, "preview_apply")["preview"]
        publish = self.service._publish_file
        count = 0

        def interrupt(root, path, raw):
            nonlocal count
            count += 1
            if count == 2:
                raise KeyboardInterrupt("Injected process interruption")
            publish(root, path, raw)

        with patch.object(self.service, "_publish_file", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.service.action(self.identity, "apply", {"token": preview["token"]})
        pending = self.service.load(self.identity)
        journal = self.service.path(
            self.identity, "publications/" + preview["token"] + "/approval.json"
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
