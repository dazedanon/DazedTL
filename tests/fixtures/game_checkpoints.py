"""Real Git journeys for a game's checkpoints: every write DazedTL makes is
one commit naming its action and stage, edits made outside DazedTL get their
own first, a failed or stopped write commits nothing, two writes at once each
commit only their own, and the Checkpoints tab and History undo through them."""

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))
sys.path.insert(0, str(root / "backend"))

from dazedtl.compatibility.checkpoint_commits import Change, for_action, running
from dazedtl.compatibility.game_write import write_game
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.languages import DEFAULT_SOURCE
from dazedtl.settings import language_pair
from dazedtl.translation.project import DEFAULTS
from desktop.backend.project import digest
from util.game_settings import save_game_wrap_widths
from util.len_git import setup_git
from util.len_translation import LenProject
from util.version_update import GitWorkflowError


def git(game, *arguments):
    return subprocess.run(
        ["git", "-C", str(game), *arguments],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    ).stdout


def game(name):
    folder = temporary / name
    shutil.copytree(root / "tests/fixtures/mz-game", folder)
    return folder


def save(folder):
    return setup_git(LenProject(folder), version="1.0", current_is_untranslated=True)


engine = TranslationEngine(temporary / "profile")
kept = game("checkpoints")
# Saving context and Copy starting prompt change only DazedTL's own folder,
# which no record holds, so they record nothing: recording a big game froze
# the app for minutes. A save that moves a legacy root file into it records
# the game first.
prompted = game("prompted")
with engine.context():
    engine.document_save(kept, "game", digest(b""), "Theme - test\n")
    # Copy starting prompt records the game's languages, then prepares.
    language_pair.choose(prompted, DEFAULT_SOURCE, "English")
    engine.prepare(prompted, DEFAULTS)
for unrecorded in (kept, prompted):
    assert not (unrecorded / ".git").exists(), unrecorded
    assert not (unrecorded / ".gitignore").exists(), unrecorded
legacy = game("legacy-glossary")
(legacy / "glossary.txt").write_text("勇者 (Hero)\n", encoding="utf-8")
with engine.context():
    glossary = engine.documents(legacy)["glossary"]["revision"]
    engine.document_save(legacy, "glossary", glossary, "勇者 (Hero)\n")
from dazedtl.compatibility import original_files

[found] = original_files.records(legacy)
assert "glossary.txt" in original_files.files(legacy, found.commit)
engine.audit_scope(kept, {"files": {"data/Map001.json": {}, "data/Items.json": {}}})
save(kept)
base = git(kept, "rev-parse", "HEAD").strip()
trailers = "%(trailers:key={},valueonly,separator=)"


def history():
    shown = "%s|" + trailers.format("DazedTL-Action") + "|"
    shown += trailers.format("DazedTL-Stage")
    return git(kept, "log", "--format=" + shown, base + "..HEAD").splitlines()


def changed(ref="HEAD"):
    return git(kept, "diff-tree", "--no-commit-id", "--name-only", "-r", ref).split()


def clean():
    assert not git(kept, "status", "--porcelain"), git(kept, "status")


def write(name, raw, **options):
    with write_game(kept, paths=[name], **options) as written:
        written.put(name, raw)


# Translate's Apply and QA's apply, as the worker runs them.
for action in ("export_selected", "qa_apply"):
    with running(for_action(action)):
        write("data/Map001.json", b'{"by": "%s"}' % action.encode())
    clean()
# A Plugin files apply, whose plugin joins the patch.
write(
    "js/plugins/TitleMessage.js",
    b"// English\n",
    summary="Apply plugin file changes",
    stage="Translate",
)
clean()
assert "js/plugins/TitleMessage.js" in git(kept, "ls-files").split()
# Saving Guided options keeps the Line widths a game already uses, its
# engine's stock ones while it has none saved, implicit: they once became a
# "Save Line widths" checkpoint the user never asked for.
from util.game_settings import DEFAULT_WRAP_WIDTHS, wrap_widths_saved

assert wrap_widths_saved(kept, DEFAULT_WRAP_WIDTHS)
assert not wrap_widths_saved(kept, {**DEFAULT_WRAP_WIDTHS, "width": 64})
# Line widths, which the game's settings keep, named or not.
with write_game(kept, pack=False, summary="Save Line widths", stage="Context"):
    save_game_wrap_widths(kept, {"width": 60})
