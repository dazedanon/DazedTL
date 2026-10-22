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
from util.rpgmaker_plugin_registry import plugin_entries
from util.version_update import (
    GitWorkflowError,
    abort_update,
    apply_official_update,
    continue_with_official,
    git_workflow,
    inspect_repository,
    preview_official_update,
)
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


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=4), encoding="utf-8", newline="\n"
    )


def event_command(code, *parameters):
    return {"code": code, "indent": 0, "parameters": list(parameters)}


def common_event(number, commands):
    return {
        "id": number,
        "list": [*commands, event_command(0)],
        "name": f"会話{number}",
        "switchId": 1,
        "trigger": 0,
    }


def conversation(number, speaker, text, rows=5):
    return common_event(
        number,
        [
            line
            for row in range(rows)
            for line in (
                event_command(101, "", 0, 0, 2, speaker),
                event_command(401, text(row)),
            )
        ],
    )


# A prepared, translated game: formatted data, a baseline, one translated line.
game = temporary / "game"
shutil.copytree(fixture, game)
# Two conversations between a scene and a slot the developer fills later.
common_events = game / "data/CommonEvents.json"
conversations = [
    None,
    common_event(1, [event_command(108, "")]),
    *(
        conversation(number, "サン", lambda row: f"会話{number}の{row}行目")
        for number in (2, 3)
    ),
    common_event(4, []),
]
write_json(common_events, conversations)
format_json_files(game / "data")
setup_git(LenProject(game), version="1.0", current_is_untranslated=True)
map001 = game / "data/Map001.json"
# LF, as the engine and the formatter write data: a Windows text write would
# make every line a translation edit, and the patch would replace them all.
map001.write_text(
    map001.read_text(encoding="utf-8").replace(
        "おお、ミカよ。よく来てくれた。", TRANSLATED
    ),
    encoding="utf-8",
    newline="\n",
)
translation = [
    *conversations[:2],
    *(
        conversation(number, "San", lambda row: f"Talk {number}, line {row}.")
        for number in (2, 3)
    ),
    conversations[4],
]
# Wrapping a line onto two changes the conversation's shape, so once a release
# changes that conversation too, the file merges by Git's lines, not by value.
translation[3]["list"].insert(2, event_command(401, "(continued)"))
write_json(common_events, translation)
# The translation sets a plugin's text, registers a plugin of its own and
# translates a script's string.
plugins_js = game / "js/plugins.js"
TRANSLATION_PLUGIN = (
    '{"name":"Translation","status":true,"description":"","parameters":{}}'
)
plugins_js.write_text(
    plugins_js.read_text(encoding="utf-8")
    .replace("ようこそ、魔法の世界へ！", "Welcome to magic!")
    .replace("\n];", ",\n" + TRANSLATION_PLUGIN + "\n];"),
    encoding="utf-8",
    newline="\n",
)
title_message = game / "js/plugins/TitleMessage.js"
title_message.write_text(
    title_message.read_text(encoding="utf-8").replace(
        "冒険の始まり", "The adventure begins"
    ),
    encoding="utf-8",
    newline="\n",
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

# A line inserted beside a translated one: formatted JSON repeats each
# command's lines, so Git lines the insertion up against the translated line
# and conflicts. The merge by value keeps the translation, the preview and
# the line view say so, and applying leaves it in the game.
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
    json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8", newline="\n"
)
preview = preview_official_update(game, later.parent, "1.02", patch_overlay=True)
change = next(
    change for change in preview.file_changes if change.path == "data/Map001.json"
)
assert not change.whole_file_replaced, change
entry = next(
    entry
    for entry in text_changes(game, preview).files
    if entry.path == "data/Map001.json"
)
assert (entry.replaced, entry.kept) == (0, 1), entry
result = apply_official_update(
    game,
    later.parent,
    "1.02",
    expected_tree=preview.proposed_tree,
    expected_original_commit=preview.original_commit,
    expected_translation_commit=preview.translation_commit,
    expected_asset_manifest=preview.proposed_asset_manifest,
    expected_baseline_asset_manifest=preview.baseline_asset_manifest,
    patch_overlay=True,
)
assert result.complete, result
assert lines(map001)[:3] == [
    "今日はいい天気じゃな。",
    TRANSLATED,
    "気をつけるのじゃぞ。",
], lines(map001)

# The developer shows a scene's pictures above the conversations, fills the
# slot below them and rewrites one translated line. Hundreds of lines added on
# both sides exceeded what Git's default diff searches, so it lined the
# repeated lines of formatted commands up against the wrong commands, and
# resolving the one real conflict replaced every translated line between.
official = json.loads(json.dumps(conversations))
official[1]["list"][:0] = [
    event_command(231, 1, f"cg{number:02}", 0, 0, 0, 0, 100, 100, 255, 0)
    for number in range(40)
]
official[4] = conversation(4, "サン", lambda row: f"新しい会話の{row}行目", rows=20)
official[3]["list"][-2]["parameters"][0] = "会話3の最後の行"
newer = temporary / "newer/data"
newer.mkdir(parents=True)
write_json(newer / "CommonEvents.json", official)
# It also gives the title plugin a subtitle and registers a plugin of its own,
# which replaced the translated plugin and dropped the translation's plugin,
# and edits the script line beside the translated one, which took the
# translated line with it.
(newer.parent / "js/plugins").mkdir(parents=True)
(newer.parent / "js/plugins.js").write_text(
    (fixture / "js/plugins.js")
    .read_text(encoding="utf-8")
    .replace('"fontSize":"28"', '"fontSize":"28","subtitle":"第二章"')
    .replace(
        "\n];",
        ',\n{"name":"Battleback","status":true,"description":"","parameters":{}}\n];',
    ),
    encoding="utf-8",
    newline="\n",
)
(newer.parent / "js/plugins/TitleMessage.js").write_text(
    (fixture / "js/plugins/TitleMessage.js")
    .read_text(encoding="utf-8")
    .replace("parameters('TitleMessage')", 'parameters("TitleMessage")')
    .replace("})();", "  console.log('第二章');\n})();"),
    encoding="utf-8",
    newline="\n",
)
preview = preview_official_update(game, newer.parent, "1.03", patch_overlay=True)
text = {entry.path: entry for entry in text_changes(game, preview).files}
assert text["data/CommonEvents.json"].replaced == 1, text
for path in ("js/plugins.js", "js/plugins/TitleMessage.js"):
    assert (text[path].to_translate, text[path].replaced, text[path].kept) == (
        1,
        0,
        1,
    ), text[path]
