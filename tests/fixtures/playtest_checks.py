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

from util.playtest.checks import static_checks

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
print("ok")
