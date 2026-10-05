"""Durable preparation stages, separate from the untouched backup and Git baseline."""

from copy import deepcopy
from pathlib import Path

from dazedtl.storage import write_json
from .files import digest, project_path, read_json

LABELS = {
    "format_data": "Format game data",
    "format_plugins": "Format plugins.js",
    "gameupdate": "Create GameUpdate files",
}


def actions(native):
    return [
        "format_data",
        *(["format_plugins"] if native.get("plugins") else []),
        "gameupdate",
    ]


def has_data(native):
    return any(path.is_file() for path in Path(native["data"]).glob("*.json"))


def require_data(native):
    if not has_data(native):
        message = (
            "Convert the native Ace data to JSON first, then return to preparation."
            if native.get("engine") == "ACE"
            else "No game JSON is available. Check the selected game's data folder before preparation."
        )
        raise ValueError(message)


def fingerprint(native, observed=None):
    root, data = Path(native["source"]), Path(native["data"])
    paths = list(data.rglob("*.json"))
    if native.get("plugins"):
        plugins = Path(native["plugins"])
        paths.extend([plugins, plugins.parent / "plugins/TranslationUpdateCheck.js"])
    paths.extend(root.glob("GameUpdate*"))
    paths.extend((root / "gameupdate").rglob("*"))
    files = {}
    for path in paths:
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            checked = project_path(root, relative)
            files[relative] = (
                observed(checked) if observed else digest(checked.read_bytes())
            )
    return digest(files)


def state(native, folder, *, active=False, observed=None):
    path = project_path(folder, "preparation.json", exists=False)
    saved = read_json(path) if path.exists() else {}
    valid = (
        has_data(native)
        and saved.get("project_id") == native["id"]
        and saved.get("source") == native["source"]
        and (active or saved.get("fingerprint") == fingerprint(native, observed))
    )
    stages = [
        {"action": name, "label": LABELS[name], "status": "pending", "message": ""}
        for name in actions(native)
    ]
    if valid:
        for row in stages:
            previous = next(
                (
                    item
                    for item in saved.get("stages", [])
                    if item.get("action") == row["action"]
                ),
                None,
            )
            if previous:
                row.update(previous)
                if row["status"] == "running" and not active:
                    row.update(
                        status="interrupted",
                        message="Preparation stopped before this stage finished.",
                    )
    return {
        "complete": all(row["status"] == "complete" for row in stages),
        "stages": stages,
        "configuration": saved.get("configuration", "") if valid else "",
    }


def configuration(native):
    path = project_path(native["source"], "gameupdate/patch-config.txt", exists=False)
    if not path.is_file():
        return "GameUpdate files installed; patch configuration is missing. Configure patch delivery before release."
    if "YOUR_PATCH_REPO" in path.read_text(encoding="utf-8"):
        return "GameUpdate files installed; choose the patch repository before release."
    return "GameUpdate configuration file is present. Its delivery connection has not been tested."


def run(plan, log, execute, guard):
    native, folder = plan["project"], plan["folder"]
    if plan["action"] in {"prepare_game", "format_data"}:
        require_data(native)
    value = state(native, folder)
    selected = actions(native) if plan["action"] == "prepare_game" else [plan["action"]]
    path = project_path(folder, "preparation.json", exists=False)

    def save():
        write_json(
            path,
            {
                **value,
                "project_id": native["id"],
                "source": native["source"],
                "fingerprint": fingerprint(native),
            },
        )

    for row in value["stages"]:
        if (
            row["action"] not in selected
            or plan["action"] == "prepare_game"
            and row["status"] == "complete"
        ):
            continue
        row.update(status="running", message="")
        save()
        try:
            log(
                row["label"] + "…"
            )  # The worker checks cancellation before every stage.
            current = {
                **deepcopy(plan),
                "action": row["action"],
                "label": row["label"],
                "guard": guard(native, folder),
            }
            result = execute(current, log)
            if isinstance(result, dict) and result.get("ok") is False:
                raise ValueError(result.get("message") or row["label"] + " failed.")
            row.update(status="complete", result=result)
            if row["action"] == "gameupdate":
                value["configuration"] = configuration(native)
            save()
        except Exception as error:
            row.update(
                status="stopped" if isinstance(error, InterruptedError) else "failed",
                message=str(error),
            )
            save()
            raise
    value["complete"] = all(row["status"] == "complete" for row in value["stages"])
    save()
    return value