applying = {
    "expected_tree": preview.proposed_tree,
    "expected_original_commit": preview.original_commit,
    "expected_translation_commit": preview.translation_commit,
    "expected_asset_manifest": preview.proposed_asset_manifest,
    "expected_baseline_asset_manifest": preview.baseline_asset_manifest,
    "patch_overlay": True,
}


def stuck(state):
    return (
        state.pending_cherry_pick,
        state.asset_sync_pending,
        state.original_version,
        state.translation_version,
    )


def failing(*args, **kwargs):
    raise GitWorkflowError("The cherry-pick failed.")


# An apply whose cherry-pick failed without a conflict, such as a patch that
# turned out empty, left the release on the original branch and its assets
# waiting, so every game write refused with no control to end it.
real_cherry_pick, git_workflow._cherry_pick = git_workflow._cherry_pick, failing
try:
    apply_official_update(game, newer.parent, "1.03", **applying)
    raise AssertionError("The failing cherry-pick applied.")
except GitWorkflowError:
    pass
finally:
    git_workflow._cherry_pick = real_cherry_pick
assert stuck(inspect_repository(game)) == (False, False, "1.02", "1.02")
# A game cancelled before cancelling restored the original branch, or closed
# before its cherry-pick began, keeps that state; cancelling ends it.
assert apply_official_update(
    game, newer.parent, "1.03", auto_resolve=False, **applying
).pending_conflicts
subprocess.run(["git", "-C", str(game), "cherry-pick", "--abort"], check=True)
assert stuck(inspect_repository(game)) == (False, True, "1.03", "1.02")
status = abort_update(game)
assert (stuck(status), status.original_commit) == (
    (False, False, "1.02", "1.02"),
    preview.original_commit,
), status
# An apply stopped at Git's conflict, then cancelled: the original branch kept
# the release and its asset record waited, so the game read 1.03 and refused
# every write. Cancelling leaves the game as before, and it applies again.
stopped = apply_official_update(
    game, newer.parent, "1.03", auto_resolve=False, **applying
)
assert stopped.pending_conflicts, stopped
status = abort_update(game)
assert (
    status.pending_cherry_pick,
    status.asset_sync_pending,
    status.original_commit,
    status.original_version,
    status.translation_commit,
) == (False, False, preview.original_commit, "1.02", preview.translation_commit), status
# A damaged asset record, such as one cut short by a crash, must not keep
# Cancel from ending the stopped update: it only says what to copy.
stopped = apply_official_update(
    game, newer.parent, "1.03", auto_resolve=False, **applying
)
assert stopped.pending_conflicts, stopped
record = git_workflow._asset_state_path(
    inspect_repository(game).repo_root,
    inspect_repository(game).game_prefix,
    "pending-assets",
)
record.write_text('{"format": ', encoding="utf-8")
status = abort_update(game)
assert (
    status.pending_cherry_pick,
    status.asset_sync_pending,
    status.original_commit,
    status.original_version,
) == (False, False, preview.original_commit, "1.02"), status
# An apply that stopped once the translation had the update, before its
# assets were copied: finishing copies them.
real_assets = git_workflow._complete_pending_asset_plan
git_workflow._complete_pending_asset_plan = failing
try:
    apply_official_update(game, newer.parent, "1.03", **applying)
    raise AssertionError("The asset copy ran.")
except GitWorkflowError:
    pass
finally:
    git_workflow._complete_pending_asset_plan = real_assets
assert stuck(inspect_repository(game)) == (False, True, "1.03", "1.03")
result = continue_with_official(game)
assert result.complete and not inspect_repository(game).asset_sync_pending, result
merged = json.loads(common_events.read_text(encoding="utf-8"))
translation[3]["list"][-2] = official[3]["list"][-2]
assert merged == [None, official[1], *translation[2:4], official[4]], merged
assert [
    (entry["name"], entry["parameters"])
    for entry in plugin_entries(plugins_js.read_text(encoding="utf-8"))
] == [
    (
        "TitleMessage",
        {"text": "Welcome to magic!", "fontSize": "28", "subtitle": "第二章"},
    ),
    ("Translation", {}),
    ("Battleback", {}),
], plugins_js.read_text(encoding="utf-8")
script = title_message.read_text(encoding="utf-8")
assert 'parameters("TitleMessage")' in script and "The adventure begins" in script, (
    script
)
print("ok")