clean()
assert history()[::-1] == [
    "Translate: Apply selected saved outputs|export_selected|Translate",
    "Check: Apply QA corrections|qa_apply|Check",
    "Translate: Apply plugin file changes||Translate",
    "Context: Save Line widths||Context",
], history()
# One Save guidance click is one checkpoint, named by the documents it saved.
from types import SimpleNamespace

from dazedtl.translation.guided import Guided
from desktop.backend.guidance import documents, documents_save

current = documents(kept)
Guided.save_guidance(
    SimpleNamespace(
        backend=SimpleNamespace(
            game_write=lambda source, _id, **options: write_game(source, **options),
            workflows=SimpleNamespace(
                documents_save=lambda _id, changes: documents_save(kept, changes)
            ),
        )
    ),
    {"source": str(kept), "id": "native"},
    {
        name: {"revision": current[name]["revision"], "text": text}
        for name, text in (("glossary", "薬 (Potion)"), ("quirks", "Plain."))
    },
)
clean()
assert history()[0] == "Context: Save Glossary, Style & quirks||Context", history()
assert changed() == [".dazedtl/glossary.txt", ".dazedtl/skills/quirks.md"]
# A hand edit goes in its own checkpoint before the Apply's.
(kept / "data/Items.json").write_text("[null]\n")
with running(for_action("export_selected")):
    write("data/Map001.json", b'{"by": "a second apply"}')
clean()
assert history()[1] == "Edits made outside DazedTL|outside_edits|", history()
assert changed("HEAD~1") == ["data/Items.json"] and changed() == ["data/Map001.json"]
head = git(kept, "rev-parse", "HEAD")
for failure in (ValueError("Refused."), InterruptedError("Stopped.")):
    try:
        with write_game(kept, paths=["data/Map001.json"]) as written:
            written.put("data/Map001.json", b'{"by": "a failed write"}')
            raise failure
    except type(failure):
        pass
    assert git(kept, "rev-parse", "HEAD") == head, failure
    git(kept, "checkout", "--", "data/Map001.json")
# An index lock a crashed Git left fails the write before its checkpoint, never
# after: the branch once moved and the write still failed, so its receipt never
# named the checkpoint.
from util.version_update import git_workflow

stale = kept / ".git/index.lock"
stale.write_bytes(b"")
try:
    with patch.object(git_workflow, "INDEX_LOCK_WAIT", 0.2):
        write("data/Map001.json", b'{"by": "a write over a stale lock"}')
except GitWorkflowError as error:
    assert "index.lock" in str(error), error
else:
    raise AssertionError("A write committed over a stale index lock.")
finally:
    stale.unlink()
assert git(kept, "rev-parse", "HEAD") == head
git(kept, "checkout", "--", "data/Map001.json")
clean()
# A context save over that lock writes the glossary, then fails at its
# checkpoint, leaving a draft that holds the revision from before the write.
# Saving the draft again once the lock is gone must succeed: the file holds
# its text, so it was refused as a conflict with the failed save's own write.
draft = engine.documents(kept)["glossary"]
stale.write_bytes(b"")
try:
    with patch.object(git_workflow, "INDEX_LOCK_WAIT", 0.2):
        engine.document_save(kept, "glossary", draft["revision"], "水 (Water)\n")
except GitWorkflowError as error:
    assert "index.lock" in str(error), error
else:
    raise AssertionError("A guidance save committed over a stale index lock.")
finally:
    stale.unlink()
assert engine.documents(kept)["glossary"]["text"] == "水 (Water)"
saved = engine.document_save(kept, "glossary", draft["revision"], "水 (Water)\n")
assert saved["glossary"]["text"] == "水 (Water)", saved
clean()
assert ".dazedtl/glossary.txt" in git(kept, "ls-files").split()
# A real conflict, other text in the file, is still refused, and so is a
# revision of a document the game has no file for.
for name, revision, text in (
    ("glossary", draft["revision"], "薬 (Elixir)"),
    ("custom:nothing", "stale", ""),
):
    try:
        engine.document_save(kept, name, revision, text)
    except ValueError as error:
        assert "changed on disk" in str(error), error
    else:
        raise AssertionError(f"A guidance save of {name} was not refused.")
clean()
meeting = threading.Barrier(2)
errors = []


