"""The release playtest's static checks on a generated MZ game.

Each part of the game holds one of the defects a manual QA of a released
translation found after text QA passed, beside the look-alikes each check
must leave alone.
"""

import json
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))
sys.path.insert(0, str(root / "backend"))

from util import rpgmaker_qa as qa
from util.playtest import fixes
from util.playtest.checks import static_checks
from util.playtest.run import (
    compare,
    layout_probes,
    merge,
    observations,
    read_widths,
)
from util.rpgmaker_screens import label_fits

game = temporary / "game"
data = game / "data"
plugins = game / "js" / "plugins"
plugins.mkdir(parents=True)
data.mkdir()


def write(path, value):
    path.write_text(
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
        encoding="utf-8",
    )


def line(original, text, code=401):
    return {"code": code, "indent": 0, "parameters": [text], "_original": original}


def entry(index, **fields):
    original = fields.pop("_original", None)
    return {"id": index, **fields, **({"_original": original} if original else {})}


write(
    game / "js" / "rmmz_core.js",
    "function Window_Base() {}\nWindow_Base.prototype.refresh = function() {};\n",
)
write(
    data / "System.json",
    {
        "terms": {
            "messages": {
                "actorDamage": "%1 took %2 damage!",
                "obtainExp": "Got EXP!",
            }
        },
        "_original": {
            "terms": {
                "messages": {
                    "actorDamage": "%1は %2 のダメージを受けた！",
                    "obtainExp": "%1 の経験値を獲得！",
                }
            }
        },
    },
)
write(
    data / "States.json",
    [
        None,
        # Its source starts with a particle and lost the name with it.
        entry(
            1,
            message1="was caught in an Illusion!",
            message4="The Illusion wore off.",
            _original={"message1": "は幻惑に囚われた！", "message4": "の幻惑が解けた"},
        ),
    ],
)
write(
    data / "Skills.json",
    [
        None,
        entry(
            1,
            message1="Called for allies!",
            message2="",
            description="Calls allies.",
            _original={"message1": "は仲間を呼んだ！"},
        ),
        # %2 is the item's name, which this translation dropped.
        entry(
            2,
            message1="%1 uses the skill!",
            message2="",
            description="Line one\nLine two",
            _original={"message1": "%1は%2を使った！"},
        ),
    ],
)
write(
    data / "Items.json",
    [
        None,
        entry(
            1,
            name="Charm",
            description="Blocks one attack in your place.\nThen it\nshatters.",
            _original={"name": "護符", "description": "身代わりになる。"},
        ),
        entry(
            2,
            name="Herb",
            description="Heals.\nA little.",
            _original={"name": "薬草", "description": "回復する。"},
        ),
        # A plugin's help window shows all three lines.
        entry(
            3,
            name="Tonic",
            description="Restores a little HP.\nTastes bitter.\nSold everywhere.",
            _original={"name": "強壮剤", "description": "体力を回復する。"},
        ),
        # No screen the tour opened shows it.
        entry(
            4,
            name="Relic",
            description="An old relic.\nIt hums.\nNobody knows why.",
            _original={"name": "遺物", "description": "古い遺物。"},
        ),
    ],
)
write(data / "CommonEvents.json", "{ broken")
write(
    data / "Map001.json",
    {
        "events": [
            None,
            {
                "id": 1,
                "pages": [
                    # A rewrap moved \V[1] to the next line: nothing is lost.
                    {
                        "list": [
                            line("所持金は\\V[1]Gだ。\nまた来てね。", "Your money is"),
                            {
                                "code": 401,
                                "indent": 0,
                                "parameters": ["\\V[1]G. Come again."],
                            },
                            {"code": 0, "indent": 0, "parameters": []},
                        ]
                    },
                    # \N[1] dropped, Japanese left in a translated line and a placeholder.
                    {
                        "list": [
                            {
                                "code": 101,
                                "indent": 0,
                                "parameters": ["", 0, 0, 2, "Elder"],
                                "_original": "村長",
                            },
                            line("\\N[1]、よく来た！", "Welcome!"),
                            line("今日は晴れだ", "Today is 晴れ."),
                            line("◯日目", "Day ◯"),
                            {
                                "code": 401,
                                "indent": 0,
                                "parameters": ["まだ訳していない"],
                            },
                            {"code": 0, "indent": 0, "parameters": []},
                        ]
                    },
                ],
            },
        ]
    },
)

