"""Plays the coding assistant of an Assistant-led project in agent mode, for
test scenarios: each step runs the project helper the way the starting prompt
tells an assistant to, and game text moves only through DazedTL's operations.

    python scripts/testkit/assistant.py STEP --helper-json HELPER --game GAME

STEP is setup (identify, record the original, prepare, set up Git), organize (list the
game's Japanese as source units and organize them into a run), translate
[--requests N] (answer the run's requests in order, the first N only when
given), write (write every saved translation into the game, checking that
the choice labels and help markers the game finds by their Japanese stay),
images (index the game's images and investigate them, recommending each
whose file name starts with text_), archived-images (decode a WOLF game's
Data/Picture.wolf into a folder, translate its text_ images through the
Images steps on that folder, pack it again and checkpoint it) or
checkpoint, the operation assistants
started before the app checkpointed their work ran. Each step reports the
phase it enters, as the starting prompt asks, and write reports QA once it
is done.
HELPER is a JSON list: the project helper's command without its subcommand.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
LATIN = re.compile(r"[A-Za-z]")
# A file name, a switch name or another identifier of an English game.
IDENTIFIER = re.compile(r"(?=[\w./-]*[\d_./])[\w./-]+")
WORK = ".dazedtl/len-method/work"
MANIFEST = f"{WORK}/manifest.json"
# The folder a WOLF game's Data/Picture.wolf is decoded into, which the game
# doesn't read, and the bundled WolfDawn that decodes and packs it.
DECODED = "decoded/Picture"
WOLF = str(
    Path(__file__).resolve().parents[2]
    / "backend/dazedtl/engine/util/wolfdawn/bin"
    / ("windows/wolf.exe" if os.name == "nt" else "linux/wolf")
)
# Where an assistant keeps its image recipes and the scripts they run.
RESOURCES = ".dazedtl/image_translation_resources"
RENDERER = f"{RESOURCES}/scripts/render.py"


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


class Assistant:
    def __init__(self, helper: list[str], game: Path):
        self.command = helper
        self.game = game
        self.work = game / WORK
        self.work.mkdir(parents=True, exist_ok=True)
        self.state = self.work / "scripted-assistant.json"
        # A VX Ace game's text is translated in its JSON exports.
        self.ace = any(game.glob("Data/*.rvdata2"))
        # A WOLF RPG Editor game keeps its files in Data's archives.
        self.wolf = any(game.glob("Data/*.wolf"))
        self.data = "ace_json" if self.ace else "data"
        # The game's language pair, which the game's own settings may name.
        settings = game / ".dazedtl/settings.json"
        languages = (
            json.loads(settings.read_text(encoding="utf-8-sig")).get("languages", {})
            if settings.is_file()
            else {}
        )
        self.source = languages.get("source", "Japanese")
        self.target = languages.get("target", "English")

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
            "WOLF RPG Editor: Game.exe and Data/*.wolf archives.\n"
            if self.wolf
            else "RPG Maker VX Ace: Data/*.rvdata2 and Game.ini.\n"
            if self.ace
            else "RPG Maker MV/MZ: data/System.json and js/plugins.js.\n",
            encoding="utf-8",
        )
        engine = (
            "WOLF RPG Editor"
            if self.wolf
            else "RPG Maker VX Ace"
            if self.ace
            else "RPG Maker MZ"
        )
        self.helper("identify", "--engine", engine, "--evidence", f"{WORK}/engine.md")
        self.operation("record_original")
        if self.wolf:
            # The archives the translation packs again are its patch.
            files = sorted(
                path.relative_to(self.game).as_posix()
                for path in self.game.glob("Data/*.wolf")
            )
            (self.game / MANIFEST).write_text(
                json.dumps({"files": files}), encoding="utf-8"
            )
            self.operation(
                "git_setup",
                {"version": "1.0", "untranslated": True, "manifest": MANIFEST},
            )
            return
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

    def images(self):
        """Indexes the game's images and saves a complete investigation that
        recommends the ones a game variant names text_, as lettered."""
        self.helper("images", "--scan")
        self.investigate()
        status = self.helper("images", "--status")
        print(json.dumps(status["counts"]))

    def investigate(self):
        """Saves a complete investigation that recommends each image named
        text_."""
        step = self.helper("images", "--investigate")
        request = json.loads(
            Path(step["task"]).with_suffix(".json").read_text(encoding="utf-8")
        )
        report = {
            "version": 1,
            "kind": "discovery",
            "projectId": request["projectId"],
            "requestId": request["id"],
            "inventoryRevision": request["inventoryRevision"],
            "complete": True,
            "assets": [
                {
                    "id": asset["id"],
                    "sourceHash": asset["sourceHash"],
                    "classification": "recommended"
                    if Path(asset["path"]).name.startswith("text_")
                    else "no_text",
                    "method": "visual",
                    "examined": True,
                    "reason": "",
                    "evidence": "contact sheet",
                    "variants": [],
                }
                for asset in request["assets"]
            ],
        }
        Path(step["report"]).write_text(json.dumps(report), encoding="utf-8")

    def archived_images(self):
        """Translates the images of a WOLF game's Data/Picture.wolf as the
        starting prompt says for images in archives: decoded with WolfDawn
        into a folder the game doesn't read, run through the Images steps on
        that folder, packed into the archive again and checkpointed. Prints
        what the steps and the patch's Git hold."""
        self.report("images")
        found = subprocess.run(
            [*self.command, "images", "--status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if not found.returncode:
            raise SystemExit("images --status read images before they were decoded")
        print("Before decoding:", found.stderr.strip())
        decoded = self.game / DECODED
        subprocess.run(
            [WOLF, "unpack", str(self.game / "Data/Picture.wolf"), "-o", str(decoded)],
            check=True,
            capture_output=True,
        )
        self.helper("images", "--scan", "--root", DECODED)
        self.investigate()
        step = self.helper("images", "--translate")
        request = json.loads(
            Path(step["task"]).with_suffix(".json").read_text(encoding="utf-8")
        )
        renderer = self.game / RENDERER
        renderer.parent.mkdir(parents=True, exist_ok=True)
        renderer.write_bytes(b"# The scripted assistant's renderer\n")
        manifest = {"version": 1, "recipes": {}}
        rows = []
        for asset in request["assets"]:
            # The lettering's corner painted over, inside the recipe's text
            # region.
            editable = self.game / asset["editable"]
            image = Image.open(editable)
            image.load()
            image.paste((200, 10, 10), (0, 0, 16, 16))
            image.save(editable, format="PNG")
            candidate = sha256(editable.read_bytes())
            manifest["recipes"][asset["id"]] = {
                "output": candidate,
                "command": ["{python}", RENDERER, asset["id"], "{output}"],
                "inputs": {
                    RENDERER: sha256(renderer.read_bytes()),
                    asset["frozen"]: asset["frozenHash"],
                },
                "check": {"text": [[0, 0, 16, 16]]},
            }
            rows.append(
                {
                    "id": asset["id"],
                    "sourceHash": asset["sourceHash"],
                    "candidateHash": candidate,
                    "status": "edited",
                    "reason": "",
                    "review": {
                        "version": 1,
                        "visual": True,
                        "alpha": True,
                        "protectedPixels": True,
                        "layout": True,
                        "evidence": "Compared original and candidate at native size.",
                    },
                }
            )
        (self.game / RESOURCES / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        Path(step["report"]).write_text(
            json.dumps(
                {
                    "version": 1,
                    "kind": "editing",
                    "projectId": request["projectId"],
                    "requestId": request["id"],
                    "inventoryRevision": request["inventoryRevision"],
                    "complete": True,
                    "assets": rows,
                }
            ),
            encoding="utf-8",
        )
        applied = self.helper("images", "--apply")
        if applied["next"] != "done" or applied["problems"]:
            raise SystemExit("images --apply: " + json.dumps(applied)[:2000])
        print("Applied:", ", ".join(applied["applied"]))
        print("Counts:", json.dumps(applied["counts"]))
        archive = self.game / "Data/Picture.wolf"
        subprocess.run(
            [WOLF, "pack", str(decoded), "-o", str(archive)],
            check=True,
            capture_output=True,
        )
        self.checkpoint("images: pack Picture.wolf again")
        # The patch, the translation branch, holds the packed archive with
        # the translated image and the CGs as they were.
        with tempfile.TemporaryDirectory() as folder:
            packed = Path(folder) / "Picture.wolf"
            packed.write_bytes(
                subprocess.run(
                    ["git", "-C", str(self.game), "show", "HEAD:Data/Picture.wolf"],
                    capture_output=True,
                    check=True,
                ).stdout
            )
            subprocess.run(
                [WOLF, "unpack", str(packed), "-o", str(Path(folder) / "out")],
                check=True,
                capture_output=True,
            )
            for name in ("text_title.png", "cg/cg_0000.png", "cg/cg_0001.png"):
                if (Path(folder) / "out" / name).read_bytes() != (
                    decoded / name
                ).read_bytes():
                    raise SystemExit(f"The patch's Picture.wolf differs at {name}")
        tracked = subprocess.run(
            ["git", "-C", str(self.game), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        print("Patch:", ", ".join(name for name in tracked if not name.startswith(".")))
        self.report("patch")

    def checkpoint(self, message="translation: write English"):
        self.operation("checkpoint", {"manifest": MANIFEST, "message": message})

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
            for pointer, text in walk(document, markers=markers, source=self.source):
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

    def answer(self, identity, source):
        return reply(identity, source, self.target)

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
                key: self.answer(key, value)
                for key, value in request["sources"].items()
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


def is_source(text, language):
    """Whether `text` is text of the game's source language: Japanese kana and
    kanji, or for English Latin letters in anything but an identifier."""
    if language == "English":
        return bool(LATIN.search(text)) and not IDENTIFIER.fullmatch(text)
    return bool(JAPANESE.search(text))


def walk(node, pointer="", markers=frozenset(), source="Japanese"):
    """Every string of the source language, leaving out the kept parameters and move routes
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
                        yield from walk(
                            item, f"{pointer}/{key}/{index}", markers, source
                        )
            else:
                yield from walk(value, f"{pointer}/{key}", markers, source)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{pointer}/{index}", markers, source)
    elif isinstance(node, str) and is_source(node, source):
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


def reply(identity, source, target="English"):
    """Readable text in the target language that keeps the line count, unique
    to the line."""
    return "\n".join(
        (f"テスト行{mark}。" if target == "Japanese" else f"Tested line {mark}.")
        for mark in (
            hashlib.sha256(f"{identity}:{number}".encode()).hexdigest()[:6]
            for number in range(len(source.split("\n")))
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=str(__doc__).split("\n", 1)[0])
    parser.add_argument(
        "step",
        choices=[
            "setup",
            "organize",
            "translate",
            "write",
            "images",
            "archived-images",
            "checkpoint",
        ],
    )
    parser.add_argument("--helper-json", required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--requests", type=int)
    args = parser.parse_args()
    assistant = Assistant(json.loads(args.helper_json), args.game)
    if args.step == "translate":
        print(json.dumps(assistant.translate(args.requests), ensure_ascii=False))
    else:
        getattr(assistant, args.step.replace("-", "_"))()


if __name__ == "__main__":
    main()