def alongside(name):
    try:
        with write_game(kept, paths=[name], summary="Write " + name) as written:
            meeting.wait(10)
            written.put(name, b'["written alongside"]')
            meeting.wait(10)
    except Exception as error:
        errors.append(error)


writers = [
    threading.Thread(target=alongside, args=(name,))
    for name in ("data/Map001.json", "data/Items.json")
]
for writer in writers:
    writer.start()
for writer in writers:
    writer.join()
assert not errors, errors
clean()
assert sorted([changed(), changed("HEAD~1")]) == [
    ["data/Items.json"],
    ["data/Map001.json"],
], history()
# An assistant's older git-scope with a shorter manifest keeps the files
# DazedTL's checkpoints let into the patch.
from util.len_patch_scope import sync_patch_scope

scoped = sync_patch_scope(LenProject(kept), ["data/Map001.json"], dry_run=True)
assert not scoped["untrack"], scoped
# An assistant's phase: its writes of one file each wait, and the phase's
# report saves them with the assistant's own edits as one checkpoint; a write
# of the app's own first saves the writes still waiting as their phase's.
from dazedtl.compatibility.checkpoint_commits import in_phase
from dazedtl.compatibility.checkpoint_commits import save as save_phase

injection = Change("Injection", "Assistant-led", "assistant_phase")
head = git(kept, "rev-parse", "HEAD")
with in_phase(injection):
    for name in ("data/Map001.json", "data/Items.json"):
        write(name, b'["the assistant\'s"]')
assert git(kept, "rev-parse", "HEAD") == head
(kept / "js/plugins/TitleMessage.js").write_text("// The assistant's own edit\n")
save_phase(kept, injection)
clean()
assert history()[0] == "Assistant-led: Injection|assistant_phase|Assistant-led"
assert changed() == [
    "data/Items.json",
    "data/Map001.json",
    "js/plugins/TitleMessage.js",
]
with in_phase(injection):
    write("data/Map001.json", b'["the assistant\'s again"]')
write("data/Items.json", b"[]", summary="Apply plugin file changes", stage="Translate")
clean()
assert history()[:2] == [
    "Translate: Apply plugin file changes||Translate",
    "Assistant-led: Injection|assistant_phase|Assistant-led",
], history()
assert changed("HEAD~1") == ["data/Map001.json"] and changed() == ["data/Items.json"]
# The Checkpoints tab. An undo waits for a later checkpoint that changed the
# same file, and an undo undone in turn never blocks it again.
from dazedtl.compatibility import checkpoint_history as checkpoints


def tip():
    return git(kept, "rev-parse", "HEAD").strip()


def listed():
    return [
        row
        for version in checkpoints.timeline(kept)["versions"]
        for row in version["checkpoints"]
    ]


before_first = (kept / "data/Items.json").read_bytes()
# Two messages, each after its face, the first translated into fewer rows
# than its source.
FIRST = '["Actor1", "村長", "おお、ミカよ。", "森の奥に杖がある。", "Actor1", "ミカ"]'.encode()
SECOND = (
    b'["Actor1", "Elder", "Oh, Mika. A staff lies in the forest.", "Actor1", "Mika"]'
)
write("data/Items.json", FIRST, summary="First", stage="Translate")
first = tip()
write("data/Items.json", SECOND, summary="Second", stage="Translate")
second = tip()
rows = {row["commit"]: row for row in listed()}
assert rows[second]["current"] and rows[second]["group"] == "Translate", rows[second]
assert rows[first]["blocker"] == {
    "commit": second,
    "title": "Second",
    "files": ["data/Items.json"],
}, rows[first]
try:
    checkpoints.undo(kept, first)
except ValueError as reason:
    assert "“Second” first; it also changed Items.json" in str(reason), reason
else:
    raise AssertionError("An undo took out a later checkpoint's change.")
