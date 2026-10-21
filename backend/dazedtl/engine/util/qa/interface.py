"""Interface captures: the screens a task captures, where its text shows,
and the fit checks made from them."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from util import rpgmaker_blocks as blocks
from util import rpgmaker_rewrap as rewrap
from util import rpgmaker_screens, system
from util.paths import new_folder
from util.qa.fitting import _box, _fit, _operation_writes, _window, _written
from util.qa.records import _changes, _record_maps, _set_pointer
from util.qa.schema import _utc_now
from util.qa.selection import _cluster_by_identity
from util.qa.storage import _atomic_write_json, _read_json
from util.rpgmaker_qa_manifest import resolve_pointer
from util.rpgmaker_screens import screen_of, shown_text

# Captures of the game's interface screens, and those taken again with a
# finding's corrections in place, under the task's folder. Each capture is a
# round in a folder of its own, which the record beside them names with the
# plugin files it ran with, so a reused task captures again once they change.
INTERFACE_FOLDER = "interface"
CAPTURE_RECORD = "capture.json"
CAPTURE_SCHEMA = "rpgmaker-qa-capture-v1"
# The places one interface-fit check names before counting the rest.
INTERFACE_PLACES_LISTED = 3
_ENEMY_LETTER_RE = re.compile(r"\s?[A-ZＡ-Ｚ]$")
# Who notes the lines a capture taken again finds squeezed.
RECAPTURE_OBSERVER = "interface"


def _capture_record(root: Path) -> dict[str, Any] | None:
    path = root / INTERFACE_FOLDER / CAPTURE_RECORD
    return _read_json(path) if path.is_file() else None


def interface_capture(task_dir: str | Path) -> dict[str, Any] | None:
    """A task's latest interface capture: its round, its folder and what it
    found; None for a task prepared without one."""
    root = Path(task_dir)
    record = _capture_record(root)
    if record:
        return {
            "round": record["round"],
            "folder": root / INTERFACE_FOLDER / record["folder"],
            "summary": record["summary"],
        }
    # A task from before captures kept a record has its one capture in the
    # folder itself.
    found = _read_json(root / "task.json").get("interface")
    if not found:
        return None
    return {
        "round": 1,
        "folder": root / INTERFACE_FOLDER,
        "summary": found,
    }


def _capture_folder(root: Path) -> Path:
    found = interface_capture(root)
    return found["folder"] if found else root / INTERFACE_FOLDER


def _capture_round(
    data: Path,
    root: Path,
    number: int,
    manifest: dict[str, Any],
    progress: Callable[[str], None] | None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Capture the interface screens as round *number* of the task in *root*:
    its record, unsaved, and where each cluster's text shows squeezed."""
    plugins = rpgmaker_screens.plugins_sha256(data)
    name = f"round-{number}"
    staging = new_folder(root / INTERFACE_FOLDER, f".{name}.")
    try:
        summary = _capture_interface(data, staging, progress)
        # A round an interrupted prepare left behind is in no record.
        system.remove_tree(root / INTERFACE_FOLDER / name, ignore_errors=True)
        system.replace(staging, root / INTERFACE_FOLDER / name)
    except BaseException:
        system.remove_tree(staging, ignore_errors=True)
        raise
    places, outside = _interface_places(root / INTERFACE_FOLDER / name, manifest)
    record = {
        "schema": CAPTURE_SCHEMA,
        "round": number,
        "folder": name,
        "captured_at": _utc_now(),
        # A capture that failed is of no plugin files, so the next prepare
        # tries again.
        "plugins_sha256": None if summary.get("error") else plugins,
        "summary": summary | {"squeezed": len(places), "outside": len(outside)},
    }
    return record, places


def _save_capture_record(root: Path, record: dict[str, Any]) -> None:
    _atomic_write_json(root / INTERFACE_FOLDER / CAPTURE_RECORD, record)


