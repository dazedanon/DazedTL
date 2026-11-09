"""Every guidance document through every state its file can be in and every
reader its definition feeds, so a new kind of document, or a new state,
can't skip one: the assistant notes were one more document name, and each
review found the next reader without its branch."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.compatibility.checkpoint_commits import ACTION_TRAILER, TARGET_TRAILER
from dazedtl.compatibility.checkpoint_history import BACK, Entry, _taken_out
from dazedtl.translation import context_setup
from dazedtl.translation.files import digest
from dazedtl.translation.helper_command import notes_note
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
from util.paths import (
    GLOSSARY_BASE_SEPARATOR,
    GLOSSARY_OVERRIDE_ENV,
    glossary_base_text,
    is_game_tool_file,
    is_project_file,
    read_active_glossary,
    read_game_glossary,
)

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
        if os.name != "nt":
            # Read as a folder once, which it isn't.
            states["a pipe"] = ("pipe", "unreadable", "isn't a regular file")
        if os.name != "nt" and os.geteuid() != 0:
            states["without read permission"] = ("locked", "unreadable", "allowed")
        (self.root / "Case").touch()
        one_case = (self.root / "case").exists()
        (self.root / "Case").unlink()
        for name in (GLOSSARY, NOTES):
            path = self.root / read(self.root)[name]["file"]
            for case, (content, state, reason) in states.items():
                if content == "twice" and name == NOTES and one_case:
                    # On a case-blind folder, as on Windows and macOS,
                    # agents.md is AGENTS.md: it holds one file, the
                    # second write's.
                    state, reason = "saved", ""
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
                    elif content == "pipe":
                        os.mkfifo(path)
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
                    if content == "twice" and name == NOTES and one_case:
                        self.assertEqual(found[name]["text"], "Two")
                    elif content == "twice" and name == NOTES:
                        # Every task said to keep the first while the
                        # editors refused both.
                        self.assertIn("merge them", notes_note(self.root))
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
        self.assertTrue(kept_by_checkpoints("agents.md/x.txt"))
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

    def test_a_glossary_saved_on_windows_reads_saves_and_sends_one_base(self):
        # Context read a CRLF glossary's shipped base as the game's own and a
        # save then sent it twice in every request, and a run failed reading
        # a UTF-16 one that Context showed as saved.
        from util.len_translation import request_glossary
        from util.vocab import read_game_vocab

        base = glossary_base_text()
        self.assertTrue(base)
        own = "村長 (Village Chief)"
        sent = own + "\n\n" + GLOSSARY_BASE_SEPARATOR + base
        windows = sent.replace("\n", "\r\n")
        files = {
            "CRLF, as Notepad saves it": windows.encode(),
            "UTF-8 with its byte order mark": windows.encode("utf-8-sig"),
            "UTF-16, as Out-File writes it": windows.encode("utf-16"),
        }
        path = self.file(GLOSSARY)
        for case, content in files.items():
            for override in (False, True):
                with (
                    self.subTest(file=case, override=override),
                    patch.dict(
                        os.environ,
                        {
                            "DAZED_GAME_ROOT": str(self.root),
                            GLOSSARY_OVERRIDE_ENV: str(path) if override else "",
                        },
                    ),
                ):
                    path.write_bytes(content)
                    held = read(self.root)[GLOSSARY]
                    self.assertEqual(held["text"], own)
                    self.assertEqual(read_game_vocab(self.root), own)
                    self.assertEqual(read_active_glossary(), sent)
                    self.assertEqual(
                        request_glossary(read_game_glossary(self.root)), sent
                    )
                    documents_save(
                        self.root,
                        {
                            GLOSSARY: {
                                "revision": held["revision"],
                                "text": own + "\n魔王 (Demon King)",
                            }
                        },
                    )
                    saved = (
                        own + "\n魔王 (Demon King)\n\n" + GLOSSARY_BASE_SEPARATOR + base
                    )
                    self.assertEqual(path.read_bytes(), saved.encode())
                    self.assertEqual(read_active_glossary(), saved)

    def test_a_game_of_another_source_saves_and_sends_no_japanese_base(self):
        # A Context save wrote the shipped base, Japanese honorifics and
        # interface words, into an English game's glossary, and its runs then
        # sent each base row an English word matched, such as "Demon".
        from util import vocab
        from util.languages import SOURCE_ENV
        from util.len_translation import request_glossary
        from util.paths import glossary_base_path
        from util.translation import buildMatchedVocabText, parseVocabWithCategories

        japanese = glossary_base_path().read_text(encoding="utf-8")
        self.assertIn("(Demon)", japanese)
        own = "Duke (Duc)"
        line = "The Duke fights the Demon with Fire."
        path = self.file(GLOSSARY)
        freeze = self.root / "freeze.txt"
        with (
            patch.dict(
                os.environ,
                {
                    SOURCE_ENV: "English",
                    "DAZED_GAME_ROOT": str(self.root),
                    GLOSSARY_OVERRIDE_ENV: "",
                },
            ),
            patch.object(vocab, "BATCH_GLOSSARY_FREEZE_FILE", freeze),
        ):
            documents_save(self.root, {GLOSSARY: {"revision": "", "text": own}})
            self.assertEqual(
                path.read_bytes(), (own + "\n\n" + GLOSSARY_BASE_SEPARATOR).encode()
            )
            # A file a save wrote before, which keeps the copy until edited.
            path.write_text(
                own + "\n\n" + GLOSSARY_BASE_SEPARATOR + japanese, encoding="utf-8"
            )
            self.assertEqual(read(self.root)[GLOSSARY]["text"], own)
            sent = {
                "a run": read_active_glossary(),
                "a Batch": vocab.freeze_batch_glossary().read_text(encoding="utf-8"),
                "a Batch of a named game": vocab.freeze_batch_glossary(
                    game_root=self.root
                ).read_text(encoding="utf-8"),
                "Assistant-led": request_glossary(read_game_glossary(self.root)),
            }
            for reader, text in sent.items():
                with self.subTest(reader=reader):
                    matched = buildMatchedVocabText(
                        parseVocabWithCategories(text), line
                    )
                    self.assertIn(own, matched)
                    self.assertNotIn("Demon", matched)

    def test_skills_saved_on_windows_build_the_prompt_a_run_sends(self):
        # Context showed a UTF-16 skill as saved while the run building its
        # system prompt failed reading it, and a byte order mark reached the
        # prompt as a character. Every encoding Context reads builds the
        # prompt an LF UTF-8 file builds, which is the prompt it built before.
        from util.skills import load_system_prompt
        from util.skills.system import (
            base_system_prompt,
            compose_system_prompt,
            prompt_overlays,
        )

        texts = {
            "game.md": "# Lore\nThe village sits by the sea.",
            "quirks.md": "Keep honorifics.\nDrop sound effects.",
            "battle.md": "Attacks are verbs.\nKeep them short.",
        }
        encodings = {
            "LF UTF-8": lambda text: text.encode(),
            "CRLF, as Notepad saves it": lambda text: text.replace(
                "\n", "\r\n"
            ).encode(),
            "UTF-8 with its byte order mark": lambda text: text.encode("utf-8-sig"),
            "UTF-16, as Out-File writes it": lambda text: text.replace(
                "\n", "\r\n"
            ).encode("utf-16"),
        }
        expected = compose_system_prompt(
            base_system_prompt(),
            prompt_overlays(
                texts["game.md"], texts["quirks.md"], [("battle", texts["battle.md"])]
            ),
        )
        for case, encode in encodings.items():
            with self.subTest(file=case):
                game = self.root / case
                (game / ".dazedtl/skills").mkdir(parents=True)
                for name, text in texts.items():
                    (game / ".dazedtl/skills" / name).write_bytes(encode(text))
                self.assertEqual(read(game)["quirks"]["state"], "saved")
                self.assertEqual(load_system_prompt(game), expected)

    def test_a_draft_over_a_recovered_save_of_a_windows_file_reads(self):
        # A Context save that ended without its checkpoint, of a file
        # PowerShell had saved as UTF-16, failed every read with a draft
        # once the next write committed it.
        from dazedtl.compatibility.checkpoint_commits import (
            RECOVERED_TRAILER,
            STAGE_TRAILER,
        )

        def git(*arguments):
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "-c",
                    "core.autocrlf=false",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    *arguments,
                ],
                capture_output=True,
                check=True,
            )

        quirks = self.root / ".dazedtl/skills/quirks.md"
        quirks.write_bytes("Keep honorifics.\r\n".encode("utf-16"))
        began = read(self.root)["quirks"]["revision"]
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "Original")
        quirks.write_bytes(b"Keep honorifics.\nDrop sound effects.\n")
        git(
            "commit",
            "-q",
            "-am",
            "Context: Save Style & quirks",
            "-m",
            f"{STAGE_TRAILER}: Context\n{RECOVERED_TRAILER}: true",
        )
        draft = {"quirks": {"text": "My draft", "revision": began}}
        self.assertFalse(read(self.root, draft)["quirks"]["changed"])

    def test_text_qa_reviews_guidance_saved_on_windows_and_keeps_its_tasks(self):
        # Text QA left a UTF-16 skill out of the review as unreadable and
        # showed a byte order mark and Windows line ends; read as Context
        # reads it, a task prepared before from the same files goes on.
        from util.qa.schema import _canonical_bytes, _sha256
        from util.qa.selection import _context_pack, context_digests

        skills = self.root / ".dazedtl/skills"
        (self.root / ".dazedtl/glossary.txt").write_bytes(b"\xe6\xb0\xb4 (Water)\r\n")
        (skills / "game.md").write_bytes("Lore\nSea".encode("utf-8-sig"))
        (skills / "battle.md").write_bytes(b"Attacks\r\nare verbs.")
        pack = _context_pack(self.root)
        self.assertEqual(
            [pack[key]["text"] for key in ("glossary", "game")]
            + [row["text"] for row in pack["overlays"]],
            ["水 (Water)\n", "Lore\nSea", "Attacks\nare verbs."],
        )
        before = {key: value for key, value in pack.items() if key != "content_sha256"}
        for document in (before["glossary"], before["game"], *before["overlays"]):
            raw = (self.root / document["path"]).read_bytes()
            document["text"] = raw.decode("utf-8")
        self.assertIn(
            _sha256(_canonical_bytes(before)), context_digests(pack, self.root)
        )
        (skills / "quirks.md").write_bytes("Keep honorifics.".encode("utf-16"))
        quirks = _context_pack(self.root)["quirks"]
        self.assertEqual(
            (quirks["status"], quirks["text"]), ("loaded", "Keep honorifics.")
        )

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
                # The editors show what a document requests don't carry is
                # for in place of its file.
                self.assertEqual(bool(document["description"]), not found.requests)
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

    def test_the_game_context_a_skills_move_left_under_its_old_name_is_read(self):
        # Moving the root skills folder into .dazedtl keeps translation.md's
        # name; the reader missed it there, so requests carried no game
        # context and Save guidance created game.md over it, empty.
        (self.root / ".dazedtl/skills").rmdir()
        (self.root / "skills").mkdir()
        (self.root / "skills/translation.md").write_text("Lore", encoding="utf-8")
        (self.root / "skills/battle.md").write_text("Battle", encoding="utf-8")
        battle = read(self.root)["custom:battle"]
        documents_save(
            self.root,
            {"custom:battle": {"revision": battle["revision"], "text": "Duel"}},
        )
        self.assertTrue((self.root / ".dazedtl/skills/translation.md").is_file())
        game = read(self.root)["game"]
        self.assertEqual((game["state"], game["text"]), ("saved", "Lore"))
        self.assertEqual(documents(self.root)["game"]["text"], "Lore")

    def test_a_save_a_folder_refuses_writes_nothing(self):
        # Two skills folders refuse a skill's save, which wrote the glossary
        # before the skills' place was asked for, so half the set saved.
        (self.root / "skills").mkdir()
        (self.root / "skills/battle.md").write_text("Battle", encoding="utf-8")
        self.file("quirks").write_text("Quirks", encoding="utf-8")
        found = read(self.root)
        with self.assertRaisesRegex(RuntimeError, "skills folders"):
            documents_save(
                self.root,
                {
                    "glossary": {
                        "revision": found["glossary"]["revision"],
                        "text": "Lili (リリ)",
                    },
                    "quirks": {"revision": found["quirks"]["revision"], "text": "New"},
                },
            )
        self.assertEqual(read(self.root)["glossary"]["state"], "missing")

    def test_start_over_lets_go_of_every_file_holding_a_document(self):
        # A portable file beside its legacy one reads as unreadable, and
        # Start over moved aside only the first, so the guidance the user
        # let go came back from the legacy file.
        from dazedtl.translation.start_over import run

        self.file("quirks").write_text("Portable", encoding="utf-8")
        (self.root / "translation_quirks.txt").write_text("Legacy", encoding="utf-8")
        documents = read(self.root)
        self.assertEqual(documents["quirks"]["state"], "unreadable")
        with TemporaryDirectory() as workspace:
            run(
                workspace,
                "game",
                self.root,
                {},
                documents,
                False,
                configured=False,
                stopped=lambda: False,
                progress=lambda *_: None,
            )
        self.assertEqual(read(self.root)["quirks"]["state"], "missing")

    def test_a_linked_skills_folder_is_read_as_unreadable_and_left_where_it_is(self):
        # A linked skills folder failed the whole read, so no editor opened;
        # read past it, its custom skills went unlisted, so requests left
        # them out unsaid, and Start over moved its files out of the folder
        # outside the game.
        from dazedtl.translation.start_over import run

        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        self.addCleanup(shutil.rmtree, outside)
        (outside / "quirks.md").write_text("Someone else's", encoding="utf-8")
        (outside / "battle.md").write_text("Someone else's", encoding="utf-8")
        skills = self.root / ".dazedtl/skills"
        skills.rmdir()
        skills.symlink_to(outside)
        found = read(self.root)
        self.assertEqual(
            {name: document["state"] for name, document in found.items()},
            {
                "glossary": "missing",
                "quirks": "unreadable",
                "game": "unreadable",
                "notes": "missing",
                "custom:battle": "unreadable",
            },
        )
        self.assertIn("link", found["custom:battle"]["reason"])
        with self.assertRaisesRegex(ValueError, "link"):
            documents(self.root)
        # Its missing game context read as missing, so every Save guidance
        # created it, writing the notes, then failing on the link.
        with self.assertRaisesRegex(ValueError, "link"):
            documents_save(
                self.root,
                {
                    "notes": {"revision": "", "text": "Mine"},
                    "game": {"revision": "", "text": ""},
                },
            )
        self.assertFalse((self.root / "AGENTS.md").exists())
        with TemporaryDirectory() as workspace:
            run(
                workspace,
                "game",
                self.root,
                {},
                found,
                False,
                configured=False,
                stopped=lambda: False,
                progress=lambda *_: None,
            )
        self.assertEqual(
            sorted(path.name for path in outside.iterdir()), ["battle.md", "quirks.md"]
        )

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
            # A notes save that also brought .gitignore's rules up to date,
            # which Go back leaves as well.
            entry("rules", ["AGENTS.md", ".gitignore"]),
            entry("map", ["Map001.json"]),
            entry("target", ["Map001.json"]),
        ]
        self.assertEqual(_taken_out(entries), {"map": "back"})
