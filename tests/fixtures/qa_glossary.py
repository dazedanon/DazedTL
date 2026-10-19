"""Text QA's glossary family: which renderings its scan fixes and which it
leaves, each case taken from a released game, and a QA journey that reviews
the fixes as a group and applies them."""

import json
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa
from util import rpgmaker_qa_glossary as glossary
from util import rpgmaker_qa_lint as lint
from util.vocab import BASE_SEPARATOR

GLOSSARY = f"""# Characters
存子 (Aruko) - The creator reads it Aruko, never Sonko.
ニーナ (Nena Evans)
イタ・ズラン (Prank Ster)
夕闇 (Yuuyami)
淫魔 (Succubus)
# Places
ケルサー砦 (Kelser Fortress)
シキノワ (Shikinowa)
フィヤルの戦士 (Warrior of Fjall)
分かち谷 (Dividing Valley)
リリスの塔 (Tower of Lilith)
# Terms
憲兵 (Military Policeman)
ウルフ (Wolf)
マナ (Mana)
回復 (Heal)
何もしない (Do Nothing)
コア1 (Core 1)
堅牢 (Fortitude)
電蝕ノ印+ (Mark of Electrocution+)

{BASE_SEPARATOR}
# Honorifics
さん (san)
"""


def record(source, live, kind, file="Map001.json"):
    """An inventory record: an event command's line by its code, or a
    database text by its field."""
    if isinstance(kind, int):
        return {
            "identity": f"{file}#{len(records)}",
            "file": file,
            "source": source,
            "live": live,
            "event_code": kind,
        }
    return {
        "identity": f"{file}#{len(records)}",
        "file": file if file != "Map001.json" else "Skills.json",
        "source": source,
        "live": live,
        "classification": "database",
        "database_entity": {"id": len(records), "field": kind},
    }


records = []
fixed = {
    # A nameplate's whole English, and the same rendering in dialogue.
    ("存子", "Sonko", 101): "Aruko",
    ("存子はここにいる。", "Sonko is here.", 401): "Aruko is here.",
    # A name joined by a middle dot is still the whole nameplate.
    ("イタ・ズラン", "Ita Zuran", 101): "Prank Ster",
    # Every place a line writes the rendering.
    ("堅牢", "Stalwart", "name"): "Fortitude",
    (
        "堅牢を置き換える。堅牢が必要。",
        "Replaces Stalwart. Requires Stalwart.",
        "description",
    ): ("Replaces Fortitude. Requires Fortitude."),
    # A mark the term ends with is written once.
    ("電蝕ノ印+", "Electrocorrosion Mark+", "name"): "Mark of Electrocution+",
    # A rendering across a line break keeps the break.
    ("・ケルサー砦のヌシの撃破", "・Defeat the Apex Monster of Kelsar\nFort", 401): (
        "・Defeat the Apex Monster of Kelser\nFortress"
    ),
    # A place half written in romanized Japanese.
    ("分かち谷の東側だ。", "It's east of Wakachi Valley.", 401): (
        "It's east of Dividing Valley."
    ),
}
kept = [
    # A katakana name's given name alone.
    ("ニーナが来た。", "Nena came.", 401),
    # A name's people, a person's people and a Latin or -ves plural.
    ("シキノワの人々だ。", "Shikinowans gather.", 401),
    ("憲兵が来た。", "The Military Police came.", 401),
    (
        "ここは淫魔ばかりだ。",
        "Everyone here is a succubus... succubi, all of them.",
        401,
    ),
    ("ウルフたちが吠えた。", "The Wolves howled.", 401),
    # An abbreviation, a hyphenated pun and a longer name with the term.
    ("マナ+5", "MN +5", "description"),
    ("淫魔ルームへようこそ。", "Welcome to the Succu-Room.", 401),
    ("コア1Ａ", "Core 1A", 401),
    # A rendering that only shares letters with the term.
    ("夕闇の店「りゆう屋」だ。", "It's her shop, Riyuuya.", 401),
    # Ordinary words: a lower-case phrase, a verb, a name said as "you".
    ("フィヤルの戦士の村へ。", "To the Fjall warriors' village.", 401),
    ("何もしない。", "Does nothing.", "description"),
    ("HPを回復する。", "Restores HP.", "description"),
    ("存子、ありがとう。", "Thank you.", 401),
    # The term's words in another order.
    ("リリスの塔へ行く。", "I'm going to Lilith's Tower.", 401),
]
for source, live, kind in [*fixed, *kept]:
    records.append(record(source, live, kind))
