"""Interface captures in the text QA engine, on a generated game.

The capture runs the game in Electron, so a stand-in writes what it would:
the item list squeezes a weapon's name and the menu squeezes a plugin's
command. Reviewers are played with fixed results, from the deep check that
names the capture to the editorial pass that reads the corrected one.
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
        ],
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
(data / "System.json").write_text(json.dumps({"gameTitle": "Test"}), encoding="utf-8")
captures = []


def capture(
    data_root, out_dir, *, overlay=None, screens=None, choices=None, all_choices=False
):
    """What the capture writes: before corrections, a squeezed weapon name and
    plugin command; after, the weapon as the corrected data names it."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = LONG
    if overlay:
        name = json.loads(
            Path(overlay["data/Weapons.json"]).read_text(encoding="utf-8")
        )[1]["name"]
    squeezed = {"squeezed": 0.7} if len(name) > 20 else {}
    listing = {
        "game": {"engine": "MZ", "width": 816, "height": 624},
        "screens": [
            {
                "name": "items-2-01",
                "file": "items-2-01.png",
                "title": "Items: Weapons",
                "labels": [{"text": name, "window": "Window_ItemList", **squeezed}],
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
                            {
                                "text": "Monster Compendium",
                                "window": "Window_MenuCommand",
                                "squeezed": 0.75,
                            }
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
# The squeezed name goes to deep review; the plugin's command is QA's to report.
assert state["interface"] == {"captured": 2, "squeezed": 1, "outside": 1}, state
forced = json.loads((task / "checkpoint.json").read_text())["deep"]["candidate_reasons"]
assert [candidate["reasons"] for candidate in forced.values()] == [["interface-fit"]], (
    forced
)
_places, outside = qa._interface_places(
    task / qa.INTERFACE_FOLDER, json.loads((task / "inventory.json").read_text())
)
assert [row["text"] for row in outside] == ["Monster Compendium"], outside
shown = {}


def review(row):
    bundle = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
    rendered = qa.render_bundle(task, row["id"])
    shown[bundle["stage"]] = rendered
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
                    "correction": SHORT,
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


while qa.status(task)["stage"] != "complete":
    rows = [row for worker in ("a", "b") if (row := qa.next_bundle(task, worker))]
    for row in rows:
        review(row)
    if not rows:
        qa.finalize(task)
# The deep reviewer read which screen squeezed the name, and its capture.
assert "check interface-fit" in shown["deep"] and "Items: Weapons" in shown["deep"]
assert str(task / qa.INTERFACE_FOLDER / "items-2-01.png") in shown["deep"], shown[
    "deep"
]
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
print("ok")