assert tip() == second
shown = checkpoints.changes(kept, second)
assert shown["file_changes"] == [
    {"path": "data/Items.json", "change": "Changed", "result": ""}
], shown
assert [
    (line["before"], line["after"]) for line in shown["text"]["files"][0]["lines"]
] == [
    ("村長", "Elder"),
    ("おお、ミカよ。", "Oh, Mika. A staff lies in the forest."),
    ("森の奥に杖がある。", None),
    ("ミカ", "Mika"),
], shown
checkpoints.undo(kept, second)
clean()
assert history()[0] == "Undid “Second”|checkpoint_undo|", history()
assert (kept / "data/Items.json").read_bytes() == FIRST
checkpoints.undo(kept, first)
clean()
assert (kept / "data/Items.json").read_bytes() == before_first
# Edits made outside DazedTL show until DazedTL's next change saves them,
# and an undo of the same file waits for them, as it would once saved.
(kept / "data/Items.json").write_text("[null]\n")
assert checkpoints.timeline(kept)["outside"] == ["data/Items.json"]
assert listed()[0]["blocker"] == {
    "commit": "",
    "title": "Edits made outside DazedTL",
    "files": ["data/Items.json"],
}, listed()[0]
# Going back puts a file the patch didn't hold then to the original game's
# bytes, here a plugin the patch took in later, which stays in it; the
# `original` branch holds only the patch, so they come from the game's record
# of its original files, which the first write made before setup. The
# glossary is DazedTL's, so going back to before it removes it; going back
# and undoing it once did nothing, as if it were an unknown original file.
plugin = "js/plugins/TitleMessage.js"
oldest = listed()[-2]
assert oldest["title"] == "Apply selected saved outputs", oldest
assert listed()[-1]["title"] == "Set up the game at version 1.0", listed()
native = (root / "tests/fixtures/mz-game" / plugin).read_bytes()
assert plugin not in git(kept, "ls-tree", "-r", "--name-only", "original").split()
[found] = original_files.records(kept)
assert found.kind == original_files.FOUND, found
recorded = original_files.files(kept, found.commit)
# The game as found, before the write that gave it DazedTL's ignore rules.
assert plugin in recorded and ".gitignore" not in recorded, sorted(recorded)
assert "refs/dazedtl/originals" not in git(kept, "for-each-ref", "refs/heads")
# A game update that came as a patch is laid over the game's record, so the
# next version's record still holds every file the patch leaves out.
patched = temporary / "patched-release"
(patched / "data").mkdir(parents=True)
(patched / "data/System.json").write_text('{"gameTitle": "1.1"}')
update = original_files.record(
    kept, original_files.PREPARED, "1.1", folder=patched, over=found.commit
)
laid = original_files.files(kept, update)
assert set(laid) == set(recorded) and laid[plugin] == recorded[plugin], laid
assert laid["data/System.json"] != recorded["data/System.json"], laid
checkpoints.go_back(kept, oldest["commit"])
clean()
assert history()[0] == "Went back to “Apply selected saved outputs”|checkpoint_back|", (
    history()
)
assert history()[1] == "Edits made outside DazedTL|outside_edits|", history()
# The rows a go back took out carry its mark; the target and older stay clear.
rows = [
    row
    for version in checkpoints.timeline(kept)["versions"]
    for row in version["checkpoints"]
]
back = rows[0]["commit"]
index = next(i for i, row in enumerate(rows) if row["commit"] == oldest["commit"])
marked = [row["commit"] for row in rows if row["taken_out_by"]]
assert marked and {row["taken_out_by"] for row in rows} == {"", back}, rows
assert rows[index]["taken_out_by"] == "", rows[index]
assert all(not row["taken_out_by"] for row in rows[index:]), rows
assert (kept / plugin).read_bytes() == native
assert plugin in git(kept, "ls-files").split()
assert not (kept / ".dazedtl/glossary.txt").exists()
assert (kept / "data/Map001.json").read_bytes() == b'{"by": "export_selected"}'
# Save a copy: the game as of a checkpoint, in a new folder outside it.
copies = temporary / "copies"
copies.mkdir()
saved = checkpoints.save_copy(kept, second, copies)
copy = Path(saved["folder"])
assert copy.parent == copies and copy.name.startswith("checkpoints (1.0, "), copy
assert (copy / "data/Items.json").read_bytes() == SECOND
assert (copy / "data/Map001.json").read_text() == git(
    kept, "show", second + ":data/Map001.json"
)
assert (copy / plugin).read_text() == git(kept, "show", f"{second}:{plugin}")
assert not (copy / ".git").exists() and not (copy / ".dazedtl/backups").exists()
assert Path(checkpoints.save_copy(kept, second, copies)["folder"]).name.endswith(" 2")
clean()
try:
    checkpoints.save_copy(kept, second, kept / "data")
except ValueError as reason:
    assert "outside the game" in str(reason), reason