PLUGIN_LIST = [
    {"name": "Dungeon", "status": True, "parameters": {"ShowGauge": "false"}},
    {"name": "Broken", "status": True, "parameters": {}},
    {"name": "Gone", "status": True, "parameters": {}},
    {"name": "Retired", "status": False, "parameters": {}},
]
write(
    game / "js" / "plugins.js",
    "var $plugins =\n" + json.dumps(PLUGIN_LIST, ensure_ascii=False) + ";\n",
)
write(
    plugins / "Dungeon.js",
    r"""
(() => {
    const params = PluginManager.parameters("Dungeon");
    const SHOW_GAUGE = params["ShowGauge"] === "true";
    const DEBUG = false;
    const LABEL_SET = "ぁぃぅっ";
    const PORTRAIT = "立ち絵/立ち絵_服/arina_通常";
    function trap() {
        $gameMessage.add("罠にかかった！");
        $gameMessage.add(LABEL_SET.includes("x") ? "ア:Eek, a trap!" : "");
        if (SHOW_GAUGE) this.drawText("淫乱度", 0, 0, 80);
        if (DEBUG) console.log("デバッグ");
        ImageManager.loadPicture("罠の絵");
        this.setText('Check "Day ◯/30" at the top left.');
    }
    function unusedLabel() { return "未使用の文字"; }
    Window_Base.prototype.refresh = function() { trap(); };
    PluginManager.registerCommand("Dungeon", "rest", () => { $gameMessage.add("休んだ。"); });
    if (getParamString(["Title", "タイトル"])) return;
})();
""",
)
write(plugins / "Broken.js", 'const message = "壊れた;\n')

report = static_checks(game, data)
problems = report["problems"]
found = {
    (row["check"], row["file"], row.get("pointer") or row.get("plugin") or ""): row
    for row in problems
}
expected = {
    ("json", "data/CommonEvents.json", ""),
    ("plugin-missing", "js/plugins/Gone.js", "Gone"),
    ("plugin-syntax", "js/plugins/Broken.js", "Broken"),
    ("battler-name", "data/States.json", "/1/message1"),
    ("battler-name", "data/Skills.json", "/1/message1"),
    ("placeholder", "data/Skills.json", "/2/message1"),
    ("placeholder", "data/System.json", "/terms/messages/obtainExp"),
    ("event-codes", "data/Map001.json", "/events/1/pages/1/list/1"),
    ("visible-text", "data/Map001.json", "/events/1/pages/1/list/2/parameters/0"),
    ("placeholder-glyph", "data/Map001.json", "/events/1/pages/1/list/3/parameters/0"),
    ("untranslated", "data/Map001.json", ""),
    ("help-rows", "data/Items.json", "/1/description"),
    ("help-rows", "data/Items.json", "/3/description"),
    ("help-rows", "data/Items.json", "/4/description"),
    ("plugin-text", "js/plugins/Dungeon.js", "Dungeon"),
    ("placeholder-glyph", "js/plugins/Dungeon.js", "Dungeon"),
}
assert set(found) == expected, sorted(set(found) ^ expected)
assert report["engine"] == "MZ" and report["gaps"] == [], report

assert found[("plugin-syntax", "js/plugins/Broken.js", "Broken")]["line"] == 1
assert found[("event-codes", "data/Map001.json", "/events/1/pages/1/list/1")][
    "codes"
] == ["\\N[1]"]
assert (
    found[("battler-name", "data/Skills.json", "/1/message1")]["identity"]
    == "Skills.json#/1/message1"
)

