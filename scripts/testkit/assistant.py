"""Plays the coding assistant of an Assistant-led project in agent mode, for
test scenarios: each step runs the project helper the way the starting prompt
tells an assistant to, and game text moves only through DazedTL's operations.

    python scripts/testkit/assistant.py STEP --helper-json HELPER --game GAME

STEP is setup (identify, record the original, prepare, set up Git), organize (list the
game's Japanese as source units and organize them into a run, with
--complete saying they cover all of it, as an API run needs, and --miss ID
leaving out the unit with that ID, as an extractor that misses a line players
read), translate
[--requests N] (answer the run's requests in order, the first N only when
given), write (write every saved translation into the game, checking that
the choice labels and help markers the game finds by their Japanese stay),
images (index the game's images and investigate them, recommending each
whose file name starts with text_), archived-images (decode a WOLF game's
Data/Picture.wolf into a folder, translate its text_ images through the
Images steps on that folder, pack it again and checkpoint it),
checkpoint, the operation assistants started before the app checkpointed
their work ran, play (run the release playtest and wait for it, printing
where it stands), untranslated (translate the text Text QA counts as never
translated through the extraction and injection steps, play the game and
prepare QA again, as qa's next step says, printing those locations and QA's status then),
check (for a TyranoScript game, run qa --check, correct two of its hits through
correction receipts, answer the third, write the game again and check again,
printing both checks and the hits),
qa-applied (report the
qa phase complete once Text QA's
apply saved its work, as qa's next step says), final-check (play the game
again after QA's apply, require the playtest to settle and report its
problems and coverage) or package (report QA done and package the patch).
Each step reports the phase it enters, as the starting prompt asks, and
write reports QA once it is done.
HELPER is a JSON list: the project helper's command without its subcommand.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

# The engine's helpers, for the WolfDawn build bundled for this system.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend/dazedtl/engine"))

JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
# Japanese punctuation, such as 「」 or ！？: the starting prompt has an
# extractor take a line of it without letters too, which the census counts
# as unsent and DazedTL writes without a request.
MARKS = re.compile(r"[\u3001-\u303f\uff01-\uff60]")
LATIN = re.compile(r"[A-Za-z]")
# A file name, a switch name or another identifier of an English game.
IDENTIFIER = re.compile(r"(?=[\w./-]*[\d_./])[\w./-]+")
WORK = ".dazedtl/len-method/work"
MANIFEST = f"{WORK}/manifest.json"
# The folder a WOLF game's Data/Picture.wolf is decoded into, which the game
# doesn't read.
DECODED = "decoded/Picture"
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
        # A TyranoScript game's text is its scenario scripts.
        self.tyrano = (game / "tyrano").is_dir()
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
            else "TyranoScript: tyrano and data/scenario/*.ks.\n"
            if self.tyrano
            else "RPG Maker VX Ace: Data/*.rvdata2 and Game.ini.\n"
            if self.ace
            else "RPG Maker MV/MZ: data/System.json and js/plugins.js.\n",
            encoding="utf-8",
        )
        engine = (
            "WOLF RPG Editor"
            if self.wolf
            else "TyranoScript"
            if self.tyrano
            else "RPG Maker VX Ace"
            if self.ace
            else "RPG Maker MZ"
        )
        self.helper("identify", "--engine", engine, "--evidence", f"{WORK}/engine.md")
        self.operation("record_original")
        if self.tyrano:
            # The investigation's glossary names the game's forest.
            self.glossary("エルフの森 (Elven Woods)")
        if self.wolf or self.tyrano:
            # The archives the translation packs again, or the scenarios it
            # writes, are its patch.
            files = sorted(
                path.relative_to(self.game).as_posix()
                for path in self.game.glob(
                    "Data/*.wolf" if self.wolf else "data/scenario/*.ks"
                )
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
        from util.wolfdawn import ensure_wolf_binary

        wolf = str(ensure_wolf_binary())
        decoded = self.game / DECODED
        subprocess.run(
            [wolf, "unpack", str(self.game / "Data/Picture.wolf"), "-o", str(decoded)],
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
            [wolf, "pack", str(decoded), "-o", str(archive)],
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
                [wolf, "unpack", str(packed), "-o", str(Path(folder) / "out")],
                check=True,
                capture_output=True,
            )
            for name in ("text_title.png", "cg/cg_0000.png", "cg/cg_0001.png"):
                if (Path(folder) / "out" / name).read_bytes() != (
                    decoded / name
                ).read_bytes():
                    raise SystemExit(f"The patch's Picture.wolf differs at {name}")
        tracked = subprocess.run(
            ["git", "-C", str(self.game), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\0")
        print(
            "Patch:",
            ", ".join(name for name in tracked if name and not name.startswith(".")),
        )
        self.report("patch")

    def glossary(self, entry):
        """Adds `entry` to the game's own glossary entries, before the base
        glossary's, as the setup investigation saves them."""
        from util.paths import GLOSSARY_BASE_SEPARATOR

        path = self.game / ".dazedtl/glossary.txt"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        own, separator, base = text.partition(GLOSSARY_BASE_SEPARATOR)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"{own.rstrip()}\n{entry}\n\n{separator}{base}", encoding="utf-8"
        )

    def scenario_lines(self):
        """A TyranoScript game's text lines by unit ID, with what each line
        keeps around its text: its file, line number, trailing tags and the
        speaker its #name line gives."""
        found = {}
        for path in sorted((self.game / "data/scenario").glob("*.ks")):
            speaker = None
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n")):
                if line.startswith("#"):
                    speaker = line[1:] or None
                    continue
                if not line or line[0] in "*[@;":
                    continue
                text = re.sub(r"(\[[a-z]+\])+$", "", line)
                found[f"{path.stem}/{number}"] = (
                    path,
                    number,
                    text,
                    line[len(text) :],
                    speaker,
                )
        return found

    def check(self):
        """Follows the QA step for an engine Text QA can't read: runs qa
        --check, corrects the forest's first line and the inn's price
        through correction receipts, answers the forest's second line,
        injects the corrections and checks again; returns both checks'
        counts and the hits."""
        first = self.helper("qa", "--check")
        report = json.loads((self.game / first["report"]).read_text(encoding="utf-8"))
        by_unit = {unit["unit"]: hit for hit in report["hits"] for unit in hit["units"]}
        expected = {
            "first/3": "glossary",
            "first/5": "visible-number-mismatch",
            "first/7": "glossary",
        }
        if {unit: hit["rule"] for unit, hit in by_unit.items()} != expected:
            raise SystemExit(
                "qa --check found other hits: "
                + json.dumps(report["hits"], ensure_ascii=False)[:2000]
            )
        corrected = {
            "first/3": "Welcome to the Elven Woods.",
            "first/5": "The inn costs 100 gold.",
        }
        run = self.remembered()["run"]
        index, total, receipts = 0, 1, {}
        while index < total:
            out = self.work / f"request-{index}.json"
            self.helper(
                "request", "--run", run, "--index", str(index), "--output", str(out)
            )
            reply = json.loads(out.read_text(encoding="utf-8"))
            total, request = reply["total"], reply["request"]
            fixes = {
                key: corrected[key] for key in request["sources"] if key in corrected
            }
            if fixes:
                receipts[request["id"]] = {
                    "request_sha256": request["fingerprint"],
                    "replaces_sha256": reply["result"]["result_sha256"],
                    "translations": {**reply["result"]["translations"], **fixes},
                }
            index += 1
        for number, (batch, receipt) in enumerate(receipts.items()):
            path = self.work / f"correction-{number}.json"
            path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            self.helper(
                "accept",
                "--run",
                run,
                "--batch",
                batch,
                "--input",
                path.relative_to(self.game).as_posix(),
            )
        answers = self.work / "qa-answers.json"
        answers.write_text(
            json.dumps(
                {
                    by_unit["first/7"][
                        "id"
                    ]: "Lili calls the forest by its old name here."
                }
            ),
            encoding="utf-8",
        )
        second = self.helper("qa", "--check", "--answers", str(answers))
        if second["open"] or second["answered"] != 1:
            raise SystemExit(f"qa --check after the corrections: {second}")
        self.write()
        return {"first": first, "second": second, "hits": report["hits"]}

    def checkpoint(self, message="translation: write English"):
        self.operation("checkpoint", {"manifest": MANIFEST, "message": message})

    def finished(self, phase=None, next_action=""):
        """Reports every phase through QA complete, which records QA's
        evidence, with `phase` the one now worked in: patch, or none while
        the assistant plays the game after QA."""
        done = dict.fromkeys(
            ("preparation", "extraction", "translation", "injection", "qa"),
            "complete",
        )
        path = self.work / "report.json"
        path.write_text(
            json.dumps(
                {
                    "phase": phase,
                    "text": f"{WORK}/translation-units.json",
                    "phases": {
                        **done,
                        "patch": "active" if phase == "patch" else "pending",
                    },
                    "next_action": next_action,
                }
            ),
            encoding="utf-8",
        )
        self.helper("progress", "--input", path.relative_to(self.game).as_posix())

    def play(self):
        """Runs the release playtest and waits for it, as the QA step says
        after injection and again after QA's apply; returns where it stands."""
        status = self.helper("playtest", "--run", "--wait", "20")
        if (status.get("operation") or {}).get("status") != "complete":
            raise SystemExit(
                "The playtest did not finish: "
                + json.dumps(status.get("operation"), ensure_ascii=False)
            )
        return status

    def untranslated(self):
        """Translates the never-translated text Text QA counts as
        untranslated through the extraction and injection steps, as qa's
        next step says: each listed location becomes a unit, which organize
        and translate answer, is written into the game, the game is played
        again and QA reads it again. Returns those locations and QA's status
        then."""
        status = self.helper("qa", "--status")
        if not status.get("untranslated"):
            raise SystemExit(f"Text QA counts no untranslated text: {status['next']}")
        listed = json.loads(
            (self.work / "qa-untranslated.json").read_text(encoding="utf-8")
        )["texts"]
        # The extractor: each location's text as the game holds it, since
        # QA's list cuts a long one short.
        found = {}
        for row in listed:
            document, node, key = self.located(row["file"], row["pointer"])
            found[f"qa:{row['file']}#{row['pointer']}"] = node[key]
        path = self.work / "source-units.json"
        units = json.loads(path.read_text(encoding="utf-8"))["units"]
        units += [
            {
                "id": identity,
                "group": "Other",
                "scene": "Other",
                "source": text,
                "kind": "ui",
                "speaker": None,
            }
            for identity, text in found.items()
        ]
        path.write_text(
            json.dumps({"version": 1, "units": units}, ensure_ascii=False),
            encoding="utf-8",
        )
        organized = self.helper(
            "organize", "--input", f"{WORK}/source-units.json", "--complete"
        )
        self.remember(run=organized.get("run", organized)["id"])
        self.translate(phase=False)
        saved = self.helper("results", "--run", self.remembered()["run"])
        results = json.loads((self.game / saved["path"]).read_text(encoding="utf-8"))
        translations = results.get("translations", results)
        # The injector: data through write_rpgmaker, plugin settings into
        # js/plugins.js, saved as a checkpoint with the runtime manifest.
        for row in listed:
            document, node, key = self.located(row["file"], row["pointer"])
            node[key] = translations[f"qa:{row['file']}#{row['pointer']}"]
            if row["file"].endswith("js/plugins.js"):
                file = self.game / row["file"]
                text = file.read_text(encoding="utf-8-sig")
                file.write_text(
                    text[: text.index("[")]
                    + json.dumps(document, ensure_ascii=False)
                    + text[text.rindex("]") + 1 :],
                    encoding="utf-8",
                )
                self.checkpoint("translation: write plugin text QA counted")
            else:
                staged = self.work / "staged" / row["file"]
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_text(json.dumps(document, ensure_ascii=False), "utf-8")
                self.operation(
                    "write_rpgmaker",
                    {
                        "source": row["file"],
                        "translated": staged.relative_to(self.game).as_posix(),
                        "output": row["file"],
                    },
                )
        # The assistant played the game before, so QA takes the new report.
        self.play()
        return {"translated": listed, "qa": self.helper("qa", "--prepare")}

    def located(self, file, pointer):
        """A game file's document, and the object and key holding the value
        at `pointer`: in js/plugins.js, `/<plugin>/<setting>` names a plugin
        by its name, as QA's list does."""
        path = self.game / file
        text = path.read_text(encoding="utf-8-sig")
        parts = [
            part.replace("~1", "/").replace("~0", "~")
            for part in pointer.split("/")[1:]
        ]
        if file.endswith("js/plugins.js"):
            document = json.loads(text[text.index("[") : text.rindex("]") + 1])
            node = next(
                plugin for plugin in document if plugin.get("name") == parts[0]
            )["parameters"]
            parts = parts[1:]
        else:
            document = node = json.loads(text)
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        return document, node, int(parts[-1]) if isinstance(node, list) else parts[-1]

    def qa_applied(self):
        """Reports the qa phase complete once Text QA's apply saved its work,
        as qa's next step then says; for MV/MZ, DazedTL keeps the phase open
        until the playtest after the apply settles."""
        qa = self.helper("qa", "--status")
        if not qa["applied"]:
            raise SystemExit(f"Text QA is not applied: {qa['next']}")
        self.finished(next_action="Play the game again after QA's apply.")

    def final_check(self):
        """Plays the game again after QA's apply and, once the playtest
        settles, reports its problems and coverage."""
        status = self.play()
        if not status["settled"]:
            raise SystemExit(f"The final check did not settle: {status['next']}")
        problems = sum(status["problems"].values())
        self.finished(
            next_action=f"Final check settled: {problems} playtest problem(s), "
            f"{status['reached']} stops reached, {status['gaps']} coverage gap(s).",
        )
        return status

    def package(self):
        """Reports QA done, which records its evidence, and packages the
        patch, as the starting prompt's last steps do."""
        self.finished("patch")
        print("Packaged:", self.operation("package")["result"]["path"])

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

    def units(self, miss=None):
        """The game data's units, without the one whose ID is `miss`."""
        if self.tyrano:
            return [
                {
                    "id": identity,
                    "group": path.stem,
                    "scene": path.stem,
                    "source": text,
                    "kind": "dialogue",
                    "speaker": speaker,
                }
                for identity, (path, _number, text, _tags, speaker) in (
                    self.scenario_lines().items()
                )
                if identity != miss
            ]
        rows = []
        markers = self.help_markers()
        for path in sorted((self.game / self.data).glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            for pointer, text in walk(document, markers=markers, source=self.source):
                if f"{path.stem}{pointer}" == miss:
                    continue
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

    def organize(self, complete=False, miss=None):
        """Organizes the game's units, leaving out the one whose ID is
        `miss`, as an extractor that misses a line players read."""
        self.report("extraction")
        source = self.work / "source-units.json"
        source.write_text(
            json.dumps({"version": 1, "units": self.units(miss)}, ensure_ascii=False),
            encoding="utf-8",
        )
        command = ["organize", "--input", f"{WORK}/source-units.json"]
        if not complete:
            organized = self.helper(*command)
        else:
            # The tool's own count of the game's text, which --complete checks.
            census = self.helper("census")
            self.helper("run", "--run", census["id"], "--wait", "10")
            report = self.work / "census-uncovered.json"
            report.unlink(missing_ok=True)
            try:
                organized = self.helper(*command, "--complete")
            except SystemExit:
                # The units leave out the title and plugin text, and any line
                # missed; add what organize names, which this extractor never
                # writes back.
                if not report.is_file():
                    raise
                uncovered = json.loads(report.read_text(encoding="utf-8"))["uncovered"]
                units = self.units(miss) + [
                    {
                        "id": f"{entry['file']}#{entry['location']}#{index}",
                        "group": "Other",
                        "scene": "Other",
                        "source": text,
                        "kind": "ui",
                        "speaker": None,
                    }
                    for entry in uncovered
                    for index, text in enumerate(entry["runs"])
                ]
                source.write_text(
                    json.dumps({"version": 1, "units": units}, ensure_ascii=False),
                    encoding="utf-8",
                )
                organized = self.helper(*command, "--complete")
        self.remember(run=organized.get("run", organized)["id"])

    def translate(self, requests=None, phase=True):
        """Answers the run's requests without a saved translation, reporting
        the translation phase first unless `phase` is false."""
        if phase:
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
            # Organizing again keeps the translations of unchanged requests.
            if request.get("accepted") or reply.get("result"):
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
        if self.tyrano:
            # Len's injector writes each line's text back before its tags.
            files: dict[Path, list[str]] = {}
            translations = results.get("translations", results)
            for identity, (
                path,
                number,
                _text,
                tags,
                _speaker,
            ) in self.scenario_lines().items():
                lines = files.setdefault(
                    path, path.read_text(encoding="utf-8").split("\n")
                )
                if identity in translations:
                    lines[number] = translations[identity] + tags
            for path, lines in files.items():
                path.write_text("\n".join(lines), encoding="utf-8")
            self.checkpoint()
            self.report("qa")
            return
        by_file: dict[str, dict[str, str]] = {}
        for identity, value in results.get("translations", results).items():
            # What organize --complete added from the census, such as the
            # title, this extractor never writes back.
            if "#" in identity:
                continue
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
    """Whether `text` is text of the game's source language: Japanese kana,
    kanji or punctuation, or for English Latin letters in anything but an
    identifier."""
    if language == "English":
        return bool(LATIN.search(text)) and not IDENTIFIER.fullmatch(text)
    return bool(JAPANESE.search(text) or MARKS.search(text))


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
    """Readable text in the target language that keeps the line count and
    each line's control codes in order, as DazedTL requires, unique to the
    line."""
    from util.runtime_text import split_protected_codes

    return "\n".join(
        (f"テスト行{mark}。" if target == "Japanese" else f"Tested line {mark}.")
        + "".join(" " + code for code in split_protected_codes(line)[1::2])
        for line, mark in (
            (line, hashlib.sha256(f"{identity}:{number}".encode()).hexdigest()[:6])
            for number, line in enumerate(source.split("\n"))
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
            "play",
            "untranslated",
            "check",
            "qa-applied",
            "final-check",
            "package",
        ],
    )
    parser.add_argument("--helper-json", required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--requests", type=int)
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--miss")
    args = parser.parse_args()
    assistant = Assistant(json.loads(args.helper_json), args.game)
    if args.step == "translate":
        print(json.dumps(assistant.translate(args.requests), ensure_ascii=False))
    elif args.step == "organize":
        assistant.organize(args.complete, args.miss)
    elif args.step in {"play", "untranslated", "check", "final-check"}:
        result = getattr(assistant, args.step.replace("-", "_"))()
        print(json.dumps(result, ensure_ascii=False))
    else:
        getattr(assistant, args.step.replace("-", "_"))()


if __name__ == "__main__":
    main()