# Players never read MapInfos.json names.
records.append(record("ケルサー砦", "Kelsar Fort", "name", "MapInfos.json"))
context = glossary.build(GLOSSARY, records)
for (source, live, kind), row in zip([*fixed, *kept, (None, None, None)], records):
    expected = fixed.get((source, live, kind), row["live"])
    found = glossary.fix(row["source"], row["live"], context)
    assert found == expected, (row["source"], found, expected)

# The lint family reads the same glossary, explains each fix, and writes the
# term into a reviewer's own correction of a line, too.
game = lint.game({"clusters": [], "records": records}, GLOSSARY)
assert lint.proposals("存子はここにいる。", "Sonko is here.", game) == {
    "lint:glossary-term": "Aruko is here."
}
assert lint.note(
    "lint:glossary-term", "存子はここにいる。", "Sonko is here.", game
) == ('The glossary gives 存子 as "Aruko".')
assert (
    lint.compose(
        "存子はここにいる。", "Sonko is right here.", ["lint:glossary-term"], game
    )
    == "Aruko is right here."
)

# A QA journey: the group reviewer accepts one fix and rejects the other,
# and only the accepted one is applied.
data = temporary / "game/data"
data.mkdir(parents=True)
(data.parent / ".dazedtl").mkdir()
(data.parent / ".dazedtl/glossary.txt").write_text(GLOSSARY, encoding="utf-8")


def line(original, text, code=401):
    return {"code": code, "indent": 0, "parameters": [text], "_original": original}


commands = [
    {
        "code": 101,
        "indent": 0,
        "parameters": ["", 0, 0, 2, "Sonko"],
        "_original": "存子",
    },
    line("存子はここにいる。", "Sonko is here."),
    line("分かち谷の東側だ。", "It's east of Wakachi Valley."),
    {"code": 0, "indent": 0, "parameters": []},
]
(data / "Map001.json").write_text(
    json.dumps({"events": [None, {"id": 1, "pages": [{"list": commands}]}]}),
    encoding="utf-8",
)
(data / "System.json").write_text(json.dumps({"gameTitle": "Test"}), encoding="utf-8")
task, state = qa.prepare_task(data.parent, data, "release", temporary / "storage")
reviewed = 0
# A second reviewer takes the checks of the first one's bundles.
while row := qa.next_bundle(task, "screen-a") or qa.next_bundle(task, "screen-b"):
    bundle = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
    groups = [item for item in bundle["items"] if item["kind"] == "lint-family"]
    if groups:
        assert [item["family"] for item in groups] == ["lint:glossary-term"], groups
        rendered = qa.render_bundle(task, row["id"])
        assert 'WHY: The glossary gives 分かち谷 as "Dividing Valley".' in rendered
    result = temporary / f"{row['id']}.json"
    result.write_text(
        json.dumps(
            {
                "schema": qa.SCREEN_RESULT_SCHEMA,
                "bundle_id": row["id"],
                "bundle_sha256": row["sha256"],
                "reviewed_all": True,
                "exceptions": [],
                "motif_reviews": [],
                "lint_reviews": [
                    {
                        "id": item["id"],
                        "rejected": [
                            proposal["id"]
                            for proposal in item["proposals"]
                            if proposal["current"] == "Sonko is here."
                        ],
                        "note": "The narrator teases her as Sonko.",
                    }
                    for item in groups
                ],
                "declined": [],
                "observations": [],
            }
        ),
        encoding="utf-8",
    )
    qa.accept_result(task, result)
    reviewed += len(groups)
assert reviewed == 1, reviewed
qa.advance(task)
state = qa.finalize(task)
findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))["findings"]
assert [(row["current"], row["correction"], row["category"]) for row in findings] == [
    ("Sonko", "Aruko", "terminology"),
    ("It's east of Wakachi Valley.", "It's east of Dividing Valley.", "terminology"),
], findings
assert findings[0]["evidence"].startswith('The glossary gives 存子 as "Aruko".'), (
    findings
)
inventory = json.loads((task / "inventory.json").read_text(encoding="utf-8"))
assert qa._apply_loaded_correction_map(
    task,
    json.loads((task / "task.json").read_text(encoding="utf-8")),
    qa.correction_map(task, [row["id"] for row in findings]),
    inventory,
    dry_run_name="dry-run.json",
    regression_name="regression.json",
    nonblocking_introduced_flags=qa.APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
)["valid"]
written = json.loads((data / "Map001.json").read_text(encoding="utf-8"))
assert [
    command["parameters"][4 if command["code"] == 101 else 0]
    for command in written["events"][1]["pages"][0]["list"][:3]
] == ["Aruko", "Sonko is here.", "It's east of Dividing Valley."], written
print("ok")