# Each string with its reach; asset names, speaker tags, matchers, the console
# and parameter names are not text.
texts = {
    row["text"]: (row["reach"], row["evidence"])
    for row in found[("plugin-text", "js/plugins/Dungeon.js", "Dungeon")]["texts"]
}
assert set(texts) == {"罠にかかった！", "淫乱度", "未使用の文字", "休んだ。"}, texts
assert texts["罠にかかった！"][0] == "drawn", texts
assert texts["淫乱度"][0] == "disabled" and "SHOW_GAUGE" in texts["淫乱度"][1], texts
assert texts["未使用の文字"] == (
    "uncalled",
    "It is in unusedLabel, which nothing calls.",
), texts
assert texts["休んだ。"] == (
    "uncalled",
    "It is in the command rest, which no event calls.",
), texts
glyph = found[("placeholder-glyph", "js/plugins/Dungeon.js", "Dungeon")]
assert [row["reach"] for row in glyph["texts"]] == ["drawn"], glyph
# What the tour saw joins the problem it confirms, or stands beside them.
trap = next(
    row["line"]
    for row in found[("plugin-text", "js/plugins/Dungeon.js", "Dungeon")]["texts"]
    if row["text"] == "罠にかかった！"
)
seen = {"stop": "menu", "scene": "Scene_Item", "map": 1, "capture": "002-overflow"}
runtime = {
    "stops": [
        {"id": "title", "status": "done"},
        {"id": "shop", "status": "failed", "note": "The shop did not open."},
        # The tour went on without a screen that hung the game.
        {"id": "screens", "status": "done", "stopped": ["Scene_Hang"]},
    ],
    "errors": [
        {
            **seen,
            "kind": "error",
            "message": "TypeError: x is undefined",
            "source": {"file": "js/plugins/Dungeon.js", "line": 9},
        },
        {**seen, "kind": "nwjs", "message": "require is not defined"},
        # The failed shop stop's own error is the tour's, not the game's.
        {
            **seen,
            "kind": "harness",
            "message": "shop: Cannot read properties of undefined (reading 'list')",
            "source": {"file": "js/plugins/Dungeon.js", "line": 3},
        },
        {
            **seen,
            "stop": "screen Scene_Gallery",
            "kind": "crash",
            "message": "TypeError: y",
        },
    ],
    "japanese": [
        {
            **seen,
            "text": "罠にかかった！",
            "source": {"file": "js/plugins/Dungeon.js", "line": trap},
        },
    ],
    "overflow": [
        {
            **seen,
            "window": "Window_Help",
            "edge": "bottom",
            "text": "Blocks one attack",
            "data": {"file": "Items.json", "pointer": "/1/description"},
        },
        # A line of a description its window shows in full is too wide.
        {
            **seen,
            "window": "Window_Help",
            "edge": "right",
            "text": "Restores a little HP.",
            "data": {"file": "Items.json", "pointer": "/3/description"},
        },
        {
            **seen,
            "scene": "Scene_Gallery",
            "window": "Window_Help",
            "edge": "bottom",
            "text": "A long caption",
        },
    ],
    "help": ["Items.json#/1/description", "Items.json#/3/description"],
    "scenes": [{"scene": "Scene_Title"}],
    "complete": True,
}
report = merge(report, runtime, "data")
problems = {
    (row["check"], row["file"], row.get("pointer") or row.get("plugin") or ""): row
    for row in report["problems"]
}
group = problems[("plugin-text", "js/plugins/Dungeon.js", "Dungeon")]
assert group["seen"] == seen and [
    row.get("seen") for row in group["texts"] if row["line"] == trap
] == [seen], group
help_rows = problems[("help-rows", "data/Items.json", "/1/description")]
assert help_rows["seen"] == seen, help_rows
# A description's line count counts only where the tour saw it run past the
# bottom of its window: one the tour showed otherwise fits, though a line of
# it may be too wide, and one it never showed is a gap saying where to look.
assert not {
    ("help-rows", "data/Items.json", "/3/description"),
    ("help-rows", "data/Items.json", "/4/description"),
} & set(problems), problems
gallery = [row for row in report["problems"] if row["check"] == "overflow"]
assert [(row["fix"], row.get("pointer")) for row in gallery] == [
    ("text-qa", "/3/description"),
    ("game", None),
], gallery
assert problems[("runtime-error", "js/plugins/Dungeon.js", "")]["line"] == 9
assert [row["check"] for row in report["problems"]].count("runtime-error") == 1
assert len(report["gaps"]) == 5, report["gaps"]
assert "Scene_Gallery could not be opened on its own" in report["gaps"][1], report[
    "gaps"
]
assert report["gaps"][3].endswith("on their own: Scene_Hang."), report["gaps"]
assert report["gaps"][4].endswith(": Items.json 4."), report["gaps"]
assert report["coverage"]["reached"] == 2, report["coverage"]
observed = {row["identity"]: row for row in observations(report)}
assert observed["Items.json#/1/description"]["categories"] == ["ui"], observed
assert "Seen on Scene_Item" in observed["Items.json#/1/description"]["note"], observed
assert "Items.json#/4/description" not in observed, observed
# A second run counts what the first found and it no longer does, and marks
# what is new; a group counts its strings one by one.
again = json.loads(json.dumps(report))
again["problems"] = [
    row for row in again["problems"] if row["check"] != "help-rows"
] + [{"kind": "fit", "check": "overflow", "file": "", "text": "A new caption"}]
plugin = next(row for row in again["problems"] if row["check"] == "plugin-text")
plugin["texts"] = plugin["texts"][1:]
assert compare(report, again) == {"fixed": 2, "new": 1}, compare(report, again)
assert [row["text"] for row in again["problems"] if row.get("new")] == ["A new caption"]

