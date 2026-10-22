"""Plays the assistant of a copied Plugin files task, for test scenarios: it
answers each request the project helper returns until the task is complete,
finding every occurrence players see, or latent, and translating it in the
file's working copy with a small dictionary of the fixture games' Japanese.

    python scripts/testkit/plugin_assistant.py REQUEST --game GAME --helper-json HELPER

REQUEST is the request file the copied task names; GAME is the game folder.
HELPER is a JSON list: the project helper's command without its subcommand.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dazedtl import system
from dazedtl.plugins.documents import Documents, replace_leaf
from dazedtl.translation.files import digest

IDENTITY = ("version", "kind", "projectId", "requestId", "binding")
# The fixture games' plugin text; longer phrases first, so a phrase holding
# another is translated whole.
ENGLISH = {
    "ようこそ、魔法の世界へ！": "Welcome to the world of magic!",
    "まだ何も書かれていない。": "Nothing is written here yet.",
    "冒険日誌の記録": "Adventure log",
    "冒険の始まり": "The adventure begins",
    "冒険日誌": "Journal",
    "ようこそ": "Welcome",
    "日誌": "Journal",
}


def english(value):
    for japanese, words in ENGLISH.items():
        value = value.replace(japanese, words)
    return value


def report(request, files, **extra):
    value = {key: request[key] for key in IDENTITY}
    value.update(files=files, complete=True, **extra)
    Path(request["report"]).write_text(
        json.dumps(value, ensure_ascii=False), encoding="utf-8"
    )


def investigate(request, _game, _documents):
    report(
        request,
        [
            {
                "path": asked["path"],
                "sourceHash": asked["sourceHash"],
                "examined": True,
                "evidence": "A scripted assistant read each use in the fixture plugin.",
                "occurrences": [
                    {
                        "id": item["id"],
                        "disposition": "latent" if item["latent"] else "visible",
                        "safe": True,
                        "evidence": "The fixture plugin draws or shows it as is.",
                        "reason": "Players see it.",
                    }
                    for item in asked["occurrences"]
                ],
            }
            for asked in request["files"]
        ],
        dependencies=[],
    )


def literal(kind, raw, value):
    """`value` written back as the source literal `raw` was."""
    if kind == "default":
        return value
    if raw[0] == "`":
        return "`" + value + "`"
    if raw[0] == "'":
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return json.dumps(value, ensure_ascii=False)


def translate(request, game, documents):
    rows = []
    for asked in request["files"]:
        targets = {item["id"]: english(item["value"]) for item in asked["occurrences"]}
        raw = (game / asked["original"]).read_bytes()
        parsed = documents.parse(
            [{"path": asked["path"], "source": raw.decode(), "kind": asked["kind"]}]
        )[asked["path"]]
        tokens = {}
        for item in asked["occurrences"]:
            tokens.setdefault(item["token"], []).append(item)
        changes = []
        for token, items in tokens.items():
            found = parsed["literals"][token]
            value = found["value"]
            for item in items:
                value = replace_leaf(value, item["logical"], targets[item["id"]])
            changes.append(
                (
                    found["start"],
                    found["end"],
                    literal(found["kind"], found["raw"], value).encode(),
                )
            )
        for start, end, replacement in sorted(changes, reverse=True):
            raw = raw[:start] + replacement + raw[end:]
        (game / asked["candidate"]).write_bytes(raw)
        rows.append(
            {
                "path": asked["path"],
                "sourceHash": asked["sourceHash"],
                "candidateHash": digest(raw),
                "targets": targets,
                "evidence": "A scripted assistant translated each listed literal.",
            }
        )
    report(request, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=str(__doc__).split("\n", 1)[0])
    parser.add_argument("request", type=Path)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--helper-json", required=True)
    args = parser.parse_args()
    helper = json.loads(args.helper_json)
    documents = Documents()
    stages = {"investigation": investigate, "translation": translate}
    path, answered = args.request, []
    for _ in range(6):
        request = json.loads(path.read_text(encoding="utf-8"))
        if request["kind"] not in stages:
            raise SystemExit(f"The scripted assistant can't answer {request['kind']}.")
        stages[request["kind"]](request, args.game, documents)
        answered.append(request["kind"])
        reply = json.loads(
            system.run(
                [*helper, "plugins", "--continue-request", request["requestId"]],
                check=True,
                capture_output=True,
                encoding="utf-8",
            ).stdout
        )
        if reply.get("stage") == "complete":
            print(json.dumps({"stage": "complete", "answered": answered}))
            return
        path = Path(reply["request"])
    raise SystemExit(f"Plugin files did not complete after {answered}.")


if __name__ == "__main__":
    main()
