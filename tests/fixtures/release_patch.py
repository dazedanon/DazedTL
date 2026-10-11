"""A developer's patch copied over a translated game through its version
history: the game keeps every file the patch leaves out and every translation
the patch doesn't change."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))
sys.path.insert(0, str(root / "backend"))

from util.dazedformat import format_json_files
from util.len_git import setup_git
from util.len_translation import LenProject
from util.project_preparation import prepare_rpgmaker_patch
from util.version_update import apply_official_update, preview_official_update
from util.version_update.release_layout import inspect_release, stage_release
from util.version_update.text_changes import text_changes

fixture = root / "tests/fixtures/mz-game"
TRANSLATED = "Oh, Mika. Thank you for coming."


def lines(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        command["parameters"][0]
        for event in data["events"]
        if event
        for command in event["pages"][0]["list"]
        if command["code"] == 401
    ]


# A prepared, translated game: formatted data, a baseline, one translated line.
game = temporary / "game"
shutil.copytree(fixture, game)
format_json_files(game / "data")
setup_git(LenProject(game), version="1.0", current_is_untranslated=True)
map001 = game / "data/Map001.json"
map001.write_text(
    map001.read_text(encoding="utf-8").replace(
        "おお、ミカよ。よく来てくれた。", TRANSLATED
    ),
    encoding="utf-8",
)
subprocess.run(
    [
        "git",
        "-C",
        str(game),
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qam",
        "translation: fixture line",
    ],
    check=True,
)

# The developer ships the changed map minified, inside an extra folder with a
# readme beside it, under folder and file names cased differently from the game.
release = temporary / "release"
inner = release / "魔法の杖 Ver1.01 修正パッチ"
(inner / "Data").mkdir(parents=True)
(release / "readme.txt").write_text("Copy the folder over the game.\n")
data = json.loads((fixture / "data/Map001.json").read_text(encoding="utf-8"))
page = next(event for event in data["events"] if event)["pages"][0]["list"]
page.insert(2, {"code": 401, "indent": 0, "parameters": ["気をつけるのじゃぞ。"]})
(inner / "Data/map001.json").write_text(
    json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
)
data["displayName"] = "魔法の森"
(inner / "Data/Map002.json").write_text(
    json.dumps(data, ensure_ascii=False), encoding="utf-8"
)

inspection = inspect_release(game, release)
layout = inspection.layout()
assert inspection.detected == "patch" and inspection.version == "1.01", inspection
assert (layout.source, layout.target, layout.files, layout.replaced) == (
    inner.name,
    "",
    2,
    1,
), layout
assert layout.left_out == ("readme.txt",), layout
# The same folder taken as a complete game would remove the rest of the game.
assert (
    inspection.game.game_files - inspection.game.covered
    > inspection.game.game_files / 2
)
# A complete release is one, and a patch for an MV game's www folder finds it.
assert inspect_release(game, fixture).detected == "game"
mv = temporary / "mv"
shutil.copytree(fixture, mv / "www")
assert inspect_release(mv, release).patch.target == "www"

staged = temporary / "staged"
copy = temporary / "copy"
shutil.copytree(release, copy)
stage_release(game, copy, staged, layout)
assert sorted(
    path.relative_to(staged).as_posix() for path in staged.rglob("*.json")
) == [
    "data/Map001.json",
    "data/Map002.json",
], list(staged.rglob("*"))
prepare_rpgmaker_patch(staged, game)

preview = preview_official_update(game, staged, "1.01", patch_overlay=True)
assert not preview.deleted_paths, preview.deleted_paths
outcome = {change.path: change.result for change in preview.file_changes}
assert outcome["data/Map001.json"] == "Merged with translation edits", outcome
# The review's line view: the inserted line is new, the translation beside it stays.
text = {entry.path: entry for entry in text_changes(game, preview).files}
assert (text["data/Map001.json"].kept, text["data/Map001.json"].replaced) == (1, 0)
assert [(line.kind, line.after) for line in text["data/Map001.json"].lines] == [
    ("added", "気をつけるのじゃぞ。")
], text
assert text["data/Map002.json"].to_translate, text
result = apply_official_update(
    game,
    staged,
    "1.01",
    expected_tree=preview.proposed_tree,
    expected_original_commit=preview.original_commit,
    expected_translation_commit=preview.translation_commit,
    expected_asset_manifest=preview.proposed_asset_manifest,
    expected_baseline_asset_manifest=preview.baseline_asset_manifest,
    patch_overlay=True,
)
assert result.complete, result
own = sorted(
    path.relative_to(fixture).as_posix()
    for path in fixture.rglob("*")
    if path.is_file()
)
assert all((game / path).is_file() for path in own), own
assert lines(map001)[:2] == [TRANSLATED, "気をつけるのじゃぞ。"], lines(map001)
assert sorted(
    path.name for path in game.iterdir() if path.name.casefold() == "data"
) == ["data"]
assert (game / "data/Map002.json").is_file() and not (game / "readme.txt").exists()

# A release whose line merge drops a translation says so in the line view:
# a line inserted beside a translated one can make the merge take the whole file.
data = json.loads(map001.read_text(encoding="utf-8"))
data.pop("_original", None)
page = next(event for event in data["events"] if event)["pages"][0]["list"]
for command in page:
    if command["code"] == 401 and command["parameters"][0] == TRANSLATED:
        command["parameters"][0] = "おお、ミカよ。よく来てくれた。"
page.insert(1, {"code": 401, "indent": 0, "parameters": ["今日はいい天気じゃな。"]})
later = temporary / "later/data"
later.mkdir(parents=True)
(later / "Map001.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8"
)
preview = preview_official_update(game, later.parent, "1.02", patch_overlay=True)
whole = next(
    change for change in preview.file_changes if change.path == "data/Map001.json"
).whole_file_replaced
entry = next(
    entry
    for entry in text_changes(game, preview).files
    if entry.path == "data/Map001.json"
)
assert (entry.replaced, entry.kept) == ((1, 0) if whole else (0, 1)), (whole, entry)
print("ok")