# Fixes go in only when the play with them in place fixed something and broke
# nothing new: no new crash, and no fewer places reached.
again["since"] = compare(report, again)
assert fixes.refusal(report, again) == "", fixes.refusal(report, again)
unchanged = {**again, "since": {"fixed": 0, "new": 1}}
assert fixes.refusal(report, unchanged).startswith("Nothing the last playtest"), (
    unchanged
)
stopping = json.loads(json.dumps(again))
stopping["problems"].append(
    {
        "kind": "crash",
        "check": "runtime-crash",
        "file": "",
        "note": "TypeError",
        "new": True,
    }
)
assert fixes.refusal(report, stopping).endswith(": TypeError"), stopping
fewer = {**again, "coverage": {**again["coverage"], "reached": 1}}
assert "fewer places" in fixes.refusal(report, fewer), fewer
assert "did not play" in fixes.refusal(report, {**again, "played": False})
# main.js loads them once, just before the engine sets up plugins, in MV's
# top-level form and MZ's indented one, keeping a BOM and CRLF.
mv = b"\xef\xbb\xbfPluginManager.setup($plugins);\r\nwindow.onload = run;\r\n"
loaded = fixes.with_loader(mv)
assert loaded == (b"\xef\xbb\xbf" + fixes.LOADER.encode() + b"\r\n" + mv[3:]), loaded
assert fixes.with_loader(loaded) == loaded
mz = b"    load() {\n        PluginManager.setup($plugins);\n    }\n"
assert (
    b"        " + fixes.LOADER.encode() + b"\n        PluginManager"
    in fixes.with_loader(mz)
)
for broken in (b"run();\n", mz + mz):
    try:
        fixes.with_loader(broken)
    except ValueError:
        continue
    raise AssertionError(broken)
fixes.check(fixes.TEMPLATE.encode())
try:
    fixes.check(b"(() => {\n  window.x = ;\n})();\n")
except ValueError as error:
    assert "line 2" in str(error), error
else:
    raise AssertionError("A fix that does not compile was accepted")

