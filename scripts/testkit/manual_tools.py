"""Plays a Manual project's own tools for test scenarios: an extractor that
writes an RPG Maker MV/MZ game's messages and choices into a translation
file, and an injector that writes a translated one back. Like a user's own
tools, it reads and writes the game's JSON itself, with no DazedTL code.

    python scripts/testkit/manual_tools.py extract --game GAME --out FILE
    python scripts/testkit/manual_tools.py inject --game GAME --file FILE

extract writes each message (a 101 window's 401 rows, joined by newlines)
and each choice as a line with an empty translation, IDs naming the file
and the JSON pointer of the text; inject writes every translated line back
over the rows its ID names, the rows left over in the last one, and says
how many it wrote.
"""

import argparse
import json
import re
from pathlib import Path

JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def data_folder(game):
    for folder in (game / "data", game / "www" / "data"):
        if folder.is_dir():
            return folder
    raise SystemExit("No RPG Maker MV/MZ data folder in " + str(game))


def command_lists(node, pointer=""):
    if isinstance(node, dict):
        if isinstance(node.get("list"), list):
            yield pointer + "/list", node["list"]
        for key, value in node.items():
            if key != "list":
                yield from command_lists(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from command_lists(value, f"{pointer}/{index}")


def lines(name, document):
    for listed, commands in command_lists(document):
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                continue
            if command.get("code") == 101:
                rows = []
                for row in commands[index + 1 :]:
                    if not isinstance(row, dict) or row.get("code") != 401:
                        break
                    rows.append(row["parameters"][0])
                text = "\n".join(rows)
                if JAPANESE.search(text):
                    yield {
                        "id": f"{name}#{listed}/{index}",
                        "scene": f"{name}#{listed}",
                        "group": name,
                        "kind": "dialogue",
                        "source": text,
                        "translation": None,
                    }
            elif command.get("code") == 102:
                for choice, text in enumerate(command["parameters"][0]):
                    if JAPANESE.search(text):
                        yield {
                            "id": f"{name}#{listed}/{index}/parameters/0/{choice}",
                            "scene": f"{name}#{listed}",
                            "group": name,
                            "kind": "ui",
                            "source": text,
                            "translation": None,
                        }


def extract(game, out):
    found = []
    for path in sorted(data_folder(game).glob("*.json")):
        if path.name.startswith("Map") or path.name == "CommonEvents.json":
            found.extend(lines(path.name, json.loads(path.read_text("utf-8-sig"))))
    out.write_text(
        json.dumps(
            {"format": "dazedtl-translation", "version": 1, "lines": found},
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )
    print(json.dumps({"lines": len(found)}))


def resolve(document, pointer):
    node = document
    for part in pointer.strip("/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def inject(game, file):
    folder = data_folder(game)
    by_file = {}
    for line in json.loads(file.read_text("utf-8"))["lines"]:
        if line["translation"]:
            name, pointer = line["id"].split("#", 1)
            by_file.setdefault(name, []).append((pointer, line["translation"]))
    written = 0
    for name, rows in by_file.items():
        path = folder / name
        document = json.loads(path.read_text("utf-8-sig"))
        for pointer, text in rows:
            if "/parameters/0/" in pointer:
                head, choice = pointer.rsplit("/parameters/0/", 1)
                resolve(document, head)["parameters"][0][int(choice)] = text
            else:
                listed, index = pointer.rsplit("/", 1)
                commands = resolve(document, listed)
                rows_at = []
                for at in range(int(index) + 1, len(commands)):
                    if commands[at].get("code") != 401:
                        break
                    rows_at.append(at)
                parts = text.split("\n")
                parts += [""] * (len(rows_at) - len(parts))
                parts = parts[: len(rows_at) - 1] + [
                    "\n".join(parts[len(rows_at) - 1 :])
                ]
                for at, part in zip(rows_at, parts):
                    commands[at]["parameters"][0] = part
            written += 1
        path.write_text(json.dumps(document, ensure_ascii=False), "utf-8")
    print(json.dumps({"written": written}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["extract", "inject"])
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--file", type=Path)
    arguments = parser.parse_args()
    if arguments.step == "extract":
        extract(arguments.game, arguments.out)
    else:
        inject(arguments.game, arguments.file)


if __name__ == "__main__":
    main()
