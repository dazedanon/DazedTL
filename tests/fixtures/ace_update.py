"""A translated VX Ace game through its version history: its patch carries
the game's data but never the ace_json DazedTL edits, and an encrypted new
release is prepared as Set up prepares the game, so updating keeps the
translation."""

import json
import shutil
import sys
import zipfile
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))
sys.path.insert(0, str(root / "backend"))

from dazedtl.compatibility import original_files
from dazedtl.compatibility.game_write import write_game
from dazedtl.compatibility.guided import runtime_files
from dazedtl.compatibility.translation import TranslationEngine
from dazedtl.translation.files import evidence
from dazedtl.translation.operations import execute
from dazedtl.translation.release import packing_paths
from util.ace import actions, rgssad
from util.version_update.release_layout import inspect_release

from tests.rgssad_archives import archive_v3
from tests.test_ace_conversion import files

FIXTURE = root / "tests/fixtures/ace"
TRANSLATED = json.loads(
    (FIXTURE / "translated/Actors.json").read_text(encoding="utf-8")
)
options = {
    "mode": "agent",
    "include_images": False,
    "instructions": "",
    "include_glossary_base": False,
    "install_forge": False,
}
(temporary / "profile").mkdir()
engine = TranslationEngine(temporary / "profile")
workspace = temporary / "workspace"
job = {"project_id": "ace", "id": "a" * 32}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edited(path, change):
    value = read(path)
    change(value)
    return json.dumps(value, ensure_ascii=False, indent=4).encode()


def operation(action, **arguments):
    plan = {"source": str(game), "options": options, "action": action}
    return execute(
        engine, workspace, job, {**plan, "arguments": arguments}, lambda: False
    )


def displayed(data, name):
    """A map's display name as the game reads it from its Data."""
    folder = temporary / "read"
    shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(data, folder / "Data")
    actions.run(folder, "ace_extract", log=lambda _line: None)
    return read(folder / f"ace_json/{name}.json")["displayName"]


# Set up: the patch is the game's Data, and the original game, converted, is
# recorded before the baseline.
game = temporary / "game"
for name in ("Data", "ace_json"):
    shutil.copytree(FIXTURE / name, game / name)
# What runs the game, which no data patch carries.
RUNTIME = {
    "Game.exe": b"exe",
    "Game.ini": b"[Game]\r\nLibrary=System\\RGSS301.dll\r\nTitle=Test\r\n",
    "System/RGSS301.dll": b"dll",
    "Audio/SE/Bell.ogg": b"ogg",
    "Fonts/Font.ttf": b"ttf",
}
for name, data in RUNTIME.items():
    (game / name).parent.mkdir(parents=True, exist_ok=True)
    (game / name).write_bytes(data)
engine.rpgmaker_prepare(game, options)
engine.audit_scope(game, {"files": {name: {} for name in runtime_files(game)}})
original_files.record(game, original_files.PREPARED, "1.0")
engine.git_setup(game, options, "1.0", "", True)

# Applying translations writes ace_json and packs it into Data, and each
# checkpoint lets the ace_json it wrote into the patch.
with write_game(game) as written:
    written.put(
        "ace_json/Actors.json", json.dumps(TRANSLATED, ensure_ascii=False).encode()
    )
    written.put(
        "ace_json/Map001.json",
        edited(
            game / "ace_json/Map001.json", lambda map: map.update(displayName="Village")
        ),
    )
native = {"source": str(game), "data": str(game / "ace_json"), "engine": "ACE"}
# Release built its patch from the runtime files and packing's inputs, which
# 2.27.0 refused as duplicates once ace_json joined the patch; the patch
# carries Data, never ace_json, whatever an older .gitattributes says.
patch = runtime_files(game)
assert not [name for name in patch if name.startswith("ace_json/")], patch
evidence(game, [*patch, *packing_paths(native)])
assert "/ace_json export-ignore" in (game / ".gitattributes").read_text(
    encoding="utf-8"
)
(game / ".gitattributes").write_text("/.dazedtl export-ignore\n", encoding="utf-8")
with write_game(game, pack=False):
    pass