# Text QA takes the playtest's findings as observations when it prepares, so
# QA with new findings is a new task, the same findings give the same task,
# and a line its inventory lacks is left out.
qa_game = temporary / "qa-game"
(qa_game / "data").mkdir(parents=True)
write(
    qa_game / "data" / "Items.json",
    [
        None,
        entry(
            1,
            name="Charm",
            description="Blocks one attack.\nThen it\nshatters.",
            _original={"name": "護符", "description": "身代わりになる。"},
        ),
    ],
)
storage = temporary / "qa"
plain, _state = qa.prepare_task(qa_game, qa_game / "data", "database", storage)
found = [
    {
        "identity": "Items.json#/1/description",
        "categories": ["ui"],
        "note": "Cut off in the item screen.",
    },
    {
        "identity": "Items.json#/9/description",
        "categories": ["ui"],
        "note": "No such item.",
    },
]
noted, _state = qa.prepare_task(
    qa_game, qa_game / "data", "database", storage, observations=found
)
same, _state = qa.prepare_task(
    qa_game, qa_game / "data", "database", storage, observations=found
)
assert plain != noted == same, (plain, noted, same)
rows = json.loads((noted / "checkpoint.json").read_text(encoding="utf-8"))[
    "observations"
]
assert [(row["worker"], row["note"]) for row in rows] == [
    ("playtest", "Cut off in the item screen.")
], rows
assert "Items.json#/1/description" in qa.observed_names(noted)
assert not qa.observed_names(plain)
# Preparing again while a task still reviews, as after a playtest fix
# changes the plugins, keeps the findings it was prepared with, so it resumes
# that task instead of starting a new review; newer findings are observed.
from dazedtl.compatibility.playtest import task_observations

workflow = temporary / "workflow"
workflow.mkdir()
write(workflow / "text-qa-database.json", {"task": str(plain), "observations": []})
assert task_observations(workflow, "database", found) == []
write(workflow / "text-qa-database.json", {"task": str(noted)})
assert task_observations(workflow, "database", found[:1]) == []
assert task_observations(workflow, "release", found) == found

# A layout check proves a width only with lines exactly that wide, in as
# many rows as one message shows, under the face the game's actors use.
layout_data = temporary / "layout"
layout_data.mkdir()
write(
    layout_data / "Actors.json",
    [None, {"faceName": ""}, {"faceName": "face02", "faceIndex": 3}],
)
widths = read_widths({"width": 55, "faceWidth": 50, "listWidth": 70, "messageRows": 4})
probes = {probe["id"]: probe for probe in layout_probes(layout_data, widths)}
assert [len(line) for line in probes["layout-width"]["lines"]] == [55] * 4, probes
assert [len(line) for line in probes["layout-faceWidth"]["lines"]] == [50] * 4, probes
assert [len(line) for line in probes["layout-listWidth"]["lines"]] == [70] * 2, probes
assert probes["layout-faceWidth"]["face"] == ["face02", 3], probes
assert not any(
    line.endswith(" ") for probe in probes.values() for line in probe["lines"]
)
for wrong in ({"width": "55"}, {"width": 0}, {"messageRows": 4}):
    try:
        read_widths(wrong)
    except ValueError:
        continue
    raise AssertionError(f"{wrong} was accepted")

# A shortened label fits only when its screen draws the shorter text in full:
# not squeezed, and not while the game still draws the old text, which means
# the plugin draws another setting there.
menu = {
    "name": "menu",
    "file": "menu.png",
    "title": "Menu",
    "labels": [
        {"text": "Bestiary"},
        {"text": "\\C[2]Records", "squeezed": 0.9},
        {"text": "Location:", "squeezed": 0.91},
    ],
}
fits = label_fits(
    [
        {"text": text, "title": "Menu", "capture": "/qa/menu.png", "shows": shows}
        for text, shows in (
            ("Monster Compendium", ["Bestiary"]),
            ("Journey Records", ["Records"]),
            ("Location:", ["Place:"]),
            ("Objective", ["Goal"]),
        )
    ],
    {"screens": [menu]},
    "/check",
)
assert [(row["fits"], row.get("squeezed")) for row in fits] == [
    (True, None),
    (False, 0.9),
    (False, 0.91),
    (False, None),
], fits
assert (
    fits[1]["note"] == "The game draws Records squeezed to 90% of the width it needs."
)
assert fits[2]["note"] == (
    "The game still draws Location: there, squeezed to 91% of the width it needs, "
    "not Place:."
), fits
assert fits[3]["capture"] == str(Path("/check") / "menu.png"), fits
print("ok")