else:
    raise AssertionError("A copy went inside the game.")
# History undoes a text batch through its checkpoint: its receipt names the
# checkpoint and keeps no copy, the undo is a checkpoint of its own, and the
# batch then reads restored with its applied-output entries back.
from dazedtl.translation import checkpoint_records, publication

texts = temporary / "texts"
texts.mkdir()
records = checkpoint_records.Records(kept, publications=texts)
items = "data/Items.json"
before_qa = (kept / items).read_bytes()
with running(for_action("qa_apply")):
    plan = publication.freeze(texts, kept, {items: b'["QA wording"]'}, "qa_apply")
    applied = publication.publish(texts, kept, plan)["publication"]
clean()
[record] = publication.records(texts)
assert (
    record["commit"] == tip()
    and record["parent"] == git(kept, "rev-parse", "HEAD~1").strip()
), record
assert sorted(
    path.name for path in (texts / "text-publications" / applied).iterdir()
) == ["receipt.json"]
publication.undo(texts, kept, applied, records)
clean()
assert history()[0] == "Undid “Apply QA corrections”|checkpoint_undo|", history()
assert (kept / items).read_bytes() == before_qa
assert [row["state"] for row in publication.history(texts)] == ["complete", "restored"]
# A restored batch still reads as undone through Git, so History keeps its
# Undo control, with its result, rather than offering a reviewed restore.
assert publication.undoes(publication.history(texts)[1])
try:
    publication.undo(texts, kept, applied, records)
except ValueError as reason:
    assert "Choose an applied or interrupted batch" in str(reason), reason
else:
    raise AssertionError("A restored batch was undone again.")
# A batch that stopped midway made no checkpoint: its files go back as the
# checkpoint it started from had them, once they still hold either side.
with running(for_action("qa_apply")):
    plan = publication.freeze(texts, kept, {items: b'["Stopped"]'}, "qa_apply")
    try:
        with patch.object(
            publication, "write_json", side_effect=KeyboardInterrupt("stopped")
        ):
            publication.publish(texts, kept, plan)
    except KeyboardInterrupt:
        pass
[stopped] = [row for row in publication.records(texts) if row["id"] == plan["id"]]
assert stopped["state"] == "reviewed", stopped
path = texts / "text-publications" / plan["id"] / "receipt.json"
stopped.update(state="publishing", parent=tip())
publication.write_json(path, stopped)
(kept / items).write_bytes(b'["Stopped"]')
(kept / "data/Map001.json").write_bytes(b'{"by": "a hand edit"}')
publication.undo(texts, kept, plan["id"], records)
assert (kept / items).read_bytes() == before_qa
assert (kept / "data/Map001.json").read_bytes() == b'{"by": "a hand edit"}'
assert history()[0] == "Restored an interrupted text batch|checkpoint_undo|", history()
# The Checkpoints tab's undo takes the batch of the checkpoint it undoes out
# too, as History's does, so History and Text QA read it restored and its
# applied-output entries go back; undoing that undo brings it back.


def outputs():
    return publication.read_json(texts / "applied-outputs.json")["files"]


def batch(identity):
    return next(
        row["state"] for row in publication.history(texts) if row["id"] == identity
    )


with running(for_action("qa_apply")):
    plan = publication.freeze(
        texts, kept, {items: b'["Undone here"]'}, "qa_apply", outputs={items: "qa"}
    )
    publication.publish(texts, kept, plan)
[record] = [row for row in publication.records(texts) if row["id"] == plan["id"]]
assert outputs() == {items: "qa"}, outputs()
undone = checkpoint_records.undo(records, record["commit"])
assert batch(plan["id"]) == "restored" and outputs() == {}, outputs()
assert (kept / items).read_bytes() == before_qa
checkpoint_records.undo(records, undone["commit"])
assert batch(plan["id"]) == "complete" and outputs() == {items: "qa"}, outputs()
# Undoing an undo names the change it redoes, not each undo inside the next.
assert history()[0] == "Redid “Apply QA corrections”|checkpoint_undo|", history()
assert (kept / items).read_bytes() == b'["Undone here"]'
# Going back to before the batch takes out it and both undos at once.
checkpoint_records.go_back(records, record["parent"])
clean()
assert batch(plan["id"]) == "restored" and outputs() == {}, outputs()
assert (kept / items).read_bytes() == before_qa
# Going back past Save Line widths gives the Guided project the widths the
# game uses again, once, for Line widths to read; it kept the widths taken
# out, so saving them again fitted nothing.
from util.game_settings import game_wrap_widths

