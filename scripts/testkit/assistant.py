"""Plays the coding assistant of an Assistant-led project in agent mode, for
test scenarios: each step runs the project helper the way the starting prompt
tells an assistant to, and game text moves only through DazedTL's operations.

    python scripts/testkit/assistant.py STEP --helper-json HELPER --game GAME

STEP is setup (identify, back up, prepare, set up Git), organize (list the
game's Japanese as source units and organize them into a run), translate
[--requests N] (answer the run's requests in order, the first N only when
given), write (write every saved translation into the game, checking that
the choice labels and help markers the game finds by their Japanese stay) or
checkpoint, the operation assistants started before the app checkpointed
their work ran. Each step reports the phase it enters, as the starting
prompt asks, and write reports QA once it is done.
HELPER is a JSON list: the project helper's command without its subcommand.
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
WORK = ".dazedtl/len-method/work"
MANIFEST = f"{WORK}/manifest.json"


class Assistant:
    def __init__(self, helper: list[str], game: Path):
        self.command = helper
        self.game = game
        self.work = game / WORK
        self.work.mkdir(parents=True, exist_ok=True)
        self.state = self.work / "scripted-assistant.json"
        # A VX Ace game's text is translated in its JSON exports.
        self.ace = any(game.glob("Data/*.rvdata2"))
        self.data = "ace_json" if self.ace else "data"

    def helper(self, *args):
        result = subprocess.run(
            [*self.command, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode:
            raise SystemExit(f"helper {' '.join(args)} failed: {result.stderr.strip()}")
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def operation(self, action, arguments=None, minutes=10):
        path = self.work / f"op-{action}.json"
        path.write_text(
            json.dumps(arguments or {}, ensure_ascii=False), encoding="utf-8"
        )
        job = self.helper("operation", action, "--arguments-file", str(path))
        run = self.helper("run", "--run", job["id"], "--wait", str(minutes))
        if run["status"] != "complete":
            raise SystemExit(f"{action}: {json.dumps(run, ensure_ascii=False)[:2000]}")
        return run

    def report(self, phase):
        path = self.work / "report.json"
        path.write_text(json.dumps({"phase": phase}), encoding="utf-8")
        self.helper("progress", "--input", path.relative_to(self.game).as_posix())

    def remembered(self):
        if self.state.is_file():
            return json.loads(self.state.read_text(encoding="utf-8"))
        return {}

    def remember(self, **values):
        self.state.write_text(
            json.dumps({**self.remembered(), **values}, ensure_ascii=False),
            encoding="utf-8",
        )

    def setup(self):
        self.helper("state")
        self.report("preparation")
        evidence = self.work / "engine.md"
        evidence.write_text(
            "RPG Maker VX Ace: Data/*.rvdata2 and Game.ini.\n"
            if self.ace
            else "RPG Maker MV/MZ: data/System.json and js/plugins.js.\n",
            encoding="utf-8",
        )
        engine = "RPG Maker VX Ace" if self.ace else "RPG Maker MZ"
        self.helper("identify", "--engine", engine, "--evidence", f"{WORK}/engine.md")
        self.operation("backup_source")
        self.operation("rpgmaker_prepare")
        files = sorted(
            f"{self.data}/{path.name}"
            for path in (self.game / self.data).glob("*.json")
        )
        if self.ace:
            files += sorted(
                f"Data/{path.name}" for path in (self.game / "Data").glob("*.rvdata2")
            )
        else:
            files.append("js/plugins.js")
        (self.game / MANIFEST).write_text(
            json.dumps({"files": files}), encoding="utf-8"
        )
        self.operation(
            "git_setup", {"version": "1.0", "untranslated": True, "manifest": MANIFEST}
        )

    def help_markers(self):
        """The comment heads MPP_ChoiceEX shows as a choice's help, from its
        Choice Help Commands parameter, as the game's plugins.js sets it."""
        plugins = self.game / "js/plugins.js"
        if not plugins.is_file():
            return frozenset()
        text = plugins.read_text(encoding="utf-8-sig")
        listed = json.loads(text[text.index("[") : text.rindex("]") + 1])
        return frozenset(
            marker
            for plugin in listed
            if plugin.get("name") == "MPP_ChoiceEX" and plugin.get("status")
            for marker in json.loads(
                plugin.get("parameters", {}).get("Choice Help Commands") or "[]"
            )
        )

    def units(self):
        rows = []
        markers = self.help_markers()
        for path in sorted((self.game / self.data).glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            for pointer, text in walk(document, markers=markers):
                rows.append(
                    {
                        "id": f"{path.stem}{pointer}",
                        "group": path.stem,
                        "scene": path.stem,
                        "source": text,
                        "kind": "dialogue" if "/list/" in pointer else "ui",
                        "speaker": None,
                    }
                )
        return rows

    def organize(self):
        self.report("extraction")
        source = self.work / "source-units.json"
        source.write_text(
            json.dumps({"version": 1, "units": self.units()}, ensure_ascii=False),
            encoding="utf-8",
        )
        organized = self.helper("organize", "--input", f"{WORK}/source-units.json")
        self.remember(run=organized.get("run", organized)["id"])

    def translate(self, requests=None):
        self.report("translation")
        run = self.remembered()["run"]
        index, total = 0, 1
        while index < total and (requests is None or index < requests):
            out = self.work / f"request-{index}.json"
            self.helper(
                "request", "--run", run, "--index", str(index), "--output", str(out)
            )
            reply = json.loads(out.read_text(encoding="utf-8"))
            total, request = reply["total"], reply["request"]
            if request.get("accepted"):
                index += 1
                continue
            translations = {
                key: english(key, value) for key, value in request["sources"].items()
            }
            receipt = self.work / f"receipt-{index}.json"
            receipt.write_text(
                json.dumps(
                    {
                        "request_sha256": request["fingerprint"],
                        "translations": translations,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.helper(
                "accept",
                "--run",
                run,
                "--batch",
                request["id"],
                "--input",
                receipt.relative_to(self.game).as_posix(),
            )
            index += 1
        return self.helper("run", "--run", run)

    def write(self):
        self.report("injection")
        saved = self.helper("results", "--run", self.remembered()["run"])
        results = json.loads((self.game / saved["path"]).read_text(encoding="utf-8"))
        by_file: dict[str, dict[str, str]] = {}
        for identity, value in results.get("translations", results).items():
            name, _, pointer = identity.partition("/")
            by_file.setdefault(name, {})["/" + pointer] = value
        staged = self.work / "staged" / self.data
        staged.mkdir(parents=True, exist_ok=True)
        markers = self.help_markers()
        for name, pointers in sorted(by_file.items()):
            game_file = self.game / self.data / f"{name}.json"
            document = json.loads(game_file.read_text(encoding="utf-8-sig"))
            before = list(kept(document, markers=markers))
            for pointer, value in pointers.items():
                set_pointer(document, pointer, value)
            (staged / f"{name}.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8"
            )
            self.operation(
                "write_rpgmaker",
                {
                    "source": f"{self.data}/{name}.json",
                    "translated": f"{WORK}/staged/{self.data}/{name}.json",
                    "output": f"{self.data}/{name}.json",
                },
            )
            # The labels and markers the game finds by their Japanese stay; a
            # write may add or remove commands, so they compare in order.
            after = list(
                kept(
                    json.loads(game_file.read_text(encoding="utf-8-sig")),
                    markers=markers,
                )
            )
            if [value for _, value in after] != [value for _, value in before]:
                raise SystemExit(
                    f"write_rpgmaker changed kept text in {name}: "
                    + json.dumps({"before": before, "after": after}, ensure_ascii=False)
                )
        self.report("qa")

    def checkpoint(self):
        self.operation(
            "checkpoint",
            {"manifest": MANIFEST, "message": "translation: write English"},
        )


def kept_parameters(node, markers):
    """The parameters of a command a structural extractor keeps: a choice
    branch's label (402), which mirrors its choice while the engine branches
    on the index, and a choice help comment's head (108), the marker
    MPP_ChoiceEX finds the help by."""
    code, parameters = node.get("code"), node.get("parameters")
    if code == 402:
        return {1}
    if code == 108 and parameters and parameters[0] in markers:
        return {0}
    return set()


def walk(node, pointer="", markers=frozenset()):
    """Every Japanese string, leaving out the kept parameters and move routes
    (205, their steps repeated in 505, and an event page's own), whose
    scripts players never read."""
    if isinstance(node, dict):
        if node.get("code") in {205, 505}:
            return
        indexes = kept_parameters(node, markers)
        for key, value in node.items():
            if key in {"_original", "moveRoute"}:
                continue
            if key == "parameters" and indexes:
                for index, item in enumerate(value):
                    if index not in indexes:
                        yield from walk(item, f"{pointer}/{key}/{index}", markers)
            else:
                yield from walk(value, f"{pointer}/{key}", markers)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{pointer}/{index}", markers)
    elif isinstance(node, str) and JAPANESE.search(node):
        yield pointer, node


def kept(node, pointer="", markers=frozenset()):
    """Each kept parameter, by pointer."""
    if isinstance(node, dict):
        for index in kept_parameters(node, markers):
            yield f"{pointer}/parameters/{index}", node["parameters"][index]
        children = ((key, value) for key, value in node.items() if key != "_original")
    elif isinstance(node, list):
        children = enumerate(node)
    else:
        return
    for key, value in children:
        yield from kept(value, f"{pointer}/{key}", markers)


def set_pointer(document, pointer, value):
    parts = pointer.split("/")[1:]
    node = document
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    if isinstance(node, list):
        node[int(parts[-1])] = value
    else:
        node[parts[-1]] = value


def english(identity, source):
    """Readable English that keeps the line count, unique to the line."""
    return "\n".join(
        f"Tested line {hashlib.sha256(f'{identity}:{number}'.encode()).hexdigest()[:6]}."
        for number in range(len(source.split("\n")))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=str(__doc__).split("\n", 1)[0])
    parser.add_argument(
        "step", choices=["setup", "organize", "translate", "write", "checkpoint"]
    )
    parser.add_argument("--helper-json", required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--requests", type=int)
    args = parser.parse_args()
    assistant = Assistant(json.loads(args.helper_json), args.game)
    if args.step == "translate":
        print(json.dumps(assistant.translate(args.requests), ensure_ascii=False))
    else:
        getattr(assistant, args.step)()


if __name__ == "__main__":
    main()
