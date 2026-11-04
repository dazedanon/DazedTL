"""Every guidance document through every state its file can be in and every
reader its definition feeds, so a new kind of document, or a new state,
can't skip one: the assistant notes were one more document name, and each
review found the next reader without its branch."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from dazedtl.compatibility.checkpoint_commits import ACTION_TRAILER, TARGET_TRAILER
from dazedtl.compatibility.checkpoint_history import BACK, Entry, _taken_out
from dazedtl.translation import context_setup
from dazedtl.translation.files import digest
from dazedtl.translation.service import Translation
from desktop.backend.guidance import documents, documents_save, read, written
from util.guidance_documents import (
    FIXED,
    HANDOFF,
    REQUEST_WORK,
    custom,
    kept_by_checkpoints,
    save_summary,
)
from util.paths import is_game_tool_file, is_project_file

GLOSSARY, NOTES = "glossary", "notes"


class GuidanceDocumentTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".dazedtl/skills").mkdir(parents=True)

    def file(self, name):
        return self.root / read(self.root)[name]["file"]

    def test_every_state_of_a_file_an_assistant_writes_reads_as_itself(self):
        # Unreadable notes left the tab without a word, and an unreadable
        # glossary refused every state; each reads as unreadable with why,
        # leaves the other documents readable, and refuses only the work
        # that needs its text.
        big = b"x" * 1_000_001
        states = {
            "missing": (None, "missing", ""),
            "UTF-8": (b"Repack Data.wolf.", "saved", ""),
            "UTF-16, as Out-File writes it": ("Repack".encode("utf-16"), "saved", ""),
            "cp932, as Set-Content writes it": (
                "メモ".encode("cp932"),
                "unreadable",
                "UTF-8",
            ),
            "larger than 1 MB": (big, "unreadable", "larger than 1 MB"),
            "a link": ("link", "unreadable", "link"),
            "a folder": ("folder", "unreadable", "folder"),
            "another file in the other place": ("twice", "unreadable", "holds it too"),
        }
        if os.name != "nt" and os.geteuid() != 0:
            states["without read permission"] = ("locked", "unreadable", "allowed")
        for name in (GLOSSARY, NOTES):
            path = self.root / read(self.root)[name]["file"]
            for case, (content, state, reason) in states.items():
                with self.subTest(document=name, file=case):
                    for leftover in (
                        path,
                        self.root / "agents.md",
                        self.root / "glossary.txt",
                    ):
                        if leftover.is_dir() and not leftover.is_symlink():
                            leftover.rmdir()
                        elif leftover.exists() or leftover.is_symlink():
                            leftover.chmod(0o644) if not leftover.is_symlink() else None
                            leftover.unlink()
                    if content == "link":
                        (self.root / "target.md").write_text("Shared", encoding="utf-8")
                        path.symlink_to(self.root / "target.md")
                    elif content == "folder":
                        path.mkdir()
                    elif content == "twice":
                        path.write_text("One", encoding="utf-8")
                        other = "agents.md" if name == NOTES else "glossary.txt"
                        (self.root / other).write_text("Two", encoding="utf-8")
                    elif content == "locked":
                        path.write_text("Locked", encoding="utf-8")
                        path.chmod(0)
                    elif content is not None:
                        path.write_bytes(content)
                    found = read(self.root)
                    self.assertEqual(found[name]["state"], state)
                    self.assertIn(reason, found[name].get("reason", ""))
                    self.assertTrue(
                        all(
                            document["state"] != "unreadable"
                            for other, document in found.items()
                            if other != name
                        )
                    )
                    if state == "unreadable":
                        # Nothing saves over it, and the work that reads a
                        # requests' document is refused with the same reason.
                        with self.assertRaisesRegex(ValueError, "can't read"):
                            documents_save(
                                self.root, {name: {"revision": "", "text": "Mine"}}
                            )
                        if found[name]["requests"]:
                            with self.assertRaisesRegex(ValueError, "can't read"):
                                documents(self.root)
                        else:
                            self.assertNotIn(name, documents(self.root))
                    if content == "locked":
                        path.chmod(0o644)
        # A folder in the notes' name is the project's too, so its files
        # never join a patch: Release's review listed AGENTS.md/x.
        self.assertTrue(is_game_tool_file("agents.md/x.txt"))
        # The notes in another case are the notes, as ownership takes them.
        for leftover in (self.root / "AGENTS.md", self.root / "agents.md"):
            leftover.unlink(missing_ok=True)
        (self.root / "agents.md").write_text("Lower case.", encoding="utf-8")
        found = read(self.root)[NOTES]
        self.assertEqual((found["state"], found["file"]), ("saved", "agents.md"))
        documents_save(
            self.root, {NOTES: {"revision": found["revision"], "text": "Kept."}}
        )
        self.assertEqual((self.root / "agents.md").read_text(encoding="utf-8"), "Kept.")
        self.assertIn("agents.md", written(self.root, [NOTES]))

    def test_an_edit_on_disk_under_a_draft_is_saved_over_only_by_keeping_the_draft(
        self,
    ):
        # Guided replaced the notes an assistant wrote after its draft began,
        # and Assistant-led refused with no way forward but losing the
        # draft. A save names the file's revision when the draft began: one
        # the file moved past is refused, and keeping the draft saves it at
        # the file's current revision.
        for name in (GLOSSARY, NOTES):
            path = self.file(name)
            edits = {
                "changed": ("Before.", "Changed by an assistant."),
                "deleted": ("Before.", None),
                "created": (None, "Created by an assistant."),
            }
            for case, (before, after) in edits.items():
                with self.subTest(document=name, edit=case):
                    path.unlink(missing_ok=True)
                    if before is not None:
                        path.write_text(before, encoding="utf-8")
                    began = read(self.root)[name]["revision"] if before else ""
                    if after is None:
                        path.unlink()
                    else:
                        path.write_text(after, encoding="utf-8")
                    draft = {name: {"revision": began, "text": "My draft"}}
                    self.assertTrue(read(self.root, draft)[name]["changed"])
                    with self.assertRaisesRegex(ValueError, "changed on disk"):
                        documents_save(self.root, draft)
                    self.assertEqual(
                        path.exists() and path.read_text(encoding="utf-8"),
                        after or False,
                    )
                    current = read(self.root)[name]["revision"]
                    documents_save(
                        self.root, {name: {"revision": current, "text": "My draft"}}
                    )
                    self.assertEqual(read(self.root)[name]["text"], "My draft")
                    # A file that already holds the draft's text is no conflict,
                    # as a glossary reads it, without its trailing newlines:
                    # the editor said a file holding the draft had changed.
                    self.assertFalse(read(self.root, draft)[name]["changed"])
                    documents_save(self.root, draft)
                    trailing = {name: {"revision": began, "text": "My draft\n"}}
                    self.assertEqual(
                        read(self.root, trailing)[name]["changed"], name != GLOSSARY
                    )

    def test_each_definition_reaches_every_reader(self):
        # The readers the analysis found branching on the notes' name, now
        # reading the definition: the editors, the save, its checkpoint
        # name, the files a write names, ownership, checkpoints, the drafts
        # gate and Guidance's completion.
        for found in (*FIXED, custom("lore")):
            with self.subTest(document=found.key):
                document = read(self.root, [found.key])[found.key]
                self.assertEqual(
                    (document["title"], document["kind"], document["state"]),
                    (found.title, found.kind, "missing"),
                )
                self.assertEqual(document["holdsUp"], sorted(found.holds_up))
                self.assertEqual(save_summary([found.key]), "Save " + found.title)
                self.assertIn(found.path, written(self.root, [found.key]))
                self.assertTrue(is_project_file(found.path))
                self.assertEqual(
                    kept_by_checkpoints(found.path), found.checkpoints == "keep"
                )
                # An empty save creates only a document Save creates empty.
                saved = documents_save(
                    self.root, {found.key: {"revision": "", "text": ""}}
                )
                self.assertEqual(bool(saved), found.created == "always")
                for work in (HANDOFF, REQUEST_WORK):
                    for method, tab in (("guided", "Guidance"), ("len", "Context")):
                        service = SimpleNamespace(
                            drafts=lambda _: {
                                "options": None,
                                "documents": {found.key: {"text": "", "revision": ""}},
                            },
                            projects=SimpleNamespace(
                                get=lambda _, m=method: {"method": m}
                            ),
                        )
                        if work in found.holds_up:
                            with self.assertRaisesRegex(
                                ValueError, f"your {found.title} draft in {tab} first"
                            ):
                                Translation.clean_drafts(service, "game", work)
                        else:
                            Translation.clean_drafts(service, "game", work)
        inspected = context_setup.inspect(
            self.root / "request.json",
            self.root / "review.json",
            {"source": str(self.root), "widths": {}},
            "game",
            read(self.root),
            {},
            {},
            digest,
        )
        self.assertEqual(inspected["status"], "ready")

    def test_go_back_takes_out_no_checkpoint_of_a_document_it_keeps(self):
        # Go back keeps the notes, yet listed a "Save Assistant notes" after
        # its target as taken out.
        def entry(commit, paths, message="Save"):
            return Entry(commit, "", message, {path: () for path in paths}, listed=True)

        back = entry(
            "back",
            ["Map001.json"],
            f"Went back\n\n{ACTION_TRAILER}: {BACK}\n{TARGET_TRAILER}: target",
        )
        entries = [
            back,
            entry("notes", ["AGENTS.md"]),
            entry("map", ["Map001.json"]),
            entry("target", ["Map001.json"]),
        ]
        self.assertEqual(_taken_out(entries), {"map": "back"})
