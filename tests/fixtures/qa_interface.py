"""Interface captures in the text QA engine, on a generated game.

The capture runs the game in Electron, so a stand-in writes what it would:
the menu squeezes a plugin's command, and the item list squeezes a weapon's
name once a plugin change narrows its window, and the second weapon's once
QA is complete. Reviewers are played with fixed results, from the deep check
that names the capture to the editorial pass that reads the corrected one.
"""

import json
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

from util import rpgmaker_qa as qa

game = temporary / "game"
data = game / "data"
data.mkdir(parents=True)
(game / "index.html").write_text("<html></html>", encoding="utf-8")
LONG = "Legendary Sword of the Northern Wastes"
SHORT = "Northern Sword"
SPEAR = "Ancient Spear"
SHORT_SPEAR = "Spear"
(data / "Weapons.json").write_text(
    json.dumps(
        [
            None,
            {
                "id": 1,
                "name": LONG,
                "description": "",
                "_original": {"name": "北方の伝説の剣"},
            },
            {
                "id": 2,
                "name": SPEAR,
                "description": "",
                "_original": {"name": "古代の槍"},
            },
        ],
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
(data / "System.json").write_text(json.dumps({"gameTitle": "Test"}), encoding="utf-8")
plugins = game / "js" / "plugins.js"
plugins.parent.mkdir()


def configure(command, room):
    """The plugin list: the menu command and how many letters the item list
    fits, which the stand-in reads as the game's plugins would draw them."""
    settings = {"command": command, "room": room}
    plugins.write_text(
        "var $plugins = " + json.dumps([{"name": "Menu", "parameters": settings}]),
        encoding="utf-8",
    )


configure("Monster Compendium", 40)
captures = []


def capture(
    data_root,
    out_dir,
    *,
    overlay=None,
    screens=None,
    choices=None,
    all_choices=False,
    progress=None,
):
    """What the capture writes: the weapons in an item list as wide as the
    plugins make it, and the plugin's menu command, squeezed when long; with
    corrections, the weapons as the corrected data names them."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    weapons = json.loads((data / "Weapons.json").read_text(encoding="utf-8"))
    if overlay:
        weapons = json.loads(
            Path(overlay["data/Weapons.json"]).read_text(encoding="utf-8")
        )
    settings = json.loads(plugins.read_text(encoding="utf-8").split("= ", 1)[1])[0][
        "parameters"
    ]

    def label(text, window, room):
        return {"text": text, "window": window} | (
            {"squeezed": 0.7} if len(text) > room else {}
        )

    listing = {
        "game": {"engine": "MZ", "width": 816, "height": 624},
        "screens": [
            {
                "name": "items-2-01",
                "file": "items-2-01.png",
                "title": "Items: Weapons",
                "labels": [
                    label(weapon["name"], "Window_ItemList", settings["room"])
                    for weapon in weapons[1:]
                ],
            },
            *(
                []
                if overlay
                else [
                    {
                        "name": "menu",
                        "file": "menu.png",
                        "title": "Menu",
                        "labels": [
                            label(settings["command"], "Window_MenuCommand", 12)
                        ],
                    }
                ]
            ),
        ],
        "skipped": [],
        "errors": [],
    }
    for screen in listing["screens"]:
        (out / screen["file"]).write_bytes(b"png")
    (out / "screens.json").write_text(json.dumps(listing), encoding="utf-8")
    captures.append({"overlay": bool(overlay), "screens": screens})
    return listing


qa.rpgmaker_screens.capture = capture
task, state = qa.prepare_task(
    game, data, "release", temporary / "storage", interface=True
)
# The plugin's command is QA's to report; nothing QA holds is squeezed.
assert state["interface"] == {"captured": 2, "squeezed": 0, "outside": 1}, state


def outside():
    _places, found = qa._interface_places(
        qa.interface_capture(task)["folder"],
        json.loads((task / "inventory.json").read_text()),
    )
    return [row["text"] for row in found]


assert outside() == ["Monster Compendium"], outside()
# A plugin change that shortens the command and narrows the item list keeps
# the task and its review, and captures again: the command fits, and the
# weapon's name, now squeezed, goes to deep review.
configure("Bestiary", 20)
again, state = qa.prepare_task(
    game, data, "release", temporary / "storage", interface=True
)
assert again == task and len(captures) == 2, captures
assert state["interface"] == {"captured": 2, "squeezed": 1, "outside": 0}, state
assert outside() == [], outside()
observed = json.loads((task / "checkpoint.json").read_text())["observations"]
assert [(row["identity"].split("@")[0], row["worker"]) for row in observed] == [
    ("Weapons.json#/1/_original/name", "interface")
], observed
# Unchanged plugin files keep the capture.
qa.prepare_task(game, data, "release", temporary / "storage", interface=True)
assert len(captures) == 2, captures
shown = {}
# The items each stage's reviewers took.
reviewed = {}


def review(row):
    bundle = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
    rendered = qa.render_bundle(task, row["id"])
    shown[bundle["stage"]] = rendered
    reviewed.setdefault(bundle["stage"], []).extend(
        item["id"].split("@")[0] for item in bundle["items"]
    )
    common = {"bundle_id": row["id"], "bundle_sha256": row["sha256"]}
    if bundle["stage"] == "screen":
        value = {
            "schema": qa.SCREEN_RESULT_SCHEMA,
            **common,
            "reviewed_all": True,
            "exceptions": [],
            "motif_reviews": [],
            "declined": [],
        }
    elif bundle["stage"] == "deep":
        value = {
            "schema": qa.DEEP_RESULT_SCHEMA,
            **common,
            "reviews": [
                {
                    "id": item["id"],
                    "disposition": "actionable",
                    "severity": "medium",
                    "category": "ui",
                    "family_key": "",
                    "motif_ids": [],
                    "evidence": "The item list squeezes it.",
                    "correction": SHORT if "/1/" in item["id"] else SHORT_SPEAR,
                    "apply_identities": [],
                }
                for item in bundle["items"]
            ],
        }
    else:
        value = {
            "schema": qa.EDITORIAL_RESULT_SCHEMA,
            **common,
            "reviews": [
                {"id": item["id"], "verdict": "accept", "note": ""}
                for item in bundle["items"]
            ],
        }
    path = temporary / f"{row['id']}.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    qa.accept_result(task, path)


def complete():
    while qa.status(task)["stage"] != "complete":
        rows = [row for worker in ("a", "b") if (row := qa.next_bundle(task, worker))]
        for row in rows:
            review(row)
        if not rows:
            qa.finalize(task)


complete()
# The deep reviewer read which screen squeezed the name, and its capture.
assert "check interface-fit" in shown["deep"] and "Items: Weapons" in shown["deep"]
assert str(qa.interface_capture(task)["folder"] / "items-2-01.png") in shown["deep"], (
    shown["deep"]
)
# Editorial read the screen captured again with the correction served in
# place of the game's data, which left the game's own file alone.
assert "corrected screen, fits: Items: Weapons" in shown["editorial"], shown[
    "editorial"
]
assert captures[-1] == {"overlay": True, "screens": ["items"]}, captures
assert (
    json.loads((data / "Weapons.json").read_text(encoding="utf-8"))[1]["name"] == LONG
)
(finding,) = json.loads((task / "findings.json").read_text(encoding="utf-8"))[
    "findings"
]
assert (finding["current"], finding["correction"]) == (LONG, SHORT), finding
# Once QA is complete, a line a later capture finds squeezed sends QA back to
# deep review for it, keeping the review done so far; nothing applies the
# earlier findings meanwhile, and later tasks stop building on its reviews
# until it is complete again.
spear_pair = qa._pair_key("古代の槍", SPEAR)
assert spear_pair in qa._task_ledger(task)["pairs"]
configure("Bestiary", 10)
reviewed.clear()
again, state = qa.prepare_task(
    game, data, "release", temporary / "storage", interface=True
)
assert again == task and state["stage"] == "deep", state
assert state["interface"] == {"captured": 2, "squeezed": 2, "outside": 0}, state
assert not (task / "findings.json").exists()
assert qa._task_ledger(task) is None
complete()
sword, spear = json.loads((task / "findings.json").read_text(encoding="utf-8"))[
    "findings"
]
assert (sword["id"], sword["current"], sword["correction"]) == (
    finding["id"],
    LONG,
    SHORT,
), sword
assert (spear["current"], spear["correction"]) == (SPEAR, SHORT_SPEAR), spear
# Only the spear was reviewed again, and only its correction went to editorial.
assert reviewed == {
    "deep": ["Weapons.json#/2/_original/name"],
    "editorial": [spear["id"]],
}, reviewed
assert "check interface-fit" in shown["deep"] and SPEAR in shown["deep"], shown["deep"]
# The spear's correction waits to be applied, so its line no longer counts as
# reviewed and standing.
assert spear_pair not in qa._task_ledger(task)["pairs"]
print("ok")