used = game_wrap_widths(kept)
before_widths = tip()
with write_game(kept, pack=False, summary="Save Line widths", stage="Context"):
    save_game_wrap_widths(kept, {**used, "width": 44})
updates = []
guided = SimpleNamespace(
    record=lambda _id: (
        None,
        {"id": "native", "revision": 3, "widths": {}, "source": str(kept)},
    ),
    backend=SimpleNamespace(
        workflows=SimpleNamespace(
            folder=lambda _id: texts, update=lambda *call: updates.append(call)
        )
    ),
)
Guided.restored_widths(guided, "project")
checkpoint_records.go_back(records, before_widths)
for _ in range(2):
    Guided.restored_widths(guided, "project")
assert updates == [("native", 3, {"widths": used})], updates
# Widths saved after the restore stay the project's.
with write_game(kept, pack=False, summary="Save Line widths", stage="Context"):
    save_game_wrap_widths(kept, {**used, "width": 44})
checkpoint_records.go_back(records, before_widths)
save_game_wrap_widths(kept, {**used, "width": 50})
Guided.restored_widths(guided, "project")
assert len(updates) == 1, updates
assert not checkpoint_records.restored_widths(texts)
git(kept, "checkout", "--", ".")
# A batch that wrote every file but whose write then failed, here at its
# checkpoint, as a failed pack or a stop also leave it, made no checkpoint and
# kept no copies; History once had no way to undo it.
from dazedtl.compatibility.checkpoint_commits import Checkpoint

with running(for_action("qa_apply")):
    plan = publication.freeze(texts, kept, {items: b'["Not recorded"]'}, "qa_apply")
    try:
        with patch.object(Checkpoint, "record", side_effect=ValueError("No commit.")):
            publication.publish(texts, kept, plan)
    except ValueError:
        pass
    else:
        raise AssertionError("A write whose checkpoint failed succeeded.")
[failed] = [row for row in publication.records(texts) if row["id"] == plan["id"]]
assert failed["state"] == "complete" and "commit" not in failed, failed
publication.undo(texts, kept, plan["id"], records)
clean()
assert batch(plan["id"]) == "restored" and (kept / items).read_bytes() == before_qa
# A file name that isn't UTF-8, as unzip leaves Shift-JIS names on Linux,
# goes to Git as its own bytes and comes back as the same file: every write
# to such a game once failed while recording its original files.
if os.name != "nt":
    picture = os.fsdecode(b"img/pictures/\x82\xa0.png")
    unzipped = game("unzipped")
    (unzipped / picture).write_bytes(b"Japanese")
    with write_game(unzipped, paths=[items]) as written:
        written.put(items, b"[]")
    [found] = original_files.records(unzipped)
    _mode, blob, size = original_files.files(unzipped, found.commit)[picture]
    copied = temporary / "unzipped-copy"
    original_files.write(unzipped, [(blob, picture, size)], copied, lambda: False)
    assert (copied / picture).read_bytes() == b"Japanese"
    # A checkpoint takes the file in and its undo puts its bytes back.
    write(picture, b"First")
    write(picture, b"Second")
    checkpoints.undo(kept, tip())
    clean()
    assert (kept / picture).read_bytes() == b"First"
    assert sorted(os.listdir(kept / "img/pictures")) == sorted(
        ["sign.png", os.path.basename(picture)]
    ), os.listdir(kept / "img/pictures")
# Install Forge, as Playtest tools runs it, names no files, yet its plugin
# joins the patch with the plugins.js loading it: the checkpoint once took
# only plugins.js, so the published patch stopped players' game at start.
from util.forge import installer as forge

forged = game("forge")
engine.audit_scope(forged, {"files": {"data/Map001.json": {}, "js/plugins.js": {}}})
save(forged)
with running(for_action("forge_install")), write_game(forged, pack=False):
    assert forge.install(forged, cfg={"forgeHotkey": "F10"})[0]
assert not git(forged, "status", "--porcelain"), git(forged, "status")
assert {"js/plugins.js", "js/plugins/Forge_MZ.js"} <= set(
    git(forged, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").split()
)
print("ok")