def _capture_interface(
    data: Path, folder: Path, progress: Callable[[str], None] | None
) -> dict[str, Any]:
    """Capture the game's interface screens into *folder*; how many, and why
    none or some could not be."""
    try:
        listing = rpgmaker_screens.capture(data, folder, progress=progress)
    except rpgmaker_screens.WindowUnavailable as error:
        return {"captured": 0, "error": str(error)}
    return {
        "captured": len(listing["screens"]),
        **({"skipped": listing["skipped"]} if listing["skipped"] else {}),
        **(
            {"error": "; ".join(listing["errors"][:3])}
            if not listing["screens"] and listing["errors"]
            else {}
        ),
    }


def _interface_places(
    folder: Path, manifest: dict[str, Any]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Where each cluster's text shows squeezed or cut off in the captures in
    *folder*, and that text the inventory holds no line of, such as a
    plugin's."""
    listing_path = folder / "screens.json"
    if not listing_path.is_file():
        return {}, []
    listing = _read_json(listing_path)
    cluster_of = _cluster_by_identity(manifest)
    by_text: dict[str, set[str]] = defaultdict(set)
    for record in manifest["records"]:
        shown = shown_text(record["live"])
        if shown and "\n" not in shown:
            by_text[shown].add(cluster_of[record["identity"]])
    places: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outside: dict[str, dict[str, Any]] = {}
    for screen in listing["screens"]:
        for label in screen.get("labels") or []:
            if not (label.get("squeezed") or label.get("clipped")):
                continue
            place = {
                "title": screen["title"],
                "capture": str(folder / screen["file"]),
                **{key: label[key] for key in ("squeezed", "clipped") if key in label},
            }
            # A battle names repeated enemies with a letter, such as "Slime Ａ".
            clusters = by_text.get(shown_text(label["text"])) or by_text.get(
                _ENEMY_LETTER_RE.sub("", shown_text(label["text"]))
            )
            if not clusters:
                outside.setdefault(label["text"], {"text": label["text"], **place})
            for cluster_id in sorted(clusters or ()):
                if place["capture"] not in {
                    earlier["capture"] for earlier in places[cluster_id]
                }:
                    places[cluster_id].append(place)
    return dict(places), list(outside.values())


def _place_text(place: dict[str, Any]) -> str:
    how = (
        "cut off" if place.get("clipped")
        else f"squeezed to {round(place['squeezed'] * 100)}% of the width it needs"
    )
    return f"{place['title']}: {how}, {place['capture']}"


def _fit_checks(
    manifest: dict[str, Any], layout: dict[str, Any]
) -> dict[str, list[dict[str, str]]]:
    """Text in a window of fixed height, such as a help window, that needs
    more rows than the window shows even wrapped to the Line widths, by
    cluster; DazedTL cannot fit it, so a reviewer shortens it."""
    cluster_of = {
        identity: cluster["representative"]
        for cluster in manifest["clusters"]
        for identity in cluster["identities"]
    }
    found: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in manifest["records"]:
        window = _window(record, layout)
        live = str(record.get("live") or "")
        if (
            window is None or window.paged or not window.rows or window.kind == "note"
            or not live.strip() or rewrap.untranslated(live)
        ):
            continue
        box = _box(record, layout)
        written = _fit(live, live, box, str(record.get("source") or ""))
        if reason := rewrap.misfit(written, window):
            note = f"Wrapped to the game's Line widths, this text {reason}."
        elif box.get("help") and (
            reason := rewrap.rows_misfit(
                blocks.help_shown(box["help"], written.split("\n")), window
            )
        ):
            note = (
                "Wrapped to the game's Line widths and shown with the rest of its "
                f"choice help, this text {reason}."
            )
        if reason:
            entry = {"check": "text-fit", "note": note}
            if entry not in found[cluster_of[record["identity"]]]:
                found[cluster_of[record["identity"]]].append(entry)
    return dict(found)


def _interface_checks(
    folder: Path, manifest: dict[str, Any]
) -> dict[str, list[dict[str, str]]]:
    """Text the game squeezes or cuts off on a captured screen, by cluster,
    naming the captures that show it."""
    places, _outside = _interface_places(folder, manifest)
    checked = {}
    for cluster_id, found in places.items():
        listed = "; ".join(_place_text(place) for place in found[:INTERFACE_PLACES_LISTED])
        more = len(found) - INTERFACE_PLACES_LISTED
        checked[cluster_id] = [{
            "check": "interface-fit",
            "note": "The game draws this text with too little room. "
            + listed + (f"; and {more} more" if more > 0 else ""),
        }]
    return checked


def _interface_after(
    root: Path,
    task: dict[str, Any],
    manifest: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Captures of the screens that squeezed or cut off a finding's text, taken
    again with the corrections in place, by finding."""
    folder = _capture_folder(root)
    places, _outside = _interface_places(folder, manifest)
    if not places:
        return {}
    records, _clusters = _record_maps(manifest)
    cluster_of = _cluster_by_identity(manifest)
    data_root = Path(task["data_root"])
    shown_on: dict[str, list[dict[str, Any]]] = {}
    documents: dict[str, Any] = {}
    choices: dict[str, dict[str, Any]] = {}
    for finding in findings:
        if finding.get("kind") == "show-text":
            continue
        for change in _changes(finding):
            touched = [
                identity for identity in change["identities"]
                if cluster_of.get(identity) in places
            ]
            if not touched:
                continue
            shown_on[finding["id"]] = places[cluster_of[touched[0]]]
            for identity in change["identities"]:
                record = records[identity]
                if record["file"] not in documents:
                    documents[record["file"]] = json.loads(
                        (data_root / record["file"]).read_text(encoding="utf-8-sig")
                    )
                operation = {
                    "identity": identity,
                    "live_pointers": record["live_pointers"],
                    "live_transform": record["live_transform"],
                    "expected": record["live"],
                    "replacement": _written(
                        record, change["correction"], task.get("layout")
                    ),
                }
                try:
                    for pointer, value in _operation_writes(
                        documents[record["file"]], operation
                    ):
                        _set_pointer(documents[record["file"]], pointer, value)
                except ValueError:
                    continue
                if record.get("event_code") == 102:
                    command = record["live_pointers"][0].split("/parameters/")[0]
                    choices[f"{record['file']}#{command}"] = {
                        "file": record["file"], "command": command,
                    }
    if not shown_on:
        return {}
    rounds = sorted(folder.glob("after-*"))
    out = folder / f"after-{len(rounds) + 1}"
    overlay = {}
    for name, document in documents.items():
        path = out / "data" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        # By its path under the game's web folder, which holds the data folder.
        overlay[f"{data_root.resolve().name}/{name}"] = path
    choice_sets = []
    for key, where in choices.items():
        params = resolve_pointer(documents[where["file"]], where["command"] + "/parameters")
        choice_sets.append({
            "key": key,
            "choices": params[0],
            **{
                name: params[index]
                for index, name in enumerate(
                    ("cancelType", "defaultType", "positionType", "background"), start=1
                )
                if index < len(params)
            },
        })
    screens = sorted({
        screen_of(place["capture"])
        for found in shown_on.values() for place in found
    } - {""})
    try:
        listing = rpgmaker_screens.capture(
            data_root, out, overlay=overlay, screens=screens,
            choices=choice_sets, all_choices=True,
        )
    except rpgmaker_screens.WindowUnavailable as error:
        return {finding_id: [{"error": str(error)}] for finding_id in shown_on}
    after: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        if finding["id"] not in shown_on:
            continue
        texts = {shown_text(change["correction"]) for change in _changes(finding)}
        titles = {place["title"] for place in shown_on[finding["id"]]}
        found = []
        for screen in listing["screens"]:
            labels = [
                label for label in screen.get("labels") or []
                if shown_text(label["text"]) in texts
            ]
            if labels and (screen["title"] in titles or screen["name"].startswith("choices")):
                worst = min(labels, key=lambda label: label.get("squeezed", 1))
                found.append({
                    "title": screen["title"],
                    "capture": str(out / screen["file"]),
                    **{key: worst[key] for key in ("squeezed", "clipped") if key in worst},
                })
        after[finding["id"]] = found or [{
            "error": "The corrected text did not show on the screens captured again.",
        }]
    return after
