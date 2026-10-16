"""The glossary check through the engine on a generated game: which lines
it flags, what it proposes, and fixes written back over their lines."""

import json
import shutil
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_glossary_check as check
from util.rpgmaker_qa import task_layout
from util.vocab import BASE_SEPARATOR

game = temporary / "game"
data = game / "data"
data.mkdir(parents=True)


def line(original, text, code=401):
    return {"code": code, "indent": 0, "parameters": [text], "_original": original}


def write(name, value):
    (data / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


commands = [
    # A nameplate that renders a renamed character, and dialogue with the
    # same rendering.
    {
        "code": 101,
        "indent": 0,
        "parameters": ["", 0, 0, 2, "Sonko"],
        "_original": "存子",
    },
    line("存子はここにいる。", "Sonko is here."),
    # Drift wrapped over a line break, which a fix within the line width
    # no longer needs.
    line("・ケルサー砦のヌシの撃破", "・Defeat the Apex Monster of Kelsar\nFort"),
    # A plural, a choice condition, a key kept in Japanese, a possessive at
    # the term's end and the other pair of a two-pair row all use the term.
    line("フィヤルの戦士たちだ。", "They're the Warriors of Fjall."),
    {
        "code": 102,
        "indent": 0,
        "parameters": [["Kelser Fortressif(s[1])"], 0, 0, 2, 0],
        "_original": ["ケルサー砦if(s[1])"],
    },
    line("<Key:ケルサー砦>", "<Key:ケルサー砦> A fort"),
    line("存子の家", "Aruko's house"),
    line("小町が来た。", "Komachi came."),
    # Honorifics from the base glossary, a katakana or kanji term inside a
    # longer word, and a term that is only part of a longer term.
    line("たくさん食べた。", "I ate a lot."),
    line("パンツが見える。", "I can see panties."),
    line("呪術師が来た。", "The sorcerer came."),
    line("回復薬だ。", "It's a potion."),
    # Ordinary words written like a term: flagged, without a proposal that
    # would replace "pray" or "But", or a whole message that says only 興奮.
    line("祈りましょう。", "Let's pray."),
    line("お尻が見える。", "But I can see it."),
    line("興奮……", "Turn you on..."),
    # A refusal saved as a translation is Translate's to send again.
    line("トーラが来た。", "I can't help with this translation."),
    {"code": 0, "indent": 0, "parameters": []},
]
write("Map001.json", {"events": [None, {"id": 1, "pages": [{"list": commands}]}]})
write(
    "Items.json",
    [
        None,
        {
            "id": 1,
            "name": "Endurable Pain",
            "description": "Restores HP.",
            "_original": {"name": "耐え得る痛み", "description": "HPを回復する。"},
        },
    ],
)
glossary = f"""# Characters
存子 (Aruko) - The creator reads it Aruko, never Sonko.
トーラ (Thora)
分身 (Clone) / 小町 (Komachi) - Two nameplates of one character.
# Places
ケルサー砦 (Kelser Fortress)
フィヤルの戦士 (Warrior of Fjall)
# Skills
回復薬 (Potion)
回復 (Heal)
興奮 (Arousal)
祈り (Prayer)
お尻 (Butt)
呪術 (Sorcery)
パン (Bread)
耐え得る痛み (Bearable Pain)

{BASE_SEPARATOR}
# Honorifics
さん (san)
"""
layout = task_layout(game)
result = check.scan(
    data, glossary, layout, skip=lambda live, _source: "can't help" in live
)
found = {line["live"]: line for line in result["found"]}
proposals = {live: line["proposal"] for live, line in found.items()}
assert result["lines"] == 17, result["lines"]
assert proposals == {
    "Sonko": "Aruko",
    "Sonko is here.": "Aruko is here.",
    "・Defeat the Apex Monster of Kelsar\nFort": (
        "・Defeat the Apex Monster of Kelser Fortress"
    ),
    "Let's pray.": None,
    "But I can see it.": None,
    "Turn you on...": None,
    "Restores HP.": None,
    "Endurable Pain": "Bearable Pain",
}, proposals
assert [term["source"] for term in found["Restores HP."]["terms"]] == ["回復"]
term = found["・Defeat the Apex Monster of Kelsar\nFort"]["terms"][0]
assert (term["english"], term["start"], term["end"]) == ("Kelser Fortress", 1, 6)

# A fix writes over the English it was chosen for and keeps the file's
# layout; a line that changed since stops the write.
copy = temporary / "copy"
shutil.copytree(data, copy)
nameplate = found["Sonko"]
kelser = found["・Defeat the Apex Monster of Kelsar\nFort"]
fixes = [
    {"record": nameplate["record"], "text": "Aruko"},
    {"record": kelser["record"], "text": kelser["proposal"]},
]
assert check.apply_fixes(copy, fixes) == ["Map001.json"]
written = json.loads((copy / "Map001.json").read_text(encoding="utf-8"))
listed = written["events"][1]["pages"][0]["list"]
assert listed[0]["parameters"][4] == "Aruko", listed[0]
assert listed[2]["parameters"][0] == kelser["proposal"], listed[2]
assert listed[1]["parameters"][0] == "Sonko is here."
assert (copy / "Map001.json").read_text(encoding="utf-8").startswith('{\n "events"')
try:
    check.apply_fixes(copy, fixes)
except ValueError as error:
    assert "changed since the glossary check" in str(error), error
else:
    raise AssertionError("A fix applied over a line that changed.")

# A hand-written fix that drops a control code is refused before it is saved.
coded = dict(nameplate["record"], source="\\C[2]存子\\C[0]", live="\\C[2]Sonko\\C[0]")
_written, problems = check.fix_problems(coded, "Aruko", layout)
assert problems == ["introduces runtime-token-mismatch"], problems
print("ok")