built = engine.package(
    game, options, {"files": {}}, temporary / "deliveries", updater=False
)
names = zipfile.ZipFile(built["path"]).namelist()
assert "Data/Actors.rvdata2" in names and not [
    name for name in names if name.startswith("ace_json/")
], names
# The repository's description files are not the game either.
assert not {".gitignore", ".gitattributes", "README.md"} & set(names), names

# Version 1.1 comes encrypted, as every shipped Ace game does: it changes the
# translated map and an untranslated item.
v11 = temporary / "v11"
for name in ("Data", "ace_json"):
    shutil.copytree(FIXTURE / name, v11 / name)
(v11 / "ace_json/Map001.json").write_bytes(
    edited(v11 / "ace_json/Map001.json", lambda map: map.update(note="新しいメモ"))
)
(v11 / "ace_json/Items.json").write_bytes(
    edited(v11 / "ace_json/Items.json", lambda items: items[1].update(name="エーテル"))
)
actions.run(v11, "ace_pack", log=lambda _line: None)
release = temporary / "release"
release.mkdir()
archive = archive_v3(
    [("Data\\" + name, data) for name, data in files(v11 / "Data").items()], seed=11
)
(release / "Game.rgss3a").write_bytes(archive)
# A release with the game's Game.exe and RGSS library is a complete game; one
# without them is a patch, however much of the game its archive or Data holds,
# since replacing the game with it would remove what runs it.
complete = temporary / "complete"
shutil.copytree(release, complete)
for name, data in RUNTIME.items():
    (complete / name).parent.mkdir(parents=True, exist_ok=True)
    (complete / name).write_bytes(data)
assert inspect_release(game, complete).detected == "game", inspect_release(
    game, complete
)
data_patch = temporary / "data-patch"
shutil.copytree(v11 / "Data", data_patch / "Data")
assert inspect_release(game, data_patch).detected == "patch"
# The usual update is the new archive alone. 2.27.1's fix took it for a
# complete game, which removed Game.exe, the library, Audio and Fonts; before
# that a patch put the archive beside the translated Data, which the game then
# read instead, and 2.27.0 staged a complete one unprepared, which removed
# every data file and ace_json.
assert inspect_release(game, release).detected == "patch", inspect_release(
    game, release
)
staged = operation("stage_update", official=str(release), version="1.1")
assert staged["patch"] and not staged["preparation_required"], staged
official = Path(staged["official"])
# Staging converts the patch as Set up converted the game.
assert rgssad.archives(official) == [] and (official / "ace_json/System.json").is_file()
preview = operation(
    "version_preview", official=str(official), version="1.1", patch_overlay=True
)
assert not [
    change["path"]
    for change in preview["file_changes"]
    if change["change"] == "Removed"
], preview["file_changes"]
outcomes = {change["path"]: change["result"] for change in preview["file_changes"]}
# 2.27.0 compared with an original branch holding no ace_json, so the
# release's replaced each translated file.
assert "Translated file replaced by official file" not in outcomes.values(), outcomes
assert outcomes["ace_json/Map001.json"] == "Merged with translation edits", outcomes
# The update packs a data file both changed from the merged ace_json, and
# keeps the release's archive for patches; the preview says both.
assert (
    outcomes["Data/Map001.rvdata2"] == "Packed from the merged text after the update"
), outcomes
assert outcomes["Game.rgss3a"] == "Replaces the archive kept for patches", outcomes
applied = operation(
    "version_apply",
    official=str(official),
    version="1.1",
    preview=preview,
    patch_overlay=True,
)
assert applied["complete"], applied
assert rgssad.archives(game) == []
# Packing writes the title into Game.ini; the rest of the runtime stays.
for name, data in RUNTIME.items():
    if name != "Game.ini":
        assert (game / name).read_bytes() == data, name
assert read(game / "ace_json/Actors.json") == TRANSLATED
merged = read(game / "ace_json/Map001.json")
assert (merged["displayName"], merged["note"]) == ("Village", "新しいメモ"), merged
assert read(game / "ace_json/Items.json")[1]["name"] == "エーテル"
# Git can't merge the map's data, which both changed, so the update packs
# it from the merged ace_json; patches rebuild the new version's archive.
assert displayed(game / "Data", "Map001") == "Village"
assert (game / ".dazedtl/ace/Game.rgss3a").read_bytes() == archive
