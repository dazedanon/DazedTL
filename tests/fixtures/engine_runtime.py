"""An offline startup and parser probe using only a generated miniature game."""

import json
import os
import re
import socket
import sys
import threading
from contextlib import redirect_stdout
from copy import deepcopy
from importlib import import_module
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend"))


def offline(*_args, **_kwargs):
    raise RuntimeError("Network access is disabled in the bundled engine probe.")


def no_external_engine(event, arguments):
    if event == "open" and isinstance(arguments[0], (str, bytes)):
        path = Path(os.fsdecode(arguments[0])).absolute()
        if any(
            path.is_relative_to(root.parent / name)
            for name in ("DazedMTLTool", "DazedMTLTool-engine")
        ):
            raise RuntimeError(
                "The bundled engine attempted to read a sibling checkout."
            )


socket.create_connection = socket.socket.connect = socket.socket.connect_ex = offline
sys.addaudithook(no_external_engine)

from dazedtl.api.server import Application
from dazedtl.compatibility.runtime import ENGINE_ROOT

game = temporary / "game"
game.mkdir()
original = json.dumps(
    [None, {"id": 1, "name": "薬", "description": "体力を回復する。", "note": ""}],
    ensure_ascii=False,
).encode()
(game / "Items.json").write_bytes(original)
app = Application(temporary / "profile", False)
try:
    assert app.state()["project"] is None
    assert app.backend.source == ENGINE_ROOT
    with app.backend.context():
        from desktop.backend.manual import (
            adoptable_requests,
            compatible,
            reusable_speaker_scan,
            seed_variables,
            signature,
            speaker_scan_inputs,
        )
        from util.paths import PROMPT_PATH, runtime_data_file
        from util.skills import load_project_setup, load_system_prompt

        # The app and its estimate workers start without the provider SDKs,
        # which took seconds of every worker's startup on Windows.
        for module in ("util.batch_providers", "util.translation"):
            import_module(module)
        assert not {"anthropic", "openai"} & set(sys.modules), "An SDK loaded."
        # A Batch preparation reuses its estimate's speaker scan only when it
        # read the same inputs; a changed file must be scanned again.
        scan_plan = {
            "mode": "batch",
            "files": [{"name": "Map001.json", "sha256": "a"}],
            "selected": ["Map001.json"],
        }
        scan_plan["scanned_speakers"] = {
            "inputs": speaker_scan_inputs(scan_plan),
            "collected": ["村長"],
        }
        assert reusable_speaker_scan(scan_plan) == ["村長"]
        scan_plan["files"] = [{"name": "Map001.json", "sha256": "b"}]
        assert reusable_speaker_scan(scan_plan) is None
        # It submits its estimate's requests only when it froze the same plan.
        adopt = temporary / "adopt"
        (adopt / "seed").mkdir(parents=True)
        estimate_plan = {
            "mode": "estimate",
            "settings": {"model": "m"},
            "context_hashes": {},
        }
        (adopt / "seed/estimate_plan.json").write_text(json.dumps(estimate_plan))
        batch_plan = {
            "mode": "batch",
            "settings": {"model": "m"},
            "context_hashes": {
                "seed/estimate_plan.json": "x",
                "seed/batch_requests.json": "y",
            },
            "adopt_requests": {
                "plan": "seed/estimate_plan.json",
                "queue": "seed/batch_requests.json",
                "ignore": ["mode"],
            },
        }
        assert (
            adoptable_requests(adopt, batch_plan) == adopt / "seed/batch_requests.json"
        )
        batch_plan["settings"] = {"model": "other"}
        assert adoptable_requests(adopt, batch_plan) is None
        # A phase's translated variables are frozen beside those requests; the
        # shared folder made every such Batch preparation fail.
        workflow = temporary / "workflow"
        (workflow / "log").mkdir(parents=True)
        (workflow / "log/var_translation_map.json").write_text(
            '{"薬": "Potion"}', encoding="utf-8"
        )
        seed_variables(adopt, batch_plan, workflow)
        assert "seed/var_translation_map.json" in batch_plan["context_hashes"]
        assert (adopt / "seed/estimate_plan.json").is_file()

        # Per-file workers save the variable map at once: a save waits for
        # another worker's, here the lock this thread holds, and keeps what it
        # wrote meanwhile instead of overwriting it.
        from util import translation as variables

        var_map = workflow / "log/var_translation_map.json"
        with patch.multiple(
            variables,
            VAR_MAP_FILE=var_map,
            VAR_MAP_LOCK_FILE=workflow / "log/var_translation_map.lock",
        ):
            with variables._file_lock(variables.VAR_MAP_LOCK_FILE):
                saver = threading.Thread(
                    target=variables.set_var_translation, args=("剣", "Sword")
                )
                saver.start()
                saver.join(0.2)
                var_map.write_text('{"薬": "Potion"}', encoding="utf-8")
            saver.join()
        assert json.loads(var_map.read_text(encoding="utf-8")) == {
            "薬": "Potion",
            "剣": "Sword",
        }

        # OpenAI Batch quotes count cache reads from prefix fingerprints taken
        # every 128 tokens past 1,024; hashing many tokens at once must find
        # exactly the hits that hashing them one by one did.
        import hashlib

        from util import translation as estimates

        def reference(sequences):
            seen, total = set(), 0
            for tokens in sequences:
                hasher, prints, hit = hashlib.blake2b(digest_size=16), [], 0
                for index, token in enumerate(tokens, 1):
                    hasher.update(token.to_bytes(4, "little"))
                    if index >= 1024 and index % 128 == 0:
                        prints.append((index, hasher.digest()))
                        hit = index if prints[-1] in seen else hit
                total += hit
                seen.update(prints)
            return total

        common = list(range(70_000, 71_300))
        sequences = [common + [5] * extra for extra in (0, 1, 127, 128, 700)] + [
            common[:1023],
            common[:1024],
            common[:1151],
            common[:1152],
            common[:1280],
            # Differs only in the last token before the 1,152 fingerprint.
            common[:1151] + [9] + common[1152:],
            [9] * 2000,
        ]
        assert estimates._estimate_openai_cache_reads(sequences) == reference(sequences)

        # Workers build the prompt for every file: an unchanged game reuses
        # it, and a changed skill file is read again.
        from util.skills import system as prompts

        guidance = temporary / "prompt-game"
        (guidance / ".dazedtl/skills").mkdir(parents=True)
        quirks = guidance / ".dazedtl/skills/quirks.md"
        quirks.write_text("Keep honorifics.", encoding="utf-8")
        # The bundled prompt is read too, and a fresh checkout leaves it too
        # recent to reuse; a copy settles with the game's files.
        bundled = temporary / "system.md"
        bundled.write_bytes(runtime_data_file(PROMPT_PATH).read_bytes())
        built = []
        with patch.object(prompts, "runtime_data_file", lambda _: bundled):
            # The first build adds the game's files; only settled ones are reused.
            load_system_prompt(guidance)
            for path in [*guidance.rglob("*"), guidance, bundled]:
                os.utime(path, ns=(10**18, 10**18))
            with patch.object(
                prompts, "prepare_game_translation_context", built.append
            ):
                first = load_system_prompt(guidance)
                assert "Keep honorifics." in first
                assert load_system_prompt(guidance) == first and len(built) == 1, built
                quirks.write_text("Drop honorifics.", encoding="utf-8")
                os.utime(quirks, ns=(10**18 + 10**10, 10**18 + 10**10))
                assert "Drop honorifics." in load_system_prompt(guidance)
                assert len(built) == 2, built

        # Git tracks a skill whatever case its extension is in, so the prompt
        # lists it on every platform.
        from util.skills import list_custom_skill_paths

        (guidance / ".dazedtl/skills/Style.MD").write_text(
            "Be terse.", encoding="utf-8"
        )
        assert [p.name for p in list_custom_skill_paths(guidance)] == ["Style.MD"]

        # A real saved run recorded this pre-version byte hash; it must still pass
        # the native resume guard, alongside plans that record the version.
        engine = "RPG Maker MV/MZ"
        legacy = "b0aa0546c511a7b996fad0dad1d62619258d5eb7ec1f23e9e0ebf113bd9284aa"
        assert compatible(engine, legacy) and compatible(engine, signature(engine))
        assert not compatible("CSV", legacy) and not compatible(engine, "changed")
        # Engine preparation writes LF bytes, including for a file whose only
        # difference is CRLF (hidden by read_text()).
        from util.dazedformat import format_json_files
        from util.project_preparation import format_plugins_js

        prepared = temporary / "formatting"
        prepared.mkdir()
        document = {"name": "薬", "text": "one\r\ntwo\nthree", "control": r"\C[2]"}
        expected_json = json.dumps(document, ensure_ascii=False, indent=4).encode()
        expected_plugins = 'var $plugins = [{\n  "name": "薬",\n  "status": true\n}];\n'
        items, plugins = prepared / "Items.JSON", prepared / "plugins.js"
        minified = (
            b"\xef\xbb\xbf" + json.dumps(document, ensure_ascii=False).encode(),
            b'\xef\xbb\xbfvar $plugins=[{"name":"\xe8\x96\xac","status":true}];',
        )
        for json_input, plugins_input in (
            *(
                (
                    expected_json.replace(b"\n", newline),
                    expected_plugins.encode().replace(b"\n", newline),
                )
                for newline in (b"\r\n", b"\r")
            ),
            minified,
        ):
            items.write_bytes(json_input)
            plugins.write_bytes(plugins_input)
            assert format_json_files(prepared) == (1, [])
            assert format_plugins_js(plugins) == len(expected_plugins)
            assert items.read_bytes() == expected_json
            assert plugins.read_bytes() == expected_plugins.encode()
        with patch.object(
            Path, "write_bytes", side_effect=AssertionError("rewrote LF")
        ):
            assert format_json_files(prepared) == (1, [])
            format_plugins_js(plugins)
        (prepared / "broken.json").write_bytes(b"{invalid\r\n")
        count, errors = format_json_files(prepared)
        assert (count, len(errors)) == (1, 1)
        assert (prepared / "broken.json").read_bytes() == b"{invalid\r\n"
        # The bundled README becomes every published repository's player page;
        # only WOLF games, which get UberWolf, get its section, and only once.
        from util.project_preparation import install_gameupdate

        template = ENGINE_ROOT / "gameupdate"
        player_readme = (template / "README.md").read_text("utf-8")
        wolf_section = (template / "README.wolf.md").read_text("utf-8")
        for wolf in (False, True):
            installed = temporary / f"gameupdate-wolf-{wolf}"
            for _ in range(2):
                assert install_gameupdate(installed, wolf=wolf)[1] == []
            expected = (
                player_readme.rstrip("\n") + "\n\n" + wolf_section
                if wolf
                else player_readme
            )
            assert (installed / "README.md").read_text("utf-8") == expected
            assert (installed / "UberWolfCli.exe").is_file() == wolf
            assert not (installed / "README.wolf.md").exists()
        # Applying one image must add only that image to an allowlisted patch
        # repository; re-including its folder once exposed every game image.
        import subprocess

        from util.rpgmaker_images import add_patch_exceptions

        repo = temporary / "image-patch"
        for image in ("img/pictures/menu/save.png", "img/pictures/menu/load.png"):
            (repo / image).parent.mkdir(parents=True, exist_ok=True)
            (repo / image).write_bytes(b"png")
        (repo / "img/faces/arina.png").parent.mkdir(parents=True)
        (repo / "img/faces/arina.png").write_bytes(b"png")
        (repo / ".gitignore").write_text(
            "/*\n!/.gitignore\n\n# DazedTL selected image patches\n"
            "!/img/\n!/img/faces/\n!/img/faces/arina.png\n"
        )
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        add_patch_exceptions(repo, [repo / "img/pictures/menu/save.png"])
        listed = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "-uall"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        ).stdout.split()
        assert sorted(listed[1::2]) == [
            ".gitignore",
            "img/faces/arina.png",
            "img/pictures/menu/save.png",
        ], listed
        # A checkpoint then places its patch block, with the only `/*`, after
        # the image section; the next image must keep that block whole.
        (repo / "Game.exe").write_bytes(b"exe")
        allowed = "!/img/\n/img/*\n!/img/faces/\n/img/faces/*\n!/img/faces/arina.png\n"
        allowed += "!/img/pictures/\n/img/pictures/*\n!/img/pictures/menu/\n"
        allowed += "/img/pictures/menu/*\n!/img/pictures/menu/save.png\n"
        (repo / ".gitignore").write_text(
            "# DazedTL selected image patches\n" + allowed + "\n"
            "# BEGIN DazedTL Len patch files\n/*\n!/.gitignore\n"
            + allowed
            + "# END DazedTL Len patch files\n"
        )
        add_patch_exceptions(repo, [repo / "img/pictures/menu/load.png"])
        listed = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "-uall"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        ).stdout.split()
        assert sorted(listed[1::2]) == [
            ".gitignore",
            "img/faces/arina.png",
            "img/pictures/menu/load.png",
            "img/pictures/menu/save.png",
        ], listed
        assert runtime_data_file(PROMPT_PATH).is_relative_to(
            root / "backend/dazedtl/engine/data"
        )
        assert load_system_prompt()
        # One investigation pass unless the user chose three; a prompt with
        # both, or three by default, triples the assistant's usage.
        standard, thorough = (
            load_project_setup("rpgmaker", thorough=choice) for choice in (False, True)
        )
        assert "One-pass discovery" in standard and "Launch exactly" not in standard
        assert "Launch exactly three" in thorough and "One-pass" not in thorough
        manual = app.backend.manual
        listing = manual.inspect(str(game), "RPG Maker MV/MZ")
        job = manual.start(
            str(game), "RPG Maker MV/MZ", ["Items.json"], listing["revision"]
        )
    controller = manual.controller(job["id"])
    # Half the suite's budget (scripts/test.mjs) for the worker to exit.
    controller.worker.join(float(os.environ.get("DAZEDTL_TEST_BUDGET") or 10) / 2)
    result = manual.jobs[job["id"]]
    assert result["status"] == "complete", (
        result["status"],
        result.get("message"),
        result.get("log"),
    )
    assert result["estimate"]["input_tokens"] > 0
    # The renderer inspects this finished estimate; its view must match the Job
    # contract the renderer's types are generated from.
    from dazedtl.api import views
    from dazedtl.api.contracts.validation import check_response

    check_response("guided_inspect", views.job(app.guided.run_view(job["id"])))
    assert (game / "Items.json").read_bytes() == original
    # The run freezes the base rules rendered for its languages.
    from util.prompt_pair import render_for_run

    frozen = manual.folder(job["id"]) / "context/system.md"
    assert frozen.read_bytes() == render_for_run(
        (root / "backend/dazedtl/engine/data/skills/system.md").read_bytes(),
        json.loads((manual.folder(job["id"]) / "plan.json").read_text())["settings"],
    )
    # Already-translated 101 names used to disappear from requests. Bracketed
    # tutorial prose also took the short-name prompt and became a bogus label.
    # Exercise the real two-pass parser in this existing offline process.
    with app.backend.context():
        run_settings = json.loads((manual.folder(job["id"]) / "plan.json").read_text())[
            "settings"
        ]
        os.environ.update(
            {
                key: str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in run_settings.items()
            }
        )
        from dazedtl.compatibility.worker_policy import configure_states
        from dazedtl.settings.preferences import (
            BATTLE_MESSAGE_USERS,
            CHOICE_COLLECTION,
            CODE_NAMEPLATES,
            PAGE_PACKING,
            SAME_LINE_SPEAKERS,
            SOURCE_TEXT,
            SPEAKER_CONTEXT,
        )
        from modules import rpgmakermvmz as parser
        from util import extensions

        # A nameplate translated with its own parentheses was saved, then read
        # back as another source, so the run dropped every paid name.
        saved_names = parser._merge_speaker_rows_into_game_characters(
            "", [("農夫の魂（夫）", "Farmer's Soul (Husband)")]
        )
        with patch.object(parser, "VOCAB", saved_names):
            assert (
                parser._vocab_speaker_lookup("農夫の魂（夫）")
                == "Farmer's Soul (Husband)"
            ), saved_names
        # Speakers joined only a section headed exactly "Game Characters", so
        # a decorated one got a second section above it, and a section an
        # older import appended stayed apart.
        saved_names = parser._merge_speaker_rows_into_game_characters(
            "# Game Characters · キャラクター\nニーナ / ネーナ (Nina)\n\n"
            "# Speakers\nミカ (Mika)\n\n# Items\n薬 (Potion)\n\n"
            "# game characters\nサンク (Sank) - Male\n",
            [("リナ", "Rina"), ("ネーナ", "Nena")],
        )
        assert saved_names == (
            "# Game Characters · キャラクター\nニーナ / ネーナ (Nina)\n"
            "サンク (Sank) - Male\nミカ (Mika)\n"
            "リナ (Rina) - Unverified nameplate, translated without its story.\n\n"
            "# Items\n薬 (Potion)\n\n"
        ), saved_names
        # A Japanese to Simplified Chinese run judged a speaker's hanzi name
        # Japanese left, so every dialogue line kept the kana nameplate.
        with patch.object(parser, "LANGUAGE", "Simplified chinese"):
            assert parser._speaker_translation_valid("宿屋の主人", "旅店老板")
            assert not parser._speaker_translation_valid("ミカ", "ミカ")
        # WOLF reads speaker names by the same rule, and keeps a name mixing
        # Latin letters with kana, such as EN_セルリア, that MV/MZ reads left.
        from modules import wolfdawn

        with patch.object(wolfdawn, "LANGUAGE", "Simplified chinese"):
            assert wolfdawn._speaker_translation_valid("宿屋の主人", "旅店老板")
            assert not wolfdawn._speaker_translation_valid("ミカ", "ミカ")
        with patch.object(wolfdawn, "LANGUAGE", "English"):
            assert wolfdawn._speaker_translation_valid("セルリア", "EN_セルリア")
            assert not wolfdawn._speaker_translation_valid("セルリア", "セルリア")
            assert not wolfdawn._speaker_translation_valid("セルリア", "")
            # A colour code's letter read as Latin, so an echoed name kept
            # its Japanese nameplate.
            assert not wolfdawn._speaker_translation_valid("セルリア", "\\c[2]セルリア")
            assert wolfdawn._speaker_translation_valid("セルリア", "\\c[2]EN_セルリア")
        with patch.object(parser, "LANGUAGE", "English"):
            assert not parser._speaker_translation_valid("セルリア", "EN_セルリア")
            assert parser._speaker_translation_valid("セルリア", "Cerulia")
        # Setup read saved guesses such as a cameo's 存子 "Sonko" as approved
        # spellings; they now say they were translated without their story.
        assert "Unverified nameplate" in saved_names, saved_names
        # A WOLF map saved its progress after each page with that page's
        # tokens, read in a `finally`: a failing first page had none yet, so
        # an UnboundLocalError hid its error, a run's stop included, and a
        # failing later page saved progress with the page before's tokens.
        # handleWOLF then wrote the map with the lines the failing page had
        # set and reported it complete; it now fails the file, as the run's
        # other file errors do.
        from modules import wolf
        from util import translation as stops

        wolf_fails = {}

        def wolf_page(page_list, *_args):
            text = page_list[0]["stringArgs"]
            source, text[0] = text[0], "EN:" + text[0]
            if wolf_fails.get(source):
                raise wolf_fails[source]
            return [3, 1]

        def wolf_map(*fails):
            wolf_fails.update(zip(("一頁", "二頁"), fails))
            pages = [
                {"list": [{"code": 101, "stringArgs": [text]}]}
                for text in ("一頁", "二頁")
            ]
            return {"events": [None, {"pages": pages}]}

        def wolf_file(name, document, error=None):
            (wolf_root / "files" / name).write_text(json.dumps(document), "utf-8")
            try:
                wolf.handleWOLF(name, False)
            except ValueError as raised:
                assert raised is error, raised
            else:
                assert error is None, f"A WOLF file whose page failed passed: {name}"

        wolf_root = temporary / "wolf-pages"
        (wolf_root / "files").mkdir(parents=True)
        saved = wolf_root / "translated/Map001.json"
        directory = os.getcwd()
        os.chdir(wolf_root)
        try:
            with (
                patch.object(wolf, "searchCodes", wolf_page),
                patch.object(wolf, "searchDB", wolf_page),
                patch.object(stops, "RUN_STOPS", True),
            ):
                stop = stops.RunStoppingError("Stopped.")
                try:
                    wolf.parseMap(wolf_map(stop, None), "Map001.json")
                except stops.RunStoppingError as error:
                    assert error is stop, error
                else:
                    raise AssertionError("A WOLF map went on after a run's stop.")
                failure = ValueError("Refused.")
                result = wolf.parseMap(wolf_map(failure, None), "Map001.json")
                assert result[1:] == [[0, 0], failure], result
                # Each finished page was saved over translated/, so a file
                # failing again replaced an earlier run's complete output
                # with a partial one; a WOLF file is now written once, whole.
                saved.parent.mkdir()
                saved.write_text("complete", "utf-8")
                wolf_file("Map001.json", wolf_map(None, failure), failure)
                assert saved.read_text("utf-8") == "complete"
                # A CommonEvent or DataBase file is one page.
                wolf_fails["一頁"] = failure
                wolf_file(
                    "CommonEvent.json",
                    {"commands": [{"stringArgs": ["一頁"]}]},
                    failure,
                )
                wolf_file(
                    "DataBase.json", {"types": [{"stringArgs": ["一頁"]}]}, failure
                )
                assert sorted(os.listdir("translated")) == ["Map001.json"]
                # A file's kind was searched for in its whole text, so a
                # CommonEvent line holding "'events':" was parsed as a map.
                wolf_fails.clear()
                wolf_file(
                    "CommonEvent.json", {"commands": [{"stringArgs": ["'events':"]}]}
                )
                assert json.loads(
                    Path("translated/CommonEvent.json").read_text("utf-8")
                ) == {"commands": [{"stringArgs": ["EN:'events':"]}]}
        finally:
            os.chdir(directory)
        # A WOLF page's set-data pass translated its choices, choice window
        # and speakers again, so each was paid for twice and a translation
        # was translated again ("EN EN はい"); its tokens were dropped, and a
        # 210 speaker's input tokens counted as output.
        wolf_sent = []
        wolf_contexts = []

        def wolf_answer(text, history, *_args):
            wolf_sent.append(text)
            wolf_contexts.append(history)
            if isinstance(text, list):
                return [[f"EN {line}" for line in text], [3, 1]]
            return ["Rin" if "NPC name" in str(history) else f"EN {text}", [3, 1]]

        wolf_choices = {"code": 102, "stringArgs": ["はい", "", "いいえ"]}
        wolf_window = {"code": 300, "stringArgs": ["選択肢/確認", "行く,残る", "宿屋"]}
        with patch.multiple(
            wolf,
            CODE101=True,
            CODE102=True,
            CODE210=True,
            CODE300=True,
            NAMESLIST=[],
            translateAI=wolf_answer,
        ):
            tokens = wolf.searchCodes(
                [
                    {"code": 101, "stringArgs": ["@1\n村人：\nこんにちは"]},
                    wolf_choices,
                    {"code": 210, "intArgs": [None], "stringArgs": ["", "勇者"]},
                    wolf_window,
                    {"code": 300, "stringArgs": ["援護文章", "@1\n店主：\nさようなら"]},
                ],
                SimpleNamespace(refresh=lambda: None),
                [],
                "Map001.json",
            )
        assert wolf_sent == [
            "村人",
            ["はい", "いいえ"],
            "勇者",
            "宿屋",
            ["行く", "残る"],
            "店主",
            ["[Rin]: こんにちは"],
            ["[Rin]: さようなら"],
        ], wolf_sent
        assert tokens == [3 * len(wolf_sent), len(wolf_sent)], tokens
        assert wolf_choices["stringArgs"] == ["EN はい", "", "EN いいえ"], wolf_choices
        assert wolf_window["stringArgs"][1:] == ["EN 行く,EN 残る", "EN 宿屋"], (
            wolf_window
        )
        # The window's question asked for the "{LANGUAGE}" translation.
        assert "{LANGUAGE}" not in str(wolf_contexts), wolf_contexts
        # The set-data pass ran once any one list of the page came back
        # whole, then wrote a list that came back short (an IndexError failed
        # the page) or long (its extra line was sent again and written over a
        # later command). A list, choices or window reply of the wrong length
        # is now left in its source text, a window's question with it, and
        # the file joins MISMATCH; a 選択肢/確認 without a question failed on
        # its missing argument.

        def wolf_odd(text, *_args):
            if isinstance(text, str):
                return [f"EN {text}", [3, 1]]
            reply = [f"EN {line}" for line in text]
            if "攻撃" in text:
                reply.append("EN extra")
            elif "薬草" not in text:
                reply.pop()
            return [reply, [3, 1]]

        def wolf_misfit(*commands):
            page = deepcopy(list(commands))
            printed = StringIO()
            with (
                patch.multiple(
                    wolf,
                    CODE101=True,
                    CODE102=True,
                    CODE122=True,
                    CODE300=True,
                    MISMATCH=[],
                    translateAI=wolf_odd,
                ),
                redirect_stdout(printed),
            ):
                wolf.searchCodes(
                    page, SimpleNamespace(refresh=lambda: None), [], "M.json"
                )
                # The run counts a file's mismatches from these markers; one
                # a module found itself only named the file in its TOTAL.
                marked = printed.getvalue().count("MISMATCH_EVENT:M.json\n")
                return page, wolf.MISMATCH, marked

        choices = {"code": 102, "stringArgs": ["はい", "いいえ"]}
        window = {"code": 300, "stringArgs": ["選択肢/確認", "行く,残る"]}
        asking = {
            "code": 300,
            "stringArgs": ["[共]汎用ウィンドウ生成", "行く,残る", "宿屋"],
        }
        dialogue = {"code": 101, "stringArgs": ["こんにちは"]}
        script = {"code": 122, "stringArgs": ["薬草"]}
        battle = {"code": 300, "stringArgs": ["BTLメッセージ", "攻撃"]}
        for commands, written, marked in (
            ([choices], [choices], 1),
            ([window], [window], 1),
            ([asking], [asking], 1),
            (
                [dialogue, script, battle],
                [dialogue, {**script, "stringArgs": ["EN 薬草"]}, battle],
                2,
            ),
        ):
            assert wolf_misfit(*commands) == (written, ["M.json"], marked), commands
        # A chunk translateAI kept in its source text after failed validation
        # came back the right length, so its lines were written back with
        # their line breaks turned into spaces ("勇者の 記録"); a page's list
        # and a DataBase category whose reply translateAI kept are now left
        # as they were, and counted once, by translateAI.
        keeping = [False]

        def wolf_keeps(text, *_args):
            keeping[0] = isinstance(text, list) and any(
                "勇者の" in line for line in text
            )
            if keeping[0]:
                return [list(text), [3, 1]]
            if isinstance(text, list):
                return [[f"EN {line}" for line in text], [3, 1]]
            return [f"EN {text}", [3, 1]]

        def wolf_db(*types):
            document = deepcopy(list(types))
            sent = []
            printed = StringIO()

            def answer(text, *_args):
                sent.append(text)
                reply = wolf_keeps(text)
                if not keeping[0] and any("看板" in line for line in text):
                    reply[0].pop()
                return reply

            with (
                patch.multiple(
                    wolf,
                    ITEMFLAG=True,
                    ARMORFLAG=True,
                    WEAPONFLAG=True,
                    STATEFLAG=True,
                    MISMATCH=[],
                    translateAI=answer,
                    last_translation_had_mismatch=lambda: keeping[0],
                ),
                redirect_stdout(printed),
            ):
                wolf.searchDB(
                    document, SimpleNamespace(refresh=lambda: None), [], "D.json"
                )
                marked = printed.getvalue().count("MISMATCH_EVENT:D.json\n")
                return document, wolf.MISMATCH, marked, sent

        battle = {"code": 300, "stringArgs": ["BTLメッセージ", "勇者の\n記録"]}
        with patch.multiple(
            wolf,
            CODE300=True,
            translateAI=wolf_keeps,
            last_translation_had_mismatch=lambda: keeping[0],
        ):
            page = [deepcopy(battle)]
            wolf.searchCodes(page, SimpleNamespace(refresh=lambda: None), [], "M.json")
            assert page == [battle], page

        def category(name, *fields):
            return {
                "name": name,
                "data": [{"data": [{"name": k, "value": v} for k, v in fields]}],
            }

        # A DataBase category whose reply had the wrong length reached the
        # set-data pass as empty lists once another category fit, and the
        # file failed with an IndexError; the status effects were sent once
        # for each of their lists that held text.
        directory = os.getcwd()
        os.chdir(temporary)
        (temporary / "log").mkdir(exist_ok=True)
        try:
            items = category("道具", ("名前", "薬草"), ("説明", "話\n記録"))
            armor = category("防具", ("名前", "看板"), ("説明", "宿屋"))
            weapon = category("武器", ("名前", "剣"), ("説明", "勇者の\n記録"))
            states = category("ステート", ("名前", "毒"), ("表示名", "毒状態"))
            written, mismatched, marked, sent = wolf_db(states, items, armor, weapon)
        finally:
            os.chdir(directory)
        assert written[2:] == [armor, weapon], written
        assert written[1]["data"][0]["data"][0]["value"] == "EN 薬草", written
        assert (mismatched, marked) == (["D.json"], 1), (mismatched, marked)
        # Nothing more of a category is sent, and paid for, once it cannot be written.
        assert ["宿屋"] not in sent, sent
        assert sum(any("毒" in line for line in lines) for lines in sent) == 2, sent
        # Each engine module ended a file whose parser returned an error its
        # own way: most printed a ✗ receipt and returned a TOTAL, so the run
        # read the file translated with part of it written, and its worker
        # logged a second receipt for what the file paid. Every module now
        # raises the error before reporting the file, as RPG Maker and WOLF
        # did, and the worker's receipt is the file's one.
        from util.translation_task import TRANSLATION_MODULE_SPECS

        refused = ValueError("Refused.")
        stubs = {
            name: lambda *_args: [{}, [3, 1], refused]
            for name in ("openFiles", "openFilesEstimate", "parseYuris")
        }
        stubs["yuris_whole_file_pass_through_reason"] = lambda _data: None
        stubs["refreshRuntimeConfig"] = lambda: None
        ends = temporary / "file-ends"
        for folder in ("files", "translated"):
            (ends / folder).mkdir(parents=True)
        (ends / "files/Doc.json").write_text("{}", "utf-8")
        # Lune, Ren'Py, Unity and CSV opened translated/<file> before their
        # parse, so a file that failed emptied an earlier complete output.
        complete = ends / "translated/Doc.json"
        complete.write_text("complete", "utf-8")
        directory = os.getcwd()
        os.chdir(ends)
        try:
            for *_kind, module_name, handler in TRANSLATION_MODULE_SPECS:
                module = import_module(module_name)
                its: dict[str, Any] = {
                    key: stub for key, stub in stubs.items() if hasattr(module, key)
                }
                for estimate in (False, True):
                    printed = StringIO()
                    with patch.multiple(module, **its), redirect_stdout(printed):
                        try:
                            getattr(module, handler)("Doc.json", estimate)
                        except ValueError as error:
                            assert error is refused, (module_name, error)
                        else:
                            raise AssertionError(f"{module_name} passed a failure.")
                    assert "[Input:" not in printed.getvalue(), module_name
                    assert complete.read_text("utf-8") == "complete", module_name
            # A file whose output can't be written fails with the error: RPG
            # Maker's returned a bare "Fail" and the plugin module's passed.
            # WOLF writes its own file (system.write_bytes) and fails with it.
            from util.translation_task import OutputNotSaved

            finished = {
                name: lambda *_args: [["text\n"], [3, 1], None]
                for name in ("openFiles", "parseYuris")
            }
            complete.unlink()
            Path("translated").rmdir()
            Path("translated").write_text("not a folder", "utf-8")
            for *_kind, module_name, handler in TRANSLATION_MODULE_SPECS:
                module = import_module(module_name)
                if module_name == "modules.wolf":
                    continue
                its = {
                    key: stub
                    for key, stub in {**stubs, **finished}.items()
                    if hasattr(module, key)
                }
                with patch.multiple(module, **its), redirect_stdout(StringIO()):
                    try:
                        getattr(module, handler)("Doc.json", False)
                    except OutputNotSaved as error:
                        assert str(error).startswith("Doc.json could not be saved: ")
                    else:
                        raise AssertionError(f"{module_name} passed an unsaved file.")
        finally:
            os.chdir(directory)
        # Every module but RPG Maker saved its progress over translated/ as
        # it went, which nothing read back (Resume translates a stopped file
        # again from the translation cache), so a file translated again that
        # failed replaced an earlier complete output with a partial one; CSV
        # also wrote it as finished. A module writes its file once now.
        progress = temporary / "progress-saves"
        for folder in ("files", "translated"):
            (progress / folder).mkdir(parents=True)
        os.chdir(progress)
        try:
            for module_name, handler, scene, source, options in (
                (
                    "modules.lune",
                    "handleLune",
                    "Scene.json",
                    '[{"name": "アリス", "message": "やあ"}]',
                    {},
                ),
                (
                    "modules.kirikiri",
                    "handleKirikiri",
                    "Scene.ks",
                    "【アリス】[CR]\n[text]やあ[KeyWait]\n",
                    {},
                ),
                (
                    "modules.csv",
                    "handleCSV",
                    "Scene.csv",
                    "Source,Target,Speaker\nやあ,,アリス\n",
                    {"SPEAKER_COLUMN": 2},
                ),
            ):
                module = import_module(module_name)
                (progress / "files" / scene).write_bytes(
                    source.encode("cp932" if scene.endswith(".ks") else "utf-8")
                )
                (progress / "translated" / scene).write_text("complete", "utf-8")
                sent = []

                def speaker_only(text, *_args, **_kwargs):
                    sent.append(text)
                    if len(sent) > 1:
                        raise refused
                    return ["Alice", [1, 1]]

                its = {"translateAI": speaker_only, "NAMESLIST": [], **options}
                with patch.multiple(module, **its), redirect_stdout(StringIO()):
                    try:
                        getattr(module, handler)(scene, False)
                    except ValueError as error:
                        assert error is refused, (module_name, error)
                    else:
                        raise AssertionError(f"{module_name} passed a failure.")
                assert sent[0] == "アリス" and len(sent) == 2, (module_name, sent)
                saved = (progress / "translated" / scene).read_bytes()
                assert saved == b"complete", (module_name, saved)
            # A line the game's Shift-JIS can't hold still fails the file at
            # once, before the file's later requests are paid for, as those
            # saves made it.
            from util.game_encoding import UnwritableText

            kirikiri = import_module("modules.kirikiri")
            unwritable = []

            def eng(text, *_args, **_kwargs):
                unwritable.append(text)
                return ["Ŋina", [1, 1]]

            with (
                patch.multiple(kirikiri, translateAI=eng, NAMESLIST=[]),
                redirect_stdout(StringIO()),
            ):
                try:
                    kirikiri.handleKirikiri("Scene.ks", False)
                except UnwritableText as error:
                    assert "line 1 holds Ŋ" in str(error), error
                else:
                    raise AssertionError("A Kirikiri file kept a line it can't write.")
            assert unwritable == ["アリス"], unwritable
        finally:
            os.chdir(directory)
        # NScripter wrote each csel choice with the dialogue line translated
        # before it, and failed a csel before any dialogue. The plugin module
        # took a QuestName's line break from the txtSubject before it, so it
        # failed a QuestName with no txtSubject, or one without a line break,
        # before it. CSV read its target column as the speaker by default, and
        # as the name it wrote there made the row look translated, wrote each
        # row's translation to the next row.
        shapes = temporary / "engine-shapes"
        for folder in ("files", "translated", "log"):
            (shapes / folder).mkdir(parents=True)
        os.chdir(shapes)
        try:
            for module_name, handler, scene, source, options, requests, output in (
                (
                    "modules.nscript",
                    "handleOnscripter",
                    "0.txt",
                    '*start\ncsel "はい",*yes,"いいえ",*no\n「やあ」\n',
                    {},
                    [["「やあ」"], ["はい", "いいえ"]],
                    (
                        "*start\ncsel \"EN 'はい'\",*yes,\"EN 'いいえ'\",*no\n"
                        "　EN '「やあ」'\\\n"
                    ),
                ),
                (
                    "modules.rpgmakerplugin",
                    "handlePlugin",
                    "plugins.js",
                    (
                        r"var q = [\"{\\\"QuestName\\\":\\\"最初の\\\\n依頼\\\"}\"];"
                        '\nvar txtSubject = "クエスト";\n'
                    ),
                    {},
                    [["最初の 依頼"], ["クエスト"]],
                    (
                        r"var q = [\"{\\\"QuestName\\\":\\\"EN \'最初の 依頼\'\\\"}\"];"
                        '\nvar txtSubject = "EN ՚クエスト՚";\n'
                    ),
                ),
                (
                    "modules.csv",
                    "handleCSV",
                    "Scene.csv",
                    "Source,Target\nやあ,アリス\nまたね,\n",
                    {},
                    [["やあ", "またね"]],
                    'Source,Target\r\nやあ,"EN ""やあ"""\r\nまたね,"EN ""またね"""\r\n',
                ),
                (
                    "modules.csv",
                    "handleCSV",
                    "Scene.csv",
                    "Source,Target\nやあ,アリス\nまたね,\n",
                    {"SPEAKER_COLUMN": 1},
                    ["アリス", ["[Alice]: やあ", "またね"]],
                    (
                        'Source,Target\r\nやあ,"EN ""[Alice]: やあ"""\r\n'
                        'またね,"EN ""またね"""\r\n'
                    ),
                ),
            ):
                module = import_module(module_name)
                encoding = "cp932" if scene == "0.txt" else "utf-8"
                (shapes / "files" / scene).write_bytes(source.encode(encoding))
                sent = []

                def shape_reply(text, *_args, **_kwargs):
                    if text:
                        sent.append(text)
                    if isinstance(text, list):
                        return [[f'EN "{line}"' for line in text], [1, 1]]
                    return ["Alice", [1, 1]]

                its = {"translateAI": shape_reply, "NAMESLIST": [], **options}
                with patch.multiple(module, **its), redirect_stdout(StringIO()):
                    getattr(module, handler)(scene, False)
                # Only the requests this case is about: CSV's second pass asks
                # for a speaker column's name again, which is not.
                assert sent[: len(requests)] == requests, (module_name, sent)
                written = (shapes / "translated" / scene).read_bytes()
                assert written.decode(encoding) == output, (module_name, written)
        finally:
            os.chdir(directory)
        # A name a registered reference game already translated is reused
        # instead of guessed: that game read 存子 as Aruko.
        from util import reference_games

        game, earlier = temporary / "names-game", temporary / "names-earlier"
        game.mkdir()
        for side, nameplate in (("ja", "存子"), ("en", "Aruko")):
            (earlier / side).mkdir(parents=True)
            (earlier / side / "Map001.json").write_text(
                json.dumps(
                    {
                        "events": [
                            None,
                            {
                                "id": 1,
                                "pages": [
                                    {
                                        "list": [
                                            {
                                                "code": 101,
                                                "parameters": ["", 0, 0, 2, nameplate],
                                            },
                                            {"code": 401, "parameters": ["……"]},
                                        ]
                                    }
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
        reference_games.add_paired_reference(
            game, "Earlier game", earlier / "ja", earlier / "en"
        )
        named = parser._reference_speaker_names(
            game / ".dazedtl/glossary.txt", ["存子", "初対面"]
        )
        assert named == {"存子": ("Aruko", "Earlier game")}, named

        # A symlinked skill file would be followed into whatever it points at
        # and shipped with the translation as if it were the game's own.
        from util.paths import portable_game_files

        linked = temporary / "linked-game"
        skills = linked / ".dazedtl/skills"
        skills.mkdir(parents=True)
        (skills / "real.md").write_text("guidance", encoding="utf-8")
        outside = temporary / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        try:
            (skills / "link.md").symlink_to(outside)
        except OSError:
            pass  # Windows without symlink rights cannot make the link.
        assert portable_game_files(linked) == [".dazedtl/skills/real.md"], (
            portable_game_files(linked)
        )

        # A database pass translates only the names still in Japanese. It used
        # to replace the whole glossary section with them, which erased about
        # 1,100 rows of a game after a patch added a few items.
        from modules import srpg
        from util.paths import ensure_game_glossary
        from util.vocab import BASE_SEPARATOR

        harvest = temporary / "harvest-game"
        (harvest / "log").mkdir(parents=True)
        glossary = ensure_game_glossary(harvest)
        game_text = "# Items\n薬 (Potion)\n毒 (Poison)\n\n# Skills\n火 (Fire)\n\n"
        game_text += (
            "# Game Characters\nサンク (Sank) - Male\nニーナ / ネーナ (Nina)\n\n"
        )
        base_text = BASE_SEPARATOR + "# Honorifics\nさん (san)\n"
        glossary.write_text(game_text + base_text, encoding="utf-8", newline="\n")
        items = [None] + [
            {"id": number, "name": name, "description": "", "note": ""}
            for number, name in enumerate(["Potion", "新薬"], 1)
        ]

        def database_names(text, _history, *_args, **_kwargs):
            return [["EN:" + value for value in text], [0, 0]]

        directory = os.getcwd()
        os.chdir(harvest)
        try:
            with (
                patch.dict(os.environ, {"DAZED_GAME_ROOT": str(harvest)}),
                patch.multiple(
                    parser,
                    IGNORETLTEXT=True,
                    translateAI=extensions.point(database_names),
                ),
            ):
                parser.searchNames(items, None, "Items", "Items.json")
                assert items[2]["name"] == "EN:新薬", items
                text = glossary.read_text(encoding="utf-8")
                assert text == (
                    game_text.replace("毒 (Poison)\n", "毒 (Poison)\n新薬 (EN:新薬)\n")
                    + base_text
                ), text
                # SRPG Studio fills the same sections; its characters stay as
                # curated, while a name translated again takes its new spelling.
                # A name a hand-written row lists as a variant gained a
                # conflicting row, and Assistant-led's import then refused.
                srpg.update_vocab_section(
                    "Game Characters",
                    [("サンク", "Sunk"), ("ネーナ", "Nena"), ("新人", "Newbie")],
                    curated=True,
                )
                srpg.update_vocab_section("Items", [("毒", "Venom")])
                text = glossary.read_text(encoding="utf-8")
                expected = game_text.replace(
                    "毒 (Poison)", "毒 (Venom)\n新薬 (EN:新薬)"
                )
                expected = expected.replace("(Nina)\n", "(Nina)\n新人 (Newbie)\n")
                assert text == expected + base_text, text
                from util.len_translation import LenProject, import_glossary

                imported = import_glossary(
                    LenProject(harvest), {"names": {"リナ": {"en": "Rina"}}}
                )
                assert imported["added"] == 1, imported
        finally:
            os.chdir(directory)

        # Database text keeps the lines its source draws. The pass ran them
        # together and rewrapped them by width, losing a weapon's skill line
        # and the full-width-space rows a detail note draws as blank rows.
        skill_line = "鋭い刃。\n\\C[24]武器スキル：\\C[0]刺突"
        detail = "重厚な大斧\n\u3000\n以下の特殊効果を持つ\n・毎ターンTP25増加"
        answers = {
            "刺突剣": "Rapier",
            "短剣": "Dagger",
            skill_line: "A keen blade.\n\\C[24]Weapon Skill: \\C[0]Thrust",
            "短い刃。\n予備の武器。": "A short blade.\n"
            "A spare weapon kept in reserve for when the first breaks.",
            detail: "A massive greataxe favored by strongmen\n\u3000\n"
            "Has the following special effects\n・TP +25 every turn",
            "村": "Village",
        }
        weapons = [
            None,
            {
                "id": 1,
                "name": "刺突剣",
                "description": skill_line,
                "note": f"<NameColor:23>\n<dPlnText:{detail}>",
            },
            {
                "id": 2,
                "name": "短剣",
                "description": "短い刃。\n予備の武器。",
                "note": "",
            },
        ]
        sent = []

        def database_lines(text, _history, *_args, **_kwargs):
            sent.extend(text)
            return [[answers[value] for value in text], [0, 0]]

        os.chdir(harvest)
        try:
            with (
                patch.dict(os.environ, {"DAZED_GAME_ROOT": str(harvest)}),
                patch.multiple(
                    parser,
                    IGNORETLTEXT=True,
                    LISTWIDTH=40,
                    NOTEWIDTH=30,
                    translateAI=extensions.point(database_lines),
                ),
            ):
                parser.searchNames(weapons, None, "Weapons", "Weapons.json")
                assert skill_line in sent, sent
                assert weapons[1]["description"] == answers[skill_line], weapons
                # A line too wide wraps evenly on its own; blank rows stay.
                assert weapons[1]["note"] == (
                    "<NameColor:23>\n<dPlnText:A massive greataxe\n"
                    "favored by strongmen\n\u3000\nHas the following\n"
                    "special effects\n・TP +25 every turn>"
                ), weapons[1]["note"]
                # A help window has the source's rows; text that needs more
                # of them with its lines kept flows instead.
                assert weapons[2]["description"] == (
                    "A short blade. A spare weapon kept in\n"
                    "reserve for when the first breaks."
                ), weapons[2]["description"]
                # Kept full-width-space rows are not Japanese left to translate.
                sent.clear()
                parser.searchNames(weapons, None, "Weapons", "Weapons.json")
                assert sent == [], sent
                # VX Ace keeps MapInfos as a hash by map ID; the names pass
                # indexed it as a list and failed with KeyError: 0.
                infos = {"1": {"id": None, "name": "村", "order": 1}}
                result = parser.parseNames(infos, "MapInfos.json", "MapInfos")
                assert result[0] is infos and result[2] is None, result
                assert infos["1"]["name"] == "Village", infos
        finally:
            os.chdir(directory)
        # Fitting the text again, as Apply and new Line widths do, keeps them.
        from util.rpgmaker_rewrap import Layout, fit_document

        fitted = json.loads(json.dumps(weapons))
        widths = {"width": 55, "faceWidth": 55, "listWidth": 40, "noteWidth": 30}
        report = fit_document(fitted, "Weapons.json", Layout.from_widths(widths))
        assert not report.changes and fitted == weapons, report.changes
        # A list keeps one item a line, as in Japanese, and a message too
        # long for its window starts each page after a sentence.
        from util.dazedwrap import wrapShaped

        items = wrapShaped(
            r"・Possess \C[24]Red Wine\C[0] ・Scene completed ・Rest in your room",
            30,
            "・\\C[24]赤い酒\\C[0]を所持\n・シーンが発生済み\n・自室で休息",
        )
        assert items == (
            r"・Possess \C[24]Red Wine\C[0]" "\n・Scene completed\n・Rest in your room"
        ), items
        # A message window pages, so an item too wide for its row wraps on rows
        # of its own: Fuuma's banners pulled the item above onto its row,
        # which text QA's lint then flagged in its own corrections.
        from util.rpgmaker_rewrap import wrap_message

        banner = (
            r"\i[343]True Lilith's Miasma"
            "\n"
            r"・SAN \C[1]-9\C[0] every turn."
            "\n"
            r"・Once every 3 turns, \i[71]Lilith's Miasma \C[1]+1\C[0]."
        )
        japanese = (
            r"\i[343]真・リリスの瘴気"
            "\n"
            r"・毎ターンSAN値が\C[1]-9\C[0]される。"
            "\n"
            r"・3ターンに一度、\i[71]リリスの瘴気が\C[1]+1\C[0]される。"
        )
        kept = banner.replace("turns, ", "turns,\n")
        for centred in ("", "\\>\\ac "):
            fitted = wrap_message(
                centred + banner, 36, source="\\>\\ac" + japanese, rows=4
            )
            assert fitted == centred + kept, fitted
        paged = wrapShaped(
            "The gate opens at dawn. Bring the lantern and the key. "
            "We leave before the guards wake up.",
            24,
            rows=2,
        )
        assert paged == (
            "The gate opens at dawn.\n\nBring the lantern\nand the key.\n"
            "We leave before the\nguards wake up."
        ), paged
        # The Japanese fonts RPG Maker games draw text in give ♥, … and
        # full-width marks two cells; counted as one, a row of them is cut off.
        from util.rpgmaker_rewrap import visible_width

        assert visible_width("Fufu…♥ See you～") == 18
        # Accented letters stay half width, as both fonts draw them.
        assert visible_width("Café") == 4
        # ❤ (East Asian width N) is a glyph those fonts lack, which a
        # fallback font draws at least full width; its emoji selector draws
        # nothing of its own.
        assert visible_width("Love you❤ ❤️") == 13
        assert visible_width("©") == 1
        # Only translated text is fitted: Japanese and a text picture, which
        # has no window, stay exact. New widths fit only their own area.
        line = "The old road bends toward a quiet village."
        # A script of the game's own (122 without a source) is code, and a
        # break inside ${...} stopped the game with a SyntaxError; a
        # translated text variable wraps around its interpolations.
        # A line break right before "[" or "<", written as "\n", would start a
        # name code such as \n[1] or \n<name>, so no line starts with one.
        script = (
            "`Score: ${$gameVariables.value(1) + $gameVariables.value(2)} points today`"
        )
        herbs = "`Bring the herbs: [Herb] and <Potion> today`"
        scripts = {
            "list": [
                {"code": 122, "parameters": [1, 1, 0, 4, script]},
                {"code": 122, "parameters": [2, 2, 0, 4, script], "_original": "点数"},
                {"code": 122, "parameters": [3, 3, 0, 4, herbs], "_original": "薬草"},
            ]
        }
        fit_document(
            scripts,
            "CommonEvents.json",
            Layout.from_widths({**widths, "listWidth": 20}),
        )
        assert [command["parameters"][4] for command in scripts["list"]] == [
            script,
            r"`Score: ${$gameVariables.value(1) + $gameVariables.value(2)}\npoints today`",
            r"`Bring the\nherbs: [Herb]\nand <Potion> today`",
        ], scripts
        # A note's translated tag body fits beside a tag left in Japanese,
        # and English with "・" bullets is not Japanese.
        notes = [
            None,
            {
                "note": "<SG説明:A light blade of copper.>\n<SG種別:武器>",
                "description": "・Light blade\n・Easy to swing in a fight",
            },
            {"description": "A blade whose tale runs on for more rows than it has"},
        ]
        report = fit_document(
            notes,
            "Weapons.json",
            Layout.from_widths({**widths, "listWidth": 20, "noteWidth": 20}),
        )
        assert (
            notes[1]["note"] == "<SG説明:A light blade of\ncopper.>\n<SG種別:武器>"
        ), notes
        # A list that needs more rows than its window shows flows together:
        # kept one item a line, the game cut off its last row.
        assert notes[1]["description"] == "・Light blade ・Easy\nto swing in a fight", (
            notes
        )
        # Flowed, its items still start a line where the rows allow it; the
        # even lines broke inside the first item and ran the next one on.
        from util.rpgmaker_rewrap import wrap_lines

        flowed = wrap_lines("Effect:\n・Attack up by a lot\n・Defense up", 30, 2)
        assert flowed == "Effect: ・Attack up by a lot\n・Defense up", flowed
        assert [row["pointer"] for row in report.misfits] == ["/2/description"], (
            report.misfits
        )
        page = {
            "list": [
                {
                    "code": 401,
                    "parameters": [line],
                    "_original": "古い道は静かな村へと曲がっていく。",
                },
                {
                    "code": 401,
                    "parameters": [
                        "古い道は静かな村へと曲がっていく、そして長い夜が来る。"
                    ],
                },
                {
                    "code": 357,
                    "parameters": ["DTextPicture", "dText", "", {"text": line * 2}],
                },
            ]
        }
        narrow = Layout.from_widths({**widths, "width": 30, "faceWidth": 30})
        untouched = json.loads(json.dumps(page))
        assert not fit_document(
            page, "Map001.json", narrow, areas={"noteWidth"}
        ).changes
        assert fit_document(page, "Map001.json", narrow).changes
        assert page["list"][0]["parameters"] == [
            "The old road bends\ntoward a quiet village."
        ], page
        assert page["list"][1:] == untouched["list"][1:], page

        # Assistant-led writes a message one row per command, as its Japanese
        # was. Its writes fit a message again over the same commands, so a
        # saved game's place in the event and each command's source stay: a
        # blank first row stays, a centring code is repeated before a word
        # with a space between (\acThe hides "The"), and a Scroll Text row
        # wraps in its own command, keeping a list's rows.
        def assistant_led_writes():
            from util import rpgmaker_qa as qa
            from util.len_originals import write_rpgmaker_json
            from util.rpgmaker_rewrap import spread

            def command(code, parameters, **extra):
                return {"code": code, "indent": 0, "parameters": parameters, **extra}

            gate = "\n塔の門は封印を持つ者にだけ開く。\n持っているか？\n"
            source = [
                command(101, ["", 0, 0, 2, "リリス"]),
                *(command(401, [row]) for row in gate.split("\n")),
                command(101, ["", 0, 0, 2, ""]),
                command(401, [r"\ac\C[2]第一章　リリスの塔\C[0]"]),
                command(105, [2, False]),
                *(
                    command(405, [row])
                    for row in (
                        "スタッフ",
                        "",
                        "ツクールMV素材集 和風",
                        "(C) Gotcha Gotcha Games",
                    )
                ),
                command(356, ["D_TEXT 時刻 24"]),
                command(356, ["D_TEXT 地図 24"]),
                command(0, []),
            ]
            staged = deepcopy(source)
            for item, row in zip(
                staged,
                [
                    ["", 0, 0, 2, "Lilith"],
                    "",
                    "The tower's gate opens only for those who carry the seal.",
                    "Do you have it?",
                    "",
                    None,
                    r"\ac\C[2]Chapter One: The Tower of Lilith\C[0]",
                    None,
                    "Credits",
                    "",
                    "RPG Maker MV Official Asset Collection Japanese Style",
                    "(C) Gotcha Gotcha Games Inc.",
                ],
            ):
                if isinstance(row, list):
                    item["parameters"] = row
                elif row is not None:
                    item["parameters"] = [row]
            # A space splits a plugin command into more arguments than its
            # source; joined words keep the count.
            staged[12]["parameters"] = ["D_TEXT Current time 24"]
            staged[13]["parameters"] = ["D_TEXT World_map 24"]
            files = {}
            for name, value in (
                ("source", source),
                ("staged", staged),
                ("game", source),
            ):
                files[name] = temporary / f"{name}-Map001.json"
                files[name].write_text(json.dumps({"list": value}, ensure_ascii=False))
            game = files["game"].with_name("Map001.json")
            files["game"].replace(game)
            tight = {**widths, "width": 30, "faceWidth": 30, "messageRows": 4}
            written = write_rpgmaker_json(
                files["source"], files["staged"], game, Layout.from_widths(tight)
            )
            assert written["fitted"] == 3 and not written["misfits"], written
            assert (written["split_commands"], written["split_count"]) == (
                [
                    {
                        "file": "Map001.json",
                        "pointer": "/list/12/parameters/0",
                        "text": "D_TEXT Current time 24",
                        "arguments": 4,
                        "source_arguments": 3,
                    }
                ],
                1,
            ), written
            fitted = json.loads(game.read_text(encoding="utf-8"))["list"]
            assert [item["parameters"][0] for item in fitted[1:5]] == [
                "",
                "The tower's gate opens",
                "only for those who carry",
                "the seal. Do you have it?",
            ], fitted
            assert fitted[1]["_original"] == gate, fitted[1]
            assert fitted[6]["parameters"] == [
                "\\ac\\C[2]Chapter One:\n\\ac The Tower of Lilith\\C[0]"
            ], fitted[6]
            assert [item["parameters"][0] for item in fitted[8:12]] == [
                "Credits",
                "",
                "RPG Maker MV Official Asset\nCollection Japanese Style",
                "(C) Gotcha Gotcha Games Inc.",
            ], fitted
            # Writing again lines up with the source and changes nothing.
            before = game.read_bytes()
            # The engine CLI writes without fitting, so in a game DazedTL
            # manages it refuses, naming the helper's write_rpgmaker.
            from scripts.len_translation import main as len_cli

            owned = temporary / "managed"
            (owned / ".git/dazedtl").mkdir(parents=True)
            (owned / ".git/dazedtl/project.json").write_text('{"projectId": "x"}')
            (owned / "data").mkdir()
            (owned / "data/Map001.json").write_bytes(before)
            refused = [
                "write-rpgmaker-json",
                *("--source", str(files["source"]), "--translated"),
                *(str(files["staged"]), "--output", str(owned / "data/Map001.json")),
            ]
            assert len_cli(refused) == 1
            assert (owned / "data/Map001.json").read_bytes() == before
            assert (
                write_rpgmaker_json(
                    files["source"], files["staged"], game, Layout.from_widths(tight)
                )["fitted"]
                == 3
            )
            assert game.read_bytes() == before
            # Saving narrower widths fits what was written to the old ones:
            # VX Ace text written with MV/MZ's widths ran past its windows.
            from util.len_originals import fit_game
            from util.rpgmaker_rewrap import widest_line

            narrow = Layout.from_widths({**tight, "width": 24, "faceWidth": 24})
            refit = fit_game(game.parent, narrow)
            assert refit["files"] == ["Map001.json"] and refit["fitted"], refit
            refitted = json.loads(game.read_text(encoding="utf-8"))["list"]
            assert len(refitted) == len(fitted) and refitted[1]["_original"] == gate
            assert (
                max(widest_line(item["parameters"][0]) for item in refitted[1:5]) <= 24
            )
            game.write_bytes(before)
            # A staged copy of the game taken before wider widths were saved
            # is written as if fitted at them, not with the narrower rows; at
            # the widths it was fitted at, it is written as it is.
            snapshot = temporary / "snapshot"
            snapshot.write_bytes(before)
            write_rpgmaker_json(
                files["source"], snapshot, game, Layout.from_widths(tight)
            )
            assert game.read_bytes() == before
            wide = Layout.from_widths({**tight, "width": 40, "faceWidth": 40})
            assert fit_game(game.parent, wide)["fitted"]
            widened = game.read_bytes()
            assert write_rpgmaker_json(files["source"], snapshot, game, wide)["fitted"]
            assert game.read_bytes() == widened, game.read_text(encoding="utf-8")
            game.write_bytes(before)
            # A choice's help is fitted too, kept on the comment as written:
            # its Japanese, marker first, on the 108.
            asked = [
                command(102, [["見る", "見ない"], 1, 0, 2, 0]),
                command(402, [0, "見る"]),
                command(108, ["選択肢ヘルプ"], indent=1),
                command(408, ["所要時間:20分"], indent=1),
                command(408, ["初回は見ることを推奨します。"], indent=1),
                command(0, [], indent=1),
                command(404, []),
                command(0, []),
            ]
            answered = deepcopy(asked)
            answered[0]["parameters"][0] = ["Watch", "Skip"]
            answered[3]["parameters"] = [
                "It takes about twenty minutes to watch it all."
            ]
            answered[4]["parameters"] = ["We recommend watching it the first time."]
            helped = temporary / "helped"
            helped.mkdir()
            for name, value in (("source", asked), ("staged", answered)):
                (helped / name).write_text(
                    json.dumps({"list": value}, ensure_ascii=False)
                )
            written = write_rpgmaker_json(
                helped / "source",
                helped / "staged",
                helped / "Map002.json",
                Layout.from_widths(tight),
            )
            rows = json.loads((helped / "Map002.json").read_text(encoding="utf-8"))[
                "list"
            ]
            assert written["fitted"] == 1 and len(rows) == len(asked), (written, rows)
            assert rows[2]["_original"].startswith("選択肢ヘルプ\n"), rows[2]
            assert max(widest_line(row["parameters"][0]) for row in rows[3:5]) <= 30, (
                rows
            )

            # Text QA corrects such a message as one text, fitted and spread over
            # its commands, however many rows it needs; undoing finds it there.
            pointers = [f"/list/{index}/parameters/0" for index in range(1, 5)]
            live = "\n".join(item["parameters"][0] for item in fitted[1:5])
            record = {
                "event_code": 401,
                "live_pointers": pointers,
                "live_transform": "identity",
                "speaker": {},
            }
            box = qa._box(record, {"widths": tight})
            assert box["wraps"], box
            correction = (
                "\nOnly a bearer of the seal may pass the gate. Do you carry it?"
            )
            problems = qa.correction_problems(
                gate, live, correction, 401, pointers, "identity", box=box
            )
            assert not problems, problems
            replacement = qa._fit(correction, live, box, gate, len(pointers))
            assert replacement == (
                "\nOnly a bearer of the\nseal may pass the gate.\nDo you carry it?"
            ), replacement
            operation = {
                "live_pointers": pointers,
                "live_transform": "identity",
                "expected": live,
                "replacement": replacement,
                "message": True,
            }
            document = {"list": deepcopy(fitted)}
            for pointer, value in qa._operation_writes(document, operation):
                qa._set_pointer(document, pointer, value)
            assert [item["parameters"][0] for item in document["list"][1:5]] == spread(
                replacement, 4
            ), document
            undo = {**operation, "expected": replacement, "replacement": live}
            for pointer, value in qa._operation_writes(document, undo):
                qa._set_pointer(document, pointer, value)
            assert document["list"][1:5] == fitted[1:5], document

            # Fitting repeats a row's instant-line code on the rows it adds,
            # which keeps the source's codes; a code the correction drops is
            # named, so the next correction can keep it.
            banner = "\\>\\i[322]種付けプレス追加\n\\>\\C[27]解放条件:\\C[0]イベント2を見る。"
            pointers = pointers[:1]
            live = "\\>\\i[322]Added\n\\>\\C[27]Unlock:\\C[0]See Event 2."
            box = qa._box({**record, "live_pointers": pointers}, {"widths": tight})
            correction = (
                "\\>\\i[322]Mating Press added\n"
                "\\>\\C[27]Unlock Condition:\\C[0] See the Generic Event 2."
            )
            fitted_banner = qa._fit(correction, live, box, banner, 1)
            assert fitted_banner.count("\\>") == 3, fitted_banner
            problems = qa.correction_problems(
                banner, live, correction, 401, pointers, "identity", box=box
            )
            assert not problems, problems
            problems = qa.correction_problems(
                banner,
                live,
                correction.replace("\\C[0]", ""),
                401,
                pointers,
                "identity",
                box=box,
            )
            assert problems == ["introduces runtime-token-mismatch (drops \\C[0])"], (
                problems
            )

        assistant_led_writes()

        # MV and Ace print the battler's name right before a particle-first
        # battle message; stripping the space after Taro printed "Arinafell!".
        assert parser._strip_taro_placeholder('"Taro fell!"') == " fell!"
        assert (
            parser._strip_taro_placeholder("Taro's Illusion wore off.")
            == "'s Illusion wore off."
        )

        def command(code, parameters, **extra):
            return {"code": code, "indent": 0, "parameters": parameters, **extra}

        def name(value, **extra):
            return command(101, ["", 0, 0, 2, value], **extra)

        calls, names = [], []

        def translate(text, history, *args):
            calls.append((deepcopy(text), history))
            return [
                [
                    r"[Carry the \C[6]Recovery Charm\C[0] to block one attack.]"
                    if "回復のお守り" in value
                    else "[Hana]: Hello."
                    for value in text
                ],
                [0, 0],
            ]

        def speaker(value):
            names.append(value)
            return ["Hana", [0, 0]]

        def parse(commands):
            calls.clear()
            names.clear()
            page = {"list": deepcopy(commands + [command(0, [])])}
            parser.searchCodes(
                page, SimpleNamespace(update=lambda *_: None), [], "Map001.json"
            )
            return page["list"]

        options = {
            "CODE101": True,
            "CODE401": True,
            "IGNORETLTEXT": True,
            "PRESERVEORIGINAL": True,
            "FIRSTLINESPEAKERS": False,
            "INLINE401SPEAKERS": False,
            "FACENAME101": False,
            "AUTONAMEPOPUP101": False,
            "SPEAKER_PARSE_MODE": False,
            "FIXTEXTWRAP": False,
            "translateAI": extensions.point(translate),
            "getSpeaker": speaker,
        }
        policy = {
            "choiceCollection": CHOICE_COLLECTION,
            "speakerContext": SPEAKER_CONTEXT,
            "sameLineSpeakers": SAME_LINE_SPEAKERS,
            "codeNameplates": CODE_NAMEPLATES,
        }
        with patch.multiple(parser, **options):
            for generation in (policy, policy, {}, policy):
                configure_states({"engine": "MVMZ"}, temporary, generation)
                commands = [
                    name(r"\C[2]【Hana】\C[0]", _original="花"),
                    command(401, ["こんにちは"]),
                    name(""),
                    command(401, ["地の文"]),
                    name("Hana"),
                    command(401, ["話します"]),
                    name("花"),
                    command(401, ["Already translated."], _original="訳済み"),
                    name(""),
                    command(401, ["誰かの言葉"]),
                ]
                result = parse(commands)
                expected = (
                    ["[Hana]: こんにちは", "地の文", "[Hana]: 話します", "誰かの言葉"]
                    if generation
                    else ["こんにちは", "地の文", "話します", "[Hana]: 誰かの言葉"]
                )
                assert calls == [(expected, "")], calls
                assert names == ["花"], names
                assert result[0] == commands[0] and result[4] == commands[4], result
                assert (
                    result[1]["parameters"] == ["Hello."]
                    and result[1]["_original"] == "こんにちは"
                ), result
                assert result[7] == commands[7], result

            tutorial = r"[道具屋の\C[6]「回復のお守り」\C[0]を持っていれば攻撃を一回だけ防げる]"
            result = parse(
                [
                    name(""),
                    command(401, [tutorial], _original=tutorial),
                    command(
                        401,
                        ["[Already translated.]"],
                        _original="[回復薬を使うと体力が回復する]",
                    ),
                ]
            )
            assert names == [], names
            assert (
                len(calls) == 1 and isinstance(calls[0][0], list) and calls[0][1] == ""
            ), calls
            assert (
                r"\C[6]" in calls[0][0][0]
                and r"\C[0]" in calls[0][0][0]
                and "回復のお守り" in calls[0][0][0]
            ), calls
            assert result[1]["parameters"] == [
                r"[Carry the \C[6]Recovery Charm\C[0] to block one attack.]"
            ], result
            assert result[1]["_original"] == tutorial, result
            assert (
                result[2]["parameters"] == ["[Already translated.]"]
                and result[2]["_original"] == "[回復薬を使うと体力が回復する]"
            ), result

            # Actual standalone nameplates still supply context and retain
            # their display wrappers; code 101 off still means no 101 prefix.
            for label in ("花", "Hana", r"\C[2]花\C[0]"):
                parse(
                    [
                        name(""),
                        command(401, [f"[{label}]"]),
                        command(401, ["こんにちは"], _original="こんにちは"),
                    ]
                )
                assert calls == [(["[Hana]: こんにちは"], "")], calls
                assert names, label
            # A same-line nameplate travels only as the [Speaker]: prefix.
            # Repeated in the body, the model kept it and a narration label
            # was written twice. Older frozen runs keep their request bodies.
            label = ["【ユウイベント1】：『ハルカとプールで特訓1』", "再生しますか？"]
            for generation, body in (
                ({}, '【ユウイベント1】："ハルカとプールで特訓1"'),
                (policy, '"ハルカとプールで特訓1"'),
            ):
                configure_states({"engine": "MVMZ"}, temporary, generation)
                result = parse([name(""), *(command(401, [line]) for line in label)])
                assert calls == [([f"[Hana]: {body}\n再生しますか？"], "")], calls
                assert result[1]["parameters"] == ["[Hana]\nHello."], result
                assert result[1]["_original"] == "\n".join(label), result
            # A message opening with a plugin's \m[N]\z[N] codes read as a
            # nameplate with no name, so its first line was never sent and
            # stayed in Japanese; a name before the codes still makes one.
            # Older frozen runs keep their request bodies.
            message = [r"\m[2]\z[1454]あら、釣りをするのね。", "頑張って釣ってね。"]
            for generation, body in (
                ({}, message[1]),
                (policy, "あら、釣りをするのね。\n頑張って釣ってね。"),
            ):
                configure_states({"engine": "MVMZ"}, temporary, generation)
                result = parse(
                    [name("ママ"), *(command(401, [line]) for line in message)]
                )
                assert calls == [([f"[Hana]: {body}"], "")], calls
            assert result[1]["parameters"] == [r"\m[2]\z[1454]Hello."], result
            parse(
                [
                    name(""),
                    command(401, [r"ママ\m[2]\z[1454]"]),
                    command(401, [message[1]]),
                ]
            )
            assert calls == [([f"[Hana]: {message[1]}"], "")], calls
            assert names and set(names) == {"ママ"}, names
            with patch.object(parser, "INLINE401SPEAKERS", True):
                parse([name(""), command(401, ["花「こんにちは」"])])
                assert calls == [(['[Hana]: "こんにちは"'], "")], calls
            parse(
                [
                    name("Hana"),
                    command(401, ["こんにちは"]),
                    command(401, ["元気ですか"]),
                ]
            )
            assert calls == [(["[Hana]: こんにちは\n元気ですか"], "")], calls
            parse([name(r"\N[1]"), command(401, ["こんにちは"])])
            assert calls == [([r"[\N[1]]: こんにちは"], "")] and not names, calls
            with patch.object(parser, "CODE101", False):
                parse([name("Hana"), command(401, ["こんにちは"])])
                assert calls == [(["こんにちは"], "")] and not names, calls
            # Messages come out laid out like the Japanese where the English
            # allows, and already fitted: a name window and centring take no
            # room on the line, so fitting them again changes nothing.
            english = {
                "村の状態": "The village's status will change as people move in "
                "and buildings are constructed.",
                "今日はもう遅い": "It's already late today... Let's play tomorrow.",
                "それでも": "And yet... To me, he looked like nothing but a monster.",
            }

            def wrapped_messages(text, *_args, **_kwargs):
                found = [
                    next(value for key, value in english.items() if key in line)
                    for line in text
                ]
                return [found, [0, 0]]

            with patch.multiple(
                parser,
                FIXTEXTWRAP=True,
                WIDTH=55,
                FACEWIDTH=45,
                MESSAGEROWS=4,
                translateAI=extensions.point(wrapped_messages),
            ):
                result = parse(
                    [
                        name(""),
                        command(401, [r"\n<システム>村の状態は人が移住したり"]),
                        command(401, ["建物が建設されたりすると変化します。"]),
                        name(""),
                        command(401, [""]),
                        command(401, ["今日はもう遅い…。"]),
                        command(401, ["遊ぶのは明日にしよう。"]),
                        name(""),
                        command(401, [r"\ac それでも……私には、"]),
                        command(401, [r"\ac 彼は怪物にしか見えなかった。"]),
                    ]
                )
            texts = [row["parameters"][0] for row in result if row["code"] == 401]
            assert texts == [
                (
                    "\\n<Hana>The village's status will change as people\n"
                    "move in and buildings are constructed."
                ),
                # The blank first row and one sentence a line, as in Japanese.
                "\nIt's already late today...\nLet's play tomorrow.",
                "\\ac And yet... To me,\n\\ac he looked like nothing but a monster.",
            ], texts
            from util.rpgmaker_rewrap import Layout, fit_document

            widths = {"width": 55, "faceWidth": 45, "listWidth": 74, "noteWidth": 45}
            report = fit_document(
                {"list": result}, "Map001.json", Layout.from_widths(widths)
            )
            assert not report.changes, report.changes
            # A message left untranslated or refused keeps every row; it was
            # written back over its first row, and the others were dropped.
            # A translated scroll is laid over its own rows, adding and
            # removing none, so a saved game's place in the event stays valid.
            bard = [
                name("花"),
                *(command(401, [f"歌その{index}"]) for index in (1, 2, 3)),
                command(105, [2, False]),
                command(405, ["巻物の一行目"]),
                command(405, ["巻物の二行目"]),
            ]

            def scroll_only(text, *_args, **_kwargs):
                return [
                    [
                        "Scroll one.\nScroll two.\nScroll three."
                        if "巻物" in line
                        else line
                        for line in text
                    ],
                    [0, 0],
                ]

            for wrap in (False, True):
                with patch.multiple(
                    parser,
                    FIXTEXTWRAP=wrap,
                    CODE405=True,
                    translateAI=extensions.point(scroll_only),
                ):
                    result = parse(bard)
                assert [row["code"] for row in result] == [
                    *(row["code"] for row in bard),
                    0,
                ], result
                result = [row for row in result if row["code"] != -1]
                scroll = (
                    [["Scroll one. Scroll two. Scroll three."], [""]]
                    if wrap
                    else [["Scroll one."], ["Scroll two.\nScroll three."]]
                )
                assert result[1:5] == bard[1:5], result
                assert [row["parameters"] for row in result[5:]] == [*scroll, []], (
                    result
                )
                assert result[5]["_original"] == "巻物の一行目\n巻物の二行目", result
            # A choice plugin shows each comment line (408) under its help
            # marker as a row. JOIN408 translates the block as one text; it is
            # written back a line per row, laid out like the Japanese, over the
            # rows it came from, which it records; a later run keeps them, and
            # lines translated one by one too.
            help_lines = [
                command(108, ["選択肢ヘルプ"]),
                command(408, ["所要時間:20分"]),
                command(408, ["初回は見ることを推奨します。"]),
            ]
            english = "Takes about 20 minutes. We recommend watching it the first time."
            with patch.multiple(
                parser,
                CODE408=True,
                JOIN408=True,
                FIXTEXTWRAP=True,
                WIDTH=55,
                translateAI=extensions.point(
                    lambda text, *_: [[english for _value in text], [0, 0]]
                ),
            ):
                result = parse(help_lines)
                assert result[:3] == [
                    help_lines[0],
                    command(
                        408,
                        ["Takes about 20 minutes."],
                        _original="所要時間:20分\n初回は見ることを推奨します。",
                        _rows=2,
                    ),
                    command(408, ["We recommend watching it the first time."]),
                ], result
                assert parse(result[:-1]) == result, result
                # One line at a time, a line too wide for the window wraps
                # within its own row: no command is added.
                with patch.object(parser, "JOIN408", False):
                    result = parse(help_lines[:2])
                    assert result[1:] == [
                        command(
                            408,
                            [
                                "Takes about 20 minutes.\nWe recommend watching it the first time."
                            ],
                            _original="所要時間:20分",
                            _rows=1,
                        ),
                        command(0, []),
                    ], result
                    assert parse(result[:-1]) == result, result
                lines = [
                    help_lines[0],
                    command(408, ["Line one."], _original="一行目"),
                    command(408, ["Line two."], _original="二行目"),
                ]
                assert parse(lines)[:-1] == lines
                # A translation written again goes over the rows it recorded,
                # never the game's own row after them.
                again = [
                    help_lines[0],
                    command(408, ["所要時間:20分"], _original="所要時間:20分", _rows=1),
                    command(408, ["(1/3)"]),
                ]
                result = parse(again)
                assert len(result) == 4 and result[2] == again[2], result
                # A marker the game's choice plugin lists in its settings counts.
                choice = temporary / "choice"
                (choice / "js").mkdir(parents=True)
                plugin = {
                    "name": "MPP_ChoiceEX",
                    "status": True,
                    "parameters": {"Choice Help Commands": '["ChoiceHelp"]'},
                }
                (choice / "js/plugins.js").write_text(
                    f"var $plugins =\n[{json.dumps(plugin)}];\n", encoding="utf-8"
                )
                with patch.dict(os.environ, {"DAZED_GAME_ROOT": str(choice)}):
                    result = parse([command(108, ["ChoiceHelp"]), help_lines[1]])
                assert result[1] == command(
                    408,
                    [
                        "Takes about 20 minutes.\nWe recommend watching it the first time."
                    ],
                    _original="所要時間:20分",
                    _rows=1,
                ), result
                # A choice's help shows beside the face of the message the
                # choice follows, joined choices included, so it wraps to the
                # portrait width there.
                from util.rpgmaker_rewrap import Layout, fit_document, widest_line

                def choosing(face):
                    return [
                        command(101, [face, 0, 0, 2, ""]),
                        command(401, ["Pick one."]),
                        command(102, [["Stay"], -1, 0, 2, 0]),
                        command(402, [0, "Stay"]),
                        command(404, []),
                        command(102, [["Watch"], -1, 0, 2, 0]),
                        command(402, [0, "Watch"]),
                        *(dict(line, indent=1) for line in help_lines),
                        command(404, []),
                    ]

                with patch.object(parser, "FACEWIDTH", 30):
                    beside, alone = (
                        [row["parameters"][0] for row in parse(choosing(face))[8:-2]]
                        for face in ("Actor1", "")
                    )
                assert max(map(widest_line, beside)) <= 30, beside
                assert max(map(widest_line, alone)) > 30, alone
            # Narrower Line widths fit translated help again over its own
            # comment lines, beside the face; a comment that is no choice's
            # help, such as a plugin's setting, stays as written.
            helped = choosing("Actor1")[:7] + [
                command(108, ["選択肢ヘルプ"], indent=1),
                command(
                    408,
                    ["Takes about 20 minutes. Watch it once."],
                    indent=1,
                    _original="所要時間:20分",
                ),
                command(408, ["We recommend it."], indent=1),
                command(404, []),
                command(108, ["<Popup>"]),
                command(408, ["A note wider than any window shows."], _original="メモ"),
            ]

            def fit(face_width):
                layout = Layout(20, face_width, 74, 45, 4)
                report = fit_document({"list": helped}, "Map001.json", layout)
                rows = "\n".join(row["parameters"][0] for row in helped[8:10])
                return report.misfits, rows.split("\n")

            misfits, rows = fit(16)
            assert not misfits and len(rows) == 4, rows
            assert max(map(widest_line, rows)) <= 16, rows
            assert len(helped) == 13 and helped[-1]["parameters"] == [
                "A note wider than any window shows."
            ], helped
            # Rows past the message window's are a page the player never sees.
            misfits, rows = fit(10)
            assert [row["reason"] for row in misfits] == [
                f"needs {len(rows)} rows; its window shows 4"
            ], (misfits, rows)
            # Plugins split 356 commands on spaces, so each handler joins a
            # translation's words its own way. A kept placeholder stays, and
            # must not shift the next translation onto the wrong command.
            english = {"時刻": "Current time", "共鳴度+3": "Resonance +3"}
            english["地図"] = "World map"
            with patch.multiple(
                parser,
                CODE356=True,
                CODE108=True,
                NBSP_356=["CommonPopup"],
                SPACES_108=["text_indicator"],
                KEEP_356=["D_TEXT [マップ表示名] 24"],
                translateAI=extensions.point(
                    lambda text, *_: [[english[value] for value in text], [0, 0]]
                ),
            ):
                result = parse(
                    [
                        command(356, ["D_TEXT [マップ表示名] 24"]),
                        command(356, ["D_TEXT 時刻 24"]),
                        command(356, ["CommonPopup add text:共鳴度+3 count:60"]),
                        command(108, ["text_indicator : 地図"]),
                    ]
                )
            assert [row["parameters"][0] for row in result[:4]] == [
                "D_TEXT [マップ表示名] 24",
                "D_TEXT Current_time 24",
                "CommonPopup add text:Resonance\u00a0+3 count:60",
                "text_indicator : World map",
            ], result
            # Text no built-in handler captures stayed Japanese. A game's own
            # patterns translate only their last group, only when it holds
            # Japanese, read a script's lines only when its first line names
            # it, and keep a script's string valid around an apostrophe.
            english.update({"宝箱だ": "It's a chest", "扉": "Door", "看板": "Old sign"})
            english["クエスト"] = "Quest log"
            with patch.multiple(
                parser,
                CODE355655=True,
                CODE356=True,
                CODE108=True,
                CODE357=True,
                ENABLED_PATTERNS_355655=set(),
                ENABLED_PLUGINS_357=set(),
                CUSTOM_355655=[
                    {"name": "notice", "regex": r"Notice\.show\('(.*)'\)"},
                    {"name": "lines", "regex": r'^\s*"(.*)",$', "script": "var doors"},
                ],
                CUSTOM_356=[
                    {"name": "sign", "regex": r"^SignText \d+ (.+)$", "spacing": "nbsp"}
                ],
                CUSTOM_108=[
                    {"name": "label", "regex": r"<Label:(.+)>", "spacing": "space"}
                ],
                CUSTOM_357=[
                    {"plugin": "QuestLog", "command": "add", "args": ["title"]}
                ],
                translateAI=extensions.point(
                    lambda text, *_: [[english[value] for value in text], [0, 0]]
                ),
            ):
                result = parse(
                    [
                        command(355, ["Notice.show('宝箱だ');"]),
                        command(355, ["Notice.show('se_chest');"]),
                        command(355, ["var doors = ["]),
                        command(655, ['  "扉",']),
                        command(355, ["var names = ["]),
                        command(655, ['  "看板",']),
                        command(356, ["SignText 3 看板"]),
                        command(108, ["<Label:地図>"]),
                        command(
                            357,
                            [
                                "QuestLog",
                                "add",
                                "追加",
                                {"title": "クエスト", "id": "q1"},
                            ],
                        ),
                    ]
                )
            assert [row["parameters"] for row in result[:9]] == [
                ["Notice.show('It\\'s a chest');"],
                ["Notice.show('se_chest');"],
                ["var doors = ["],
                ['  "Door",'],
                ["var names = ["],
                ['  "看板",'],
                ["SignText 3 Old\u00a0sign"],
                ["<Label:World map>"],
                ["QuestLog", "add", "追加", {"title": "Quest log", "id": "q1"}],
            ], result
            # VX Ace evaluates a text variable's script with Ruby, where the
            # template literal MV/MZ reads ran a shell command. An Ace
            # project's runs, Batch's saved profile included, say it is Ace.
            from desktop.backend.manual import run_plan
            from desktop.backend.workflow import Workflows
            from util.game_settings import normalize_wrap_widths

            flows = Workflows(temporary / "workspace", None, None, None)
            flows.projects["ace"] = {
                "id": "ace",
                "engine": "ACE",
                "source": str(game),
                "engine_options": {"VXACE": False},
                "widths": normalize_wrap_widths(None),
                "phase1_comments": False,
            }
            ace = run_plan(
                temporary / "workspace",
                {"engine": "RPG Maker MV/MZ", "files": [{"name": "Map001.json"}]},
                ["Map001.json"],
                "estimate",
                workflow=flows.phase_workflow("ace", "advanced"),
            )
            assert ace["engines"]["rpgmakermvmz"]["VXACE"], ace["engines"]
            assert ace["runtime_profile"]["config"]["VXACE"], ace["runtime_profile"]
            # Until widths are saved, an Ace game fits to its own windows,
            # which cut off text fitted to MV/MZ's.
            from util.game_settings import ACE_WRAP_WIDTHS, game_wrap_widths

            native = temporary / "native-ace"
            (native / "Data").mkdir(parents=True)
            (native / "Data/Map001.rvdata2").write_bytes(b"")
            assert game_wrap_widths(native) == ACE_WRAP_WIDTHS, game_wrap_widths(native)
            # The source keeps its \n[1] and \nc<name> name codes, which once
            # went out as "\ [1]" and "\ c<name>", and MV/MZ's template literal
            # escapes a translated backtick and ${, which ended it early or
            # interpolated. An interpolation the source runs, such as the
            # hero's name, keeps running; one in a '...' string, which the
            # game shows as text, started running and stopped it.
            operands, requests = {}, []
            replies = {
                r"\\nc<村長>村人と\\n[1]": (
                    r'\\nc<Chief>\C[2]"#{name}"\C[0] `says` ${hi} to \\n[1]'
                ),
                "${name}の部屋": "${name}'s room, not ${hers}",
                "#{name}の部屋": "#{name}'s room, not #{hers}",
            }
            sources = {True: '"#{name}の部屋";', False: "`${name}の部屋`;"}
            texts = {True: "'#{name}の部屋';", False: "'${name}の部屋';"}

            def variable(text, *_):
                requests.extend(text)
                return [[replies[value] for value in text], [0, 0]]

            with patch.multiple(
                parser,
                CODE122=True,
                CODE122_VAR_RANGES="1",
                translateAI=extensions.point(variable),
            ):
                for vxace in (True, False):
                    with patch.object(parser, "VXACE", vxace):
                        result = parse(
                            [
                                command(
                                    122, [1, 1, 0, 4, r'"\\nc<村長>村人と\\n[1]";']
                                ),
                                command(122, [1, 1, 0, 4, sources[vxace]]),
                                command(122, [1, 1, 0, 4, texts[vxace]]),
                            ]
                        )
                    operands[vxace] = [item["parameters"][4] for item in result[:3]]
            assert requests == [
                r"\\nc<村長>村人と\\n[1]",
                "#{name}の部屋",
                "#{name}の部屋",
                r"\\nc<村長>村人と\\n[1]",
                "${name}の部屋",
                "${name}の部屋",
            ], requests
            assert operands == {
                True: [
                    r'"\\nc<Chief>\\C[2]\#{name}\\C[0] `says` ${hi} to \\n[1]";',
                    '"#{name}\'s room, not \\#{hers}";',
                    '"\\#{name}\'s room, not \\#{hers}";',
                ],
                False: [
                    r"`\\nc<Chief>\\C[2]#{name}\\C[0] \`says\` \${hi} to \\n[1]`;",
                    r"`${name}'s room, not \${hers}`;",
                    r"`\${name}'s room, not \${hers}`;",
                ],
            }, operands
            # Batch collection queues a lone label or plugin argument with the
            # file text. It sent each one Live before the Batch cost review.
            from util import rpgmaker_scope

            payloads = []

            def queued(text, *_args):
                payloads.append(deepcopy(text))
                return [deepcopy(text), [0, 0]]

            with (
                patch.dict(os.environ, {"BATCH_PHASE": "collect"}),
                patch.multiple(
                    parser, CODE356=True, translateAI=extensions.point(queued)
                ),
            ):
                parse(
                    [
                        command(356, ["Tachie showName 村長"]),
                        command(356, ["OriginMenuStatus SetParam param1 攻撃力"]),
                    ]
                )
                parser.translateNoteOmitSpace(
                    {"note": "<LB:村>"},
                    rpgmaker_scope.NOTE_TAGS[1].search("<LB:村>"),
                )
            assert all(isinstance(text, list) for text in payloads) and {
                text[0] for text in payloads
            } == {"村長", "攻撃力", "村"}, payloads
            # Batch runs carry these lists through their saved runtime profile.
            from util.runtime_profile import apply_batch_runtime_profile

            sign = {"name": "sign", "regex": r"SignText (.+)", "spacing": "nbsp"}
            with patch.multiple(
                parser,
                CODE356=False,
                NBSP_356=[],
                CUSTOM_356=[],
                ENABLED_PLUGINS_357=set(),
                ENABLED_PATTERNS_355655=set(),
            ):
                apply_batch_runtime_profile(
                    parser,
                    {
                        "engine": "rpgmakermvmz",
                        "version": 1,
                        "config": {
                            "CODE356": True,
                            "NBSP_356": ["CommonPopup"],
                            "CUSTOM_356": [sign],
                        },
                    },
                )
                assert parser.NBSP_356 == ["CommonPopup"], parser.NBSP_356
                assert parser.CUSTOM_356 == [sign], parser.CUSTOM_356
            # A parser exception fails its file. It used to be masked by an
            # unbound result, or saved and reported as a completed translation.
            data, tokens, error = parser.parseSystem(
                {"gameTitle": "テスト"}, "System.json"
            )
            assert isinstance(error, KeyError), error
            with patch.object(parser, "openFiles", return_value=[data, tokens, error]):
                try:
                    parser.handleMVMZ("System.json", True)
                except KeyError:
                    pass
                else:
                    raise AssertionError("A parser exception was reported as success.")
            # Single-pass choice collection requests a menu once, even when the
            # first visit leaves it untranslated as collect and estimate do.
            menus = []

            def untranslated(text, *_args):
                if text == ["特別な品", "やめる"]:
                    menus.append(text)
                return [list(text), [0, 0]]

            menu = command(102, [["特別な品", "やめる"], 1, 0, 2, 0])
            with patch.multiple(
                parser, CODE102=True, translateAI=extensions.point(untranslated)
            ):
                for generation, visits in ((policy, 1), ({}, 2)):
                    configure_states({"engine": "MVMZ"}, temporary, generation)
                    menus.clear()
                    parse([command(401, ["こんにちは"]), menu])
                    assert len(menus) == visits, (generation, menus)
            # Small event pages of a file share one labelled request; a page
            # of more than 10 entries keeps its own, so no other scene bleeds
            # into a conversation. Choice menus travel with their page in
            # play order. A reply of the wrong length writes nothing of it.
            sent = []

            def answer(text, history, *_args):
                sent.append((list(text), history))
                packed = isinstance(history, dict) and history["instructions"][
                    0
                ].startswith(parser.PACKED_PAGES)
                short = packed and sent_mode == "short"
                return [[f"EN {line}" for line in text][: len(text) - short], [0, 0]]

            def box(text):
                return [name(""), command(401, [text])]

            def choice_menu(*labels):
                return command(102, [list(labels), 1, 0, 2, 0])

            def event(identity, *commands):
                return {"id": identity, "list": [*commands, command(0, [])]}

            def common_events():
                talk = [line for n in range(11) for line in box(f"話{n}")]
                return [
                    None,
                    event(1, *box("やあ")),
                    event(2, *box("看板"), choice_menu("はい", "いいえ")),
                    event(3, *talk[:10], choice_menu("行く", "残る"), *talk[10:]),
                    event(4, *box("さようなら")),
                ]

            talk = [f"話{n}" for n in range(11)]
            expected = [
                (
                    [*talk[:5], "行く", "残る", *talk[5:]],
                    {
                        "instructions": [
                            parser.PAGE_MENUS + "\n- choice menu at lines 6-7"
                        ],
                        "source_items": [],
                    },
                ),
                (
                    ["やあ", "看板", "はい", "いいえ", "さようなら"],
                    {
                        "instructions": [
                            parser.PACKED_PAGES
                            + "\n- common event 1: line 1"
                            + "\n- common event 2: lines 2-4, choice menu at lines 3-4"
                            + "\n- common event 4: line 5"
                        ],
                        "source_items": [],
                    },
                ),
            ]
            with patch.multiple(
                parser, CODE102=True, translateAI=extensions.point(answer)
            ):
                for generation, sent_mode, calls_made in (
                    ({**policy, "pagePacking": PAGE_PACKING}, "", 2),
                    ({**policy, "pagePacking": PAGE_PACKING}, "short", 2),
                    (policy, "", 6),
                ):
                    configure_states({"engine": "MVMZ"}, temporary, generation)
                    sent.clear()
                    data, _tokens, error = parser.parseCommonEvents(
                        common_events(), "CommonEvents.json"
                    )
                    assert error is None and len(sent) == calls_made, sent
                    if calls_made == 2:
                        assert sent == expected, sent
                    packed = sent_mode != "short"
                    assert data[1]["list"][1]["parameters"][0].startswith(
                        "EN" if packed else "やあ"
                    ), data[1]
                    assert data[2]["list"][2]["parameters"][0] == (
                        ["EN はい", "EN いいえ"] if packed else ["はい", "いいえ"]
                    ), data[2]
                    assert data[3]["list"][1]["parameters"][0].startswith("EN"), data[3]
                    assert data[3]["list"][10]["parameters"][0] == [
                        "EN 行く",
                        "EN 残る",
                    ]
                    assert data[4]["list"][1]["parameters"][0].startswith(
                        "EN" if packed else "さようなら"
                    ), data[4]
            configure_states({"engine": "MVMZ"}, temporary, policy)

            # Pass state belongs to each call and thread; a parse error restores it.
            configure_states({"engine": "MVMZ"}, temporary, policy)
            entered, release = threading.Event(), threading.Event()
            seen, errors = [], []
            choice = {"parameters": [["選択"]]}

            def search(page, *_args):
                if page == "waiting":
                    entered.set()
                    assert release.wait(1), "Test synchronization failed"
                    seen.append(parser._choice_current(choice, 0))
                    raise ValueError("Generated parse failure")
                seen.append(parser._choice_current(choice, 0))

            def second_pass():
                try:
                    parser.searchCodes("waiting", None, [[]], "Map001.json")
                except ValueError:
                    seen.append(parser._choice_current(choice, 0))
                except Exception as error:
                    errors.append(error)

            with patch.object(parser, "_searchCodes", search):
                worker = threading.Thread(target=second_pass)
                worker.start()
                try:
                    assert entered.wait(1)
                    parser.searchCodes("other", None, [], "Map002.json")
                finally:
                    release.set()
                    worker.join(1)
            assert not worker.is_alive() and not errors, errors
            assert seen == ["選択", "", "選択"], seen

            # Skill messages say who uses each skill, so a skill only the
            # heroine learns is not translated with "their": an actor learns
            # it through its starting class or a Change Skill command, an
            # enemy uses its actions. Notes number lines within each request,
            # and a line the translator leaves out of requests gets none. When
            # the party can only ever hold her, a skill no enemy uses and a
            # state's message1 are hers too.
            run = temporary / "skill-users"
            (run / "files").mkdir(parents=True)
            (run / "log").mkdir()
            for file, value in {
                "Actors.json": [
                    None,
                    {"id": 1, "name": "アリナ", "classId": 1, "traits": []},
                    # A player-named actor tells the model nothing.
                    {
                        "id": 2,
                        "name": "",
                        "classId": 2,
                        "traits": [{"code": 43, "dataId": 3, "value": 1}],
                    },
                ],
                "Classes.json": [
                    None,
                    {"id": 1, "learnings": [{"skillId": 1}], "traits": []},
                    {"id": 2, "learnings": [], "traits": []},
                ],
                "Enemies.json": [
                    None,
                    {"id": 1, "name": "スライム", "actions": [{"skillId": 2}]},
                ],
                "System.json": {"partyMembers": [1]},
            }.items():
                (run / "files" / file).write_text(
                    json.dumps(value, ensure_ascii=False), encoding="utf-8"
                )
            messages = ["%1は斬りかかった！", "%1は体当たりした！", "%1は祈った！"]
            messages += ["は胸元をはだけた！", "%1!!"]
            skills = [None] + [
                {"id": skill, "name": "", "message1": message}
                for skill, message in enumerate(messages, 1)
            ]
            requests = []

            def events(*commands, folder=run / "files"):
                events = [None, {"pages": [{"list": [*commands, command(0, [])]}]}]
                (folder / "Map001.json").write_text(json.dumps({"events": events}))

            def record(text, history, *_args, glossary_names=()):
                requests.append((list(text), history, glossary_names))
                return [["EN:" + value for value in text], [0, 0]]

            directory = os.getcwd()
            os.chdir(run)
            try:
                with patch.multiple(
                    parser,
                    IGNORETLTEXT=False,
                    translateAI=extensions.point(record),
                    _request_size=lambda: 2,
                ):
                    older = {**policy, "battleMessageUsers": "battle-message-users-v1"}
                    current = {**policy, "battleMessageUsers": BATTLE_MESSAGE_USERS}
                    learned = command(318, [0, 1, 0, 4])
                    # A second actor joining makes the party more than her.
                    joined = command(129, [2, 0, False])
                    for generation, commands, alone in (
                        (older, [learned], False),
                        (current, [learned], True),
                        (current, [learned, joined], False),
                        (policy, [learned], False),
                    ):
                        events(*commands)
                        configure_states({"engine": "MVMZ"}, temporary, generation)
                        parser.resetActorMapCache()
                        requests.clear()
                        translated = deepcopy(skills)
                        parser.searchNames(translated, None, "Skills", "Skills.json")
                        assert translated[2]["message1"] == "EN:%1は体当たりした！"
                        assert translated[5]["message1"] == "EN:%1!!"
                        if generation is policy:
                            # Older runs keep their single request.
                            assert len(requests) == 1, requests
                            assert "gender neutral" in requests[0][1], requests
                            assert "Line1" not in requests[0][1], requests
                            continue
                        texts = [request[0] for request in requests]
                        assert texts == [
                            messages[:2],
                            [messages[2], "Taro" + messages[3]],
                            [messages[4]],
                        ], texts
                        first, second, unsent = requests
                        assert first[1].endswith(
                            "Line1: actor アリナ\nLine2: enemy スライム"
                        ), first
                        assert first[2] == ("アリナ", "スライム"), first
                        # Her party's skill 3 is hers; an enemy's skill stays its.
                        notes = "\nLine1: actor アリナ\nLine2: actor アリナ"
                        if alone:
                            assert second[1].endswith(notes), second
                        else:
                            assert second[1].endswith("\nLine2: actor アリナ"), second
                            assert "Line1" not in second[1], second
                        assert second[2] == ("アリナ",), second
                        assert unsent[1].endswith("Keep the battler gender neutral.")
                        assert unsent[2] == (), unsent
                        requests.clear()
                        parser.searchSS(
                            {"id": 1, "message1": "は幻惑に囚われた！"}, None
                        )
                        ((_text, instruction, names),) = requests
                        assert ("The party is always アリナ" in instruction) == alone
                        assert names == (("アリナ",) if alone else ()), names
            finally:
                os.chdir(directory)
                parser.resetActorMapCache()
        configure_states({"engine": "MVMZ"}, temporary, None)

        # New lines get the QA lint fixes that need no reviewer, keeping codes,
        # line breaks and a dakuten apostrophe; a collect pass's untranslated
        # text stays as it is.
        def shared(text, **_kwargs):
            return [
                ["\\NK[1]Spluuurt……hhh♥♥Thwump♥\nSto'p……h!\\NK[0]", text[1]],
                [0, 0],
            ]

        sources = [
            "\\NK[1]ぶっぷぅ……っっっ♥♥どちゅっ♥\nや゛めて……っ！\\NK[0]",
            "♥Hシーン",
        ]
        with patch.multiple(parser, AUTONAMEPOPUP101=True, sharedtranslateAI=shared):
            output, _tokens = parser.translateAI(sources, "")
        assert output == [
            "\\NK[1]Spluuurt……♥♥ Thwump♥\nSto'p……!\\NK[0]",
            "♥Hシーン",
        ], output
    # A map call can contain a malformed attempt, an accepted retry, a refused
    # chunk, and another success. Keep every body and only its own validation;
    # refusal loops must preserve source without making more provider calls.
    with app.backend.context():
        from unittest.mock import Mock

        # A schema-rejecting API must never cause a second, weaker request.
        # Exercise the real native fallback and the DeepSeek builder exception
        # in this existing offline process, including restoration for old runs.
        import httpx
        from dazedtl.compatibility.request_parameters import configure_builders
        from dazedtl.settings.preferences import GENERATION_PARAMETERS
        from openai import BadRequestError, UnprocessableEntityError
        from util import translation
        from util.batch_providers import (
            PROVIDER_OPENAI,
            detect_batch_provider,
            get_client,
        )

        with patch.dict(
            os.environ,
            {"API_PROVIDER": "openai", "api": "https://openrouter.ai/api/v1"},
        ):
            # A Batch client built without an address takes the run's route,
            # never OpenAI's own address behind it.
            client = get_client(PROVIDER_OPENAI, api_key="fixture-key")
            assert str(client.base_url).startswith("https://openrouter.ai/api/v1")
            for _ in range(2):
                translation.STRICT_STRUCTURED_OUTPUTS = True
                configure_builders(
                    translation,
                    GENERATION_PARAMETERS,
                    structured_outputs=True,
                    openrouter_host="deepinfra",
                )
            for model in (
                "deepseek/fixture",
                "anthropic/claude-fixture",
                "openai/gpt-4.1",
            ):
                params = translation.buildOpenAIRequest(
                    "Translate.", '{"Line1":"薬"}', [], 0, "json", model, numLines=1
                )
                assert params["response_format"]["json_schema"] == {
                    "name": "translation_response",
                    "strict": True,
                    "schema": translation.createTranslationSchema(1),
                }
                assert params["extra_body"]["provider"] == {
                    "only": ["deepinfra"],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                }
            rejected = BadRequestError(
                "Unsupported response format",
                response=httpx.Response(
                    400,
                    request=httpx.Request(
                        "POST", "https://provider.invalid/v1/chat/completions"
                    ),
                ),
                body={"code": "unsupported"},
            )
            good = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"Line1":"Potion"}')
                    )
                ],
                usage=None,
            )
            for error in (rejected, RuntimeError("Invalid schema")):
                send = Mock(side_effect=[error, good])
                with patch.object(
                    translation.openai,
                    "chat",
                    SimpleNamespace(completions=SimpleNamespace(create=send)),
                ):
                    try:
                        translation.translateText(
                            "Translate.",
                            '{"Line1":"薬"}',
                            [],
                            0,
                            "json",
                            "deepseek/fixture",
                            numLines=1,
                        )
                    except type(error) as actual:
                        assert actual is error
                    else:
                        raise AssertionError(
                            "Strict OpenRouter work accepted a schema downgrade."
                        )
                assert send.call_count == 1
            translation.STRICT_STRUCTURED_OUTPUTS = False
            configure_builders(translation, None)
            legacy = translation.buildOpenAIRequest(
                "Translate.", "薬", [], 0, "json", "deepseek/fixture", numLines=1
            )
            assert legacy["response_format"] == {"type": "json_object"}
            assert "provider" not in legacy.get("extra_body", {})

            # A json_schema request's 400 was sent again in JSON mode whatever
            # it said, so under the run-stop policy each rejected request
            # reached the provider twice. There only an error saying the
            # response format falls back, never one echoing the request back;
            # a run frozen before falls back at every 400. A validating
            # server's 422 failed every request instead of using JSON mode.
            def status_error(status, body):
                error = BadRequestError if status == 400 else UnprocessableEntityError
                return error(
                    f"Error code: {status} - {body}",
                    response=httpx.Response(
                        status,
                        request=httpx.Request(
                            "POST", "https://provider.invalid/v1/chat/completions"
                        ),
                    ),
                    body=body,
                )

            unrelated = {"message": "The model `gone` does not exist."}
            unsupported = {
                "message": "Invalid parameter: 'response_format' of type "
                "'json_schema' is not supported with this model."
            }
            echoed = {
                "object": "error",
                "message": "1 validation error for ChatCompletionRequest\n"
                "model\n  Field required [type=missing, input_value={'messages':"
                " [], 'response_format': {'type': 'json_schema'}}, input_type=dict]",
            }
            literal = {
                "detail": [
                    {
                        "type": "literal_error",
                        "loc": ["body", "response_format", "type"],
                        "msg": "Input should be 'text' or 'json_object'",
                        "input": "json_schema",
                    }
                ]
            }
            missing = {
                "detail": [
                    {
                        "type": "missing",
                        "loc": ["body", "model"],
                        "msg": "Field required",
                        "input": {"response_format": {"type": "json_schema"}},
                    }
                ]
            }
            for run_stops, status, body, sent in (
                (True, 400, unrelated, 1),
                (True, 400, unsupported, 2),
                (True, 400, echoed, 1),
                # JSON mode, or no format at all, would be rejected too.
                (True, 400, {"message": "Input should be 'json_schema'"}, 1),
                (False, 400, unrelated, 2),
                (True, 422, literal, 2),
                (False, 422, literal, 2),
                (False, 422, missing, 1),
                # OpenRouter passes on the upstream server's body as text.
                (
                    True,
                    400,
                    {
                        "message": "Provider returned error",
                        "metadata": {"raw": json.dumps(missing)},
                    },
                    1,
                ),
            ):
                send = Mock(side_effect=[status_error(status, body), good])
                with (
                    patch.object(translation, "RUN_STOPS", run_stops),
                    patch.object(
                        translation.openai,
                        "chat",
                        SimpleNamespace(completions=SimpleNamespace(create=send)),
                    ),
                ):
                    try:
                        translation.translateText(
                            "Translate.",
                            '{"Line1":"薬"}',
                            [],
                            0,
                            "json",
                            "openai/gpt-4.1",
                            numLines=1,
                        )
                    except Exception as error:
                        assert sent == 1 and f"({status})" in str(error), error
                    else:
                        assert sent == 2, (run_stops, body)
                assert send.call_count == sent, (run_stops, body, send.call_count)
                assert send.call_args.kwargs["response_format"]["type"] == (
                    "json_object" if sent == 2 else "json_schema"
                )
            # DeepSeek's own models think within max_tokens by default, so a
            # long request gets the full ceiling there and the cap elsewhere.
            for model, endpoint, ceiling in (
                (
                    "deepseek/fixture",
                    None,
                    translation.COMPAT_TRANSLATION_OUTPUT_TOKENS,
                ),
                (
                    "deepseek-flash",
                    "https://api.deepseek.com",
                    translation.MAX_TRANSLATION_OUTPUT_TOKENS,
                ),
            ):
                params = translation.buildOpenAIRequest(
                    "Translate.",
                    "薬" * 9000,
                    [],
                    0,
                    "json",
                    model,
                    numLines=1,
                    api_url=endpoint,
                )
                assert params["max_tokens"] == ceiling, (model, params["max_tokens"])
                assert params["response_format"] == {"type": "json_object"}
        # Namespaced Claude/GPT IDs retain OpenRouter's transport identity;
        # Batch must never use native OpenAI/Anthropic upload endpoints.
        for model in ("anthropic/claude-sonnet-4.5", "openai/gpt-4.1"):
            route = {
                "model": model,
                "API_PROVIDER": "openai",
                "api": "https://openrouter.ai/api/v1",
            }
            app.backend.validate_route(route)
            assert app.backend.provider_defaults(route)["batch_supported"]
            assert (
                detect_batch_provider(
                    model, api_url=route["api"], api_provider="openai"
                )
                == "openrouter"
            )
            params = translation.buildOpenAIRequest(
                "Translate.",
                "薬",
                [],
                0,
                "json",
                model,
                numLines=1,
                api_provider="openai",
                api_url=route["api"],
            )
            assert (
                params["model"] == model
                and "max_tokens" in params
                and "max_completion_tokens" not in params
            )
        from dazedtl.compatibility.request_parameters import configure_builders
        from dazedtl.settings.preferences import GENERATION_PARAMETERS

        configure_builders(translation, GENERATION_PARAMETERS, max_output_tokens=32768)
        from util.batch_providers import _openai_batch_body

        # Guided's builder asks the format rule Assistant-led's payload asks
        # (test_compatibility_contracts): JSON mode only for DeepSeek.
        for protocol, endpoint, model, field, mode in (
            (
                "openai",
                "https://api.openai.com/v1",
                "gpt-6-sol",
                "max_completion_tokens",
                "json_schema",
            ),
            (
                "openai",
                "https://openrouter.ai/api/v1",
                "z-ai/glm-5.3-flash",
                "max_tokens",
                "json_schema",
            ),
            (
                "gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai",
                "gemini-3.8-flash",
                "max_tokens",
                "json_schema",
            ),
            (
                "mistral",
                "https://api.mistral.ai/v1",
                "mistral-medium",
                "max_tokens",
                "json_schema",
            ),
            # Kimi deprecates max_tokens; its Batch requests name the provider.
            (
                "openai",
                "https://api.moonshot.ai/v1",
                "kimi-k3",
                "max_completion_tokens",
                "json_schema",
            ),
            ("kimi", "", "kimi-k2.6", "max_completion_tokens", "json_schema"),
            (
                "openai",
                "https://fixture.invalid/v1",
                "local-model",
                "max_tokens",
                "json_schema",
            ),
            (
                "openai",
                "https://api.deepseek.com",
                "deepseek-flash",
                "max_tokens",
                "json_object",
            ),
        ):
            params = translation.buildOpenAIRequest(
                "Translate.",
                "薬",
                [],
                0,
                "json",
                model,
                numLines=1,
                api_provider=protocol,
                api_url=endpoint,
            )
            assert params[field] == 32768 and "薬" in json.dumps(
                params, ensure_ascii=False
            ), params
            assert params["response_format"]["type"] == mode, (model, params)
            # Gemini's Batch files take JSON mode; the others keep it.
            batch_format = _openai_batch_body(protocol, params)["response_format"]
            assert batch_format == (
                {"type": "json_object"}
                if protocol == "gemini"
                else params["response_format"]
            ), (model, batch_format)
        # Kimi Batches run only K2.6 and K2.7 Code, at 60% of the Live price.
        kimi = {"api_url": "https://api.moonshot.ai/v1", "api_provider": "openai"}
        assert [
            detect_batch_provider(model, **kimi)
            for model in ("kimi-k2.6", "kimi-k2.7-code", "kimi-k3")
        ] == ["kimi", "kimi", None]
        quote = translation.estimateCostComparison(
            1_000_000, 0, "kimi-k2.6", batch_provider="kimi"
        )
        assert abs(quote["batch_cost"] - quote["live_cost"] * 0.6) < 1e-9, quote
        # The real SDK refuses a non-streaming request this large before sending
        # it, which stopped native Anthropic Live runs and Batch collection
        # (names translate live). Guided Live must still see a streamed refusal.
        import anthropic
        import httpx2
        from dazedtl.compatibility.translation import TranslationProvider

        claude_stops = ["end_turn", "refusal"]

        def claude_stream(req):
            body = json.loads(req.content)
            assert body["stream"] and body["max_tokens"] == 32768, body
            return claude_reply(body, '{"Line1": "Potion"}', claude_stops.pop(0))

        def claude_reply(body, text, stop="end_turn"):
            events = (
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "model": body["model"],
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 7, "output_tokens": 0},
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop, "stop_sequence": None},
                    "usage": {"output_tokens": 3},
                },
                {"type": "message_stop"},
            )
            return httpx2.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content="".join(
                    f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                    for event in events
                ),
            )

        native_anthropic = anthropic.Anthropic
        with (
            patch.dict(
                os.environ,
                {
                    "API_PROVIDER": "anthropic",
                    "key": "fixture-key",
                    "api": "https://api.anthropic.com",
                },
            ),
            # translateText configures the shared OpenAI module for every provider.
            patch.multiple(
                translation.openai,
                base_url=translation.openai.base_url,
                api_key=translation.openai.api_key,
            ),
            patch.object(
                anthropic,
                "Anthropic",
                side_effect=lambda **kwargs: native_anthropic(
                    **kwargs,
                    http_client=httpx2.Client(
                        transport=httpx2.MockTransport(claude_stream)
                    ),
                ),
            ),
        ):
            response = translation.translateText(
                "Translate.", "薬", [], 0, "json", "claude-opus-5-5", 1
            )
            provider = TranslationProvider(
                {
                    "protocol": "anthropic",
                    "mode": "translate",
                    "endpoint": "https://api.anthropic.com",
                },
                "fixture-key",
            )
            try:
                guided = provider.live(
                    translation.buildClaudeRequest(
                        "Translate.", "薬", [], "json", "claude-opus-5-5", 1
                    )
                )
            finally:
                provider.client.close()
        assert response.choices[0].message.content == '{"Line1": "Potion"}'
        assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (
            7,
            3,
        )
        assert guided["text"] == '{"Line1": "Potion"}' and guided["refusal"], guided
        assert not claude_stops
        # The names review prices Claude by Claude's own count of the request
        # the names translation then sends, and never counts where the
        # network is blocked.
        from util import claude_tokens
        from util.translation_task import TranslationTask, TranslationTaskCore

        # Every RPG Maker estimate runs its files in one worker; a worker per
        # file took seconds each on Windows for Live-only connections.
        launches = []

        def one_worker(task, files, estimate_only, batch_phase, file_result_callback):
            launches.append((list(files), batch_phase))
            for file in files:
                file_result_callback(file, "[Input: 10][Output: 2]")
            return "Success"

        estimate_task = TranslationTask(
            temporary,
            ("RPG Maker MV/MZ", (".json",), None),
            estimate_only=True,
        )
        with (
            patch.dict(os.environ, {"fileThreads": "4"}),
            patch.object(TranslationTask, "run_module_in_process", one_worker),
        ):
            estimate_task._run_files(["Map001.json", "Map002.json"], True)
        assert launches == [(["Map001.json", "Map002.json"], None)], launches
        assert estimate_task.estimate_summary["input_tokens"] == 20, (
            estimate_task.estimate_summary
        )
        # A file is finished only when its module reports success: a stopped
        # file whose module saved part of its output counted as finished in a
        # Translation run (desktop/backend/manual.py), which Resume skipped.
        results = {
            "a.json": "TOTAL: [Input: 1][Output: 1][Cost: $0.0010][0.1s] ✓",
            "b.json": ("VALIDATION_MISMATCH", "Kept.", "TOTAL: ✓", 1),
            "c.json": "Fail",
            "d.json": "Stopped",
        }
        json_task = TranslationTask(temporary, ("JSON", (".json",), None))
        finished = []
        json_task.file_finished_signal.connect(finished.append)
        with (
            patch.dict(os.environ, {"fileThreads": "1"}),
            patch.object(
                TranslationTask,
                "run_module_in_process",
                lambda _task, name, *_args: results[name],
            ),
        ):
            json_task._run_files(list(results), False)
        assert finished == ["a.json", "b.json"], finished
        # Live translation reuses its workers too; a worker per file took two
        # seconds a file. A file that fails ends its worker without failing the
        # files after it, and chunks that kept their original text count as a
        # worker per file counted them.
        live_root = temporary / "live-workers"
        live_root.mkdir()
        runner = live_root / "runner.py"
        runner.write_text(
            "import json, sys, uuid\n"
            "launches = f'launches-{uuid.uuid4().hex}.txt'\n"
            "for line in sys.stdin:\n"
            "    name = line.strip()\n"
            "    with open(launches, 'a') as f:\n"
            "        f.write(name + '\\n')\n"
            "    if name == 'Map002.json':\n"
            "        print('FILE_ERROR:' + json.dumps({'filename': name, 'error': 'Broken.'}), flush=True)\n"
            "        sys.exit(1)\n"
            "    if name == 'Map004.json':\n"
            "        sys.exit(3)\n"
            "    if name == 'Map003.json':\n"
            "        print('MISMATCH_EVENT:' + name, flush=True)\n"
            "        print('MISMATCH_EVENT:' + name, flush=True)\n"
            "    figures = f'[Input: {int(name[3:6])}][Output: 1][Cost: $0.0100][0.5s]'\n"
            "    if name == 'Map100.json':\n"
            "        figures = '[Input: 0][Output: 0][Cost: $0.0000][0.0s]'\n"
            "    print('FILE_RESULT:' + json.dumps({'filename': name, 'result': f'TOTAL: {figures} ✓', 'mismatch_count': 1}), flush=True)\n",
            encoding="utf-8",
        )
        live_task = TranslationTask(
            live_root, ("RPG Maker MV/MZ", (".json",), None), runner_script=runner
        )
        errors, mismatched, done, logged = [], [], [], []
        live_task.file_error_signal.connect(lambda *args: errors.append(args))
        live_task.file_mismatch_signal.connect(lambda *args: mismatched.append(args))
        live_task.progress_signal.connect(lambda *args: done.append(args[2]))
        live_task.log_signal.connect(logged.append)
        maps = [f"Map00{number}.json" for number in range(1, 6)]
        with patch.dict(os.environ, {"fileThreads": "1"}):
            assert live_task._run_files(maps, False) == "Fail"

        # Each worker records its own files: appends from several processes
        # to one file are not atomic on Windows and can garble its lines, and
        # Windows can give a new worker an ended one's process ID.
        def worker_files():
            return sorted(
                path.read_text().split() for path in live_root.glob("launches-*.txt")
            )

        workers = worker_files()
        assert workers == [
            ["Map001.json", "Map002.json"],
            ["Map003.json", "Map004.json"],
            ["Map005.json"],
        ], workers
        assert done == maps, done
        assert [name for name, _ in errors] == ["Map002.json", "Map004.json"], errors
        assert errors[0][1] == "Broken.", errors
        assert [name for name, _ in mismatched] == ["Map003.json"], mismatched
        assert live_task._run_mismatch_count == 2, live_task._run_mismatch_count
        # The Run log shows what they mean, never the worker's own markers.
        assert not [line for line in logged if "MISMATCH_EVENT" in str(line)], logged
        # Concurrent files share the queue: each file goes to one worker once.
        for path in live_root.glob("launches-*.txt"):
            path.unlink()
        many = [f"Map1{number:02d}.json" for number in range(12)]
        # The run's TOTAL adds up each file's own total from every worker and
        # its names passes, starting from the receipts of the run's earlier
        # attempts; a file read back without usage keeps what the earlier
        # attempt cost, and one that paid again replaces it.
        resumed = TranslationTask(
            live_root,
            ("RPG Maker MV/MZ", (".json",), None),
            runner_script=runner,
            receipts={
                "speakers": {"input": 30, "output": 6, "cost": 0.04, "seconds": 1.5},
                "Map099.json": {"cost": 0.25, "seconds": 1.0},
                "Map100.json": {"input": 50, "output": 5, "cost": 0.5, "seconds": 2},
                "Map101.json": {"input": 7, "output": 7, "cost": 7.0, "seconds": 7},
            },
        )
        resumed._record_names_receipt(20, 4, 0.06121, 0.54)
        with patch.dict(os.environ, {"fileThreads": "3"}):
            total = resumed._run_total(resumed._run_files(many, False))
        assert total == "TOTAL: [Input: 1266][Output: 26][Cost: $0.9612][10.5s] ✓", (
            total
        )
        handed = [name for names in worker_files() for name in names]
        assert sorted(handed) == many, handed
        # A run frozen with the run-stop policy ends at an error every later
        # request would get too, over the workers that each fail a file: one
        # refusal of its thinking effort, or the same model error on 3
        # requests in a row. The files after the stop are never handed, so
        # nothing more is sent; a run frozen before keeps sending one refused
        # request per file. Real workers translate packed maps against a
        # stand-in provider that rejects every request.
        # Each run has its own folder and runs beside the others: their
        # workers, which start one after another within a run, took most of
        # this probe's time when the runs did too.
        from concurrent.futures import ThreadPoolExecutor

        stop_root = temporary / "run-stops"
        stop_maps = {}
        for number in range(1, 5):
            commands = [
                {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
                {
                    "code": 401,
                    "indent": 0,
                    "parameters": [f"村人{number}の話を聞いてくれ。"],
                },
                {"code": 0, "indent": 0, "parameters": []},
            ]
            stop_event = {
                "id": 1,
                "name": "EV001",
                "x": 1,
                "y": 1,
                "note": "",
                "pages": [{"list": commands}],
            }
            stop_maps[f"Map00{number}.json"] = json.dumps(
                {"displayName": "", "events": [None, stop_event]},
                ensure_ascii=False,
            )
        texts = ["Text1.json", "Text2.json"]
        stop_texts = {}
        for number, text_file in enumerate(texts, 1):
            stop_texts[text_file] = json.dumps(
                {f"村人{number}の話を聞いてくれ。": "TODO"}, ensure_ascii=False
            )
        # The stand-in rejects requests as the provider's SDK does, without
        # importing the SDK, which took most of each worker's start-up: the
        # engine must read its error exactly as it reads the SDK's own.
        from runpy import run_path

        from dazedtl.compatibility.provider_responses import error_evidence

        stop_root.mkdir()
        (stop_root / "stand_in.py").write_text(
            "class Rejected(Exception):\n"
            "    status_code = 400\n"
            "    def __init__(self, message):\n"
            "        super().__init__(message)\n"
            "        self.body = {'message': message, 'code': None}\n"
            "def reject(error):\n"
            "    '''Raises *error* as util/translation.py raises the SDK's again.'''\n"
            "    try:\n"
            "        raise error\n"
            "    except Exception as provider_error:\n"
            "        raise Exception(f'API status error (400): {provider_error}')\n",
            encoding="utf-8",
        )
        rejecting = run_path(str(stop_root / "stand_in.py"))
        stand_in_messages = {
            "effort": "Unsupported value: 'reasoning_effort' does not support 'high'.",
            "model": "The model `gone` does not exist.",
        }
        for message in stand_in_messages.values():
            sdk_error = BadRequestError(
                message,
                response=httpx2.Response(
                    400,
                    request=httpx2.Request(
                        "POST", "https://stand-in.test/v1/chat/completions"
                    ),
                ),
                body={"message": message, "code": None},
            )
            raised = []
            for error in (rejecting["Rejected"](message), sdk_error):
                try:
                    rejecting["reject"](error)
                except Exception as engine_error:
                    raised.append(engine_error)
            assert str(raised[0]) == str(raised[1]), raised
            assert error_evidence(raised[0]) == error_evidence(raised[1]), raised
        stop_runner = stop_root / "runner.py"
        stop_runner.write_text(
            "import json, socket, sys, time\n"
            f"sys.path[:0] = {json.dumps([str(ENGINE_ROOT), str(root / 'backend')])}\n"
            "def offline(*_args, **_kwargs):\n"
            "    raise RuntimeError('No network in the run-stop workers.')\n"
            "socket.create_connection = socket.socket.connect = socket.socket.connect_ex = offline\n"
            "time.sleep = lambda _seconds: None\n"
            "from functools import partial\n"
            "from pathlib import Path\n"
            "from runpy import run_path\n"
            "rejecting = run_path(str(Path(__file__).with_name('stand_in.py')))\n"
            "from util import translation\n"
            "from dazedtl.compatibility import request_parameters, run_stops\n"
            "from dazedtl.settings.preferences import RUN_STOPS\n"
            "folder = Path(sys.argv[1])\n"
            "stand_in = json.loads((folder / 'stand-in.json').read_text())\n"
            "refused = stand_in['refuses']\n"
            "def provider(_native, *_args, **_kwargs):\n"
            "    with open(folder / 'sent.txt', 'a') as sent:\n"
            "        sent.write('sent\\n')\n"
            "    if stand_in['pays'] and len((folder / 'sent.txt').read_text().split()) == 1:\n"
            "        import openai\n"
            "        return openai.types.chat.ChatCompletion.model_validate({'id': 'paid', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-stand-in', 'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}'}}], 'usage': {'prompt_tokens': 11, 'completion_tokens': 3, 'total_tokens': 14}})\n"
            f"    message = {stand_in_messages!r}[refused]\n"
            "    rejecting['reject'](rejecting['Rejected'](message))\n"
            "translation.translateText.layer('stand-in', provider)\n"
            "translation.translateText.layer('request-parameters', partial(request_parameters.refusal, translation, 'high', None))\n"
            "policy = {'runStops': RUN_STOPS} if stand_in['policy'] == '1' else None\n"
            "run_stops.configure(translation, policy, folder)\n"
            "from modules import rpgmakermvmz\n"
            "rpgmakermvmz.PAGE_PACKING = True\n"
            "from util.subprocess_runner import file_arguments, run_handler\n"
            "run_handler(str(folder), sys.argv[2], file_arguments(sys.argv[3]), sys.argv[4] == 'True')\n",
            encoding="utf-8",
        )
        from dazedtl.settings.effort import rejection

        refused_effort = rejection("gpt-stand-in", "high")
        stop_environment = {
            "api": "https://stand-in.test/v1",
            "key": "stand-in-key",
            "model": "gpt-stand-in",
            "API_PROVIDER": "openai",
            "language": "English",
            "timeout": "10",
            "width": "60",
            "faceWidth": "50",
            "listWidth": "40",
            "noteWidth": "30",
            "messageRows": "4",
            "fileThreads": "1",
            "threads": "1",
        }

        def stop_run(name, module, refusal, policy, selected, pays=False):
            """One run's task and what it handed, sent, logged and wrote."""
            folder = stop_root / name
            (folder / "files").mkdir(parents=True)
            (folder / "translated").mkdir()
            game = stop_maps | (stop_texts if module == "JSON" else {})
            for file_name, text in game.items():
                (folder / "files" / file_name).write_text(text, encoding="utf-8")
            (folder / "stand-in.json").write_text(
                json.dumps({"refuses": refusal, "policy": policy, "pays": pays}),
                encoding="utf-8",
            )
            task = TranslationTask(
                folder, (module, (".json",), None), runner_script=stop_runner
            )
            errors, handed, logged = [], [], []
            task.file_error_signal.connect(lambda *args: errors.append(args))
            task.progress_signal.connect(lambda *args: handed.append(args[2]))
            task.log_signal.connect(logged.append)
            result = task._run_files(selected, False)
            requests = (folder / "sent.txt").read_text(encoding="utf-8").split()
            written = sorted(
                path.name for path in (folder / "translated").glob("Text*.json")
            )
            return task, result, errors, handed, logged, requests, written

        maps = [f"Map00{number}.json" for number in range(1, 5)]
        from dazedtl.compatibility.process_view import file_receipt

        mvmz_runs = (
            ("effort", "1", maps[:2], maps[:1], refused_effort),
            ("effort", "0", maps[:2], maps[:2], None),
            ("model", "1", maps, maps[:3], True),
        )
        # Under the policy the stand-in answers the first request, which the
        # file pays for before the stop leaves its handler: its receipt keeps
        # it, read from its log line by the run's records and from its result
        # by the run's TOTAL.
        text_runs = (("1", 2), ("0", 2))
        with (
            patch.dict(os.environ, stop_environment),
            ThreadPoolExecutor(len(mvmz_runs) + len(text_runs)) as runs,
        ):
            mvmz_futures = [
                runs.submit(
                    stop_run,
                    f"mvmz-{number}",
                    "RPG Maker MV/MZ",
                    *run[:3],
                    run[4] is None,
                )
                for number, run in enumerate(mvmz_runs)
            ]
            text_futures = [
                runs.submit(
                    stop_run,
                    f"text-{policy}",
                    "JSON",
                    "effort",
                    policy,
                    texts,
                    policy == "1",
                )
                for policy, _ in text_runs
            ]
        for (refusal, policy, selected, files, stopped), future in zip(
            mvmz_runs, mvmz_futures
        ):
            stop_task, result, errors, handed, logged, requests, _ = future.result()
            case = (refusal, policy, errors)
            assert result == "Fail", (case, result)
            assert handed == files, (case, handed)
            # One request per file until the stop, and the paid one before.
            assert len(requests) == len(files) + (stopped is None), (case, requests)
            assert [name for name, _ in errors] == files, case
            if stopped is None:
                # The refusal fails each file alone, as when the run was
                # approved. The stand-in answers the first file's first
                # request, which that file paid for before it failed: its
                # receipt keeps it, in the run's records and its TOTAL.
                assert {error for _, error in errors} == {refused_effort}, case
                assert stop_task.run_stop is None, case
                paid = stop_task.receipts["Map001.json"]
                assert (paid["input"], paid["output"]) == (11, 3), paid
                assert [
                    receipt
                    for receipt in (file_receipt(line, files) for line in logged)
                    if receipt
                ] == [("Map001.json", paid)], logged
            elif stopped is True:
                # The two rejections before the stop failed their own files.
                # They read as the provider's own error, which the run's
                # message names, not the SDK's and the engine's wrapping.
                assert errors[0][1] == (
                    "The provider rejected the request: HTTP 400 - The model "
                    "`gone` does not exist."
                ), case
                assert errors[0][1] == errors[1][1], case
                assert errors[2][1].startswith(
                    "The provider rejected 3 requests in a row with the same error"
                ), case
                assert stop_task.run_stop == errors[2][1], case
                # The Run log reads each request's error once, and each
                # failed file's once more: the worker's closing ERROR marker
                # and a second copy through its progress bar repeated them.
                kinds = [
                    line.split(" ", 1)[0] for line in logged if "does not exist" in line
                ]
                assert kinds == ["[API_ERROR]", "❌"] * 2 + ["[API_ERROR]"], logged
            else:
                assert errors == [("Map001.json", stopped)], case
                assert stop_task.run_stop == stopped, case
        # Outside RPG Maker the stop leaves the module's parse and file
        # handlers too, so the stopped file fails instead of being written
        # out as finished; a run frozen before the policy goes on, each
        # refused file failing alone as RPG Maker's do, where it was written
        # untranslated and read translated. A file the per-file executor
        # started before the stop meets it without sending.
        for (policy, sends), future in zip(text_runs, text_futures):
            stop_task, result, errors, handed, logged, requests, written = (
                future.result()
            )
            case = (policy, result, errors)
            assert handed == texts[: len(handed)], (case, handed)
            assert len(requests) == sends, (case, requests)
            if policy == "1":
                assert result == "Fail", case
                assert errors[0] == ("Text1.json", refused_effort), case
                assert errors == [(name, refused_effort) for name in handed], case
                assert stop_task.run_stop == refused_effort, case
                assert written == [], (case, written)
                paid = stop_task.receipts["Text1.json"]
                assert (paid["input"], paid["output"]) == (11, 3), paid
                assert [
                    receipt
                    for receipt in (file_receipt(line, texts) for line in logged)
                    if receipt
                ] == [("Text1.json", paid)], logged
            else:
                assert result == "Fail", case
                assert handed == texts, case
                assert errors == [(name, refused_effort) for name in texts], case
                assert stop_task.run_stop is None, case
                assert written == [], (case, written)
        # That worker saves a Batch's files one after another; a file missing
        # a result must not keep the files after it from saving theirs. Each
        # file reports only its own exact cost, which the run's TOTAL adds up.
        from util import subprocess_runner, translation_task

        # A failed worker's error is its closing ERROR line, which the Run log
        # leaves out, not its traceback's first line, the first of chained
        # errors.
        rejected = "The provider rejected the request: HTTP 400 - No."
        assert (
            translation_task._process_error(
                "Traceback (most recent call last):\n"
                "Exception: API call failed: Error code: 400\n"
                f"util.translation.RequestRejectedError: {rejected}",
                ["[API_ERROR] " + rejected, "ERROR:" + rejected],
            )
            == rejected
        )

        def consume(name, _estimate):
            translation._add_paid(5, 2, 0.25)
            if name == "Map001.json":
                raise translation.BatchResultUnavailableError("Missing.")
            if name == "Map003.json":
                raise translation_task.OutputNotSaved(name, OSError("Disk full."))
            return str(translation._global_accurate_cost)

        reported = StringIO()
        with (
            patch.dict(os.environ, {"BATCH_PHASE": "consume"}),
            patch.object(
                translation_task, "translation_module", lambda _: (0, 0, consume)
            ),
            redirect_stdout(reported),
        ):
            subprocess_runner.run_handler(
                temporary,
                "RPG Maker MV/MZ",
                ["Map001.json", "Map003.json", "Map002.json"],
                False,
            )
        reports = [
            (kind, json.loads(value))
            for kind, _, value in (
                line.partition(":") for line in reported.getvalue().splitlines()
            )
            if kind in {"FILE_ERROR", "FILE_RESULT"}
        ]
        assert [(kind, report["filename"]) for kind, report in reports] == [
            ("FILE_ERROR", "Map001.json"),
            ("FILE_ERROR", "Map003.json"),
            ("FILE_RESULT", "Map002.json"),
        ], reported.getvalue()
        assert reports[2][1]["result"] == "0.25", reports
        # A map whose final save failed returned a bare "Fail", so the run
        # read "Translation failed" without the error; it fails with it now,
        # still only its own file.
        assert reports[1][1]["error"] == "Map003.json could not be saved: Disk full."
        # The file that failed keeps the results it paid for on its receipt,
        # logged as its line and sent with its error for the run's TOTAL.
        receipt = reports[0][1]["receipt"]
        assert receipt in reported.getvalue().splitlines(), reported.getvalue()
        failed = translation_task.file_marker_result(*reports[0])
        assert failed == ("SUBPROCESS_ERROR", "Missing.", receipt), failed
        figures = translation_task._result_figures(failed)
        assert (figures["input"], figures["output"], figures["cost"]) == (5, 2, 0.25)

        # So does a file a module failed in a worker given that one file,
        # whose exit reports the failure.
        def failing(_name, _estimate):
            translation._add_paid(7, 1, 0.5)
            return "Fail"

        reported = StringIO()
        with (
            patch.object(
                translation_task, "translation_module", lambda _: (0, 0, failing)
            ),
            redirect_stdout(reported),
        ):
            subprocess_runner.run_handler(temporary, "JSON", "Text1.json", False)
        marker = next(
            line
            for line in reported.getvalue().splitlines()
            if line.startswith("FILE_RESULT:")
        )
        failed = translation_task.file_marker_result(
            "FILE_RESULT", json.loads(marker.partition(":")[2])
        )
        assert failed[0] == "FAILED", reported.getvalue()
        figures = translation_task._result_figures(failed)
        assert (figures["input"], figures["output"], figures["cost"]) == (7, 1, 0.5)
        assert reported.getvalue().splitlines()[-1] == "RESULT:Fail"
        # A module that caught the run's stop still ends it, and what its file
        # cost before the stop reaches the run's receipts.
        spent = "TOTAL: [Input: 5][Output: 2][Cost: $0.0100][0.5s] ✓"

        def caught(_name, _estimate):
            translation._run_stops.append("Stopped.")
            return spent

        reported = StringIO()
        with (
            patch.object(translation, "RUN_STOPS", True),
            patch.object(translation, "_run_stops", []),
            patch.object(
                translation_task, "translation_module", lambda _: (0, 0, caught)
            ),
            redirect_stdout(reported),
        ):
            subprocess_runner.run_handler(
                temporary,
                "RPG Maker MV/MZ",
                iter(["Map001.json", "Map002.json"]),
                False,
            )
        stops = [
            json.loads(value)
            for kind, _, value in (
                line.partition(":") for line in reported.getvalue().splitlines()
            )
            if kind in {"FILE_ERROR", "FILE_RESULT", "RUN_STOPPED"}
        ]
        assert stops == [
            {"filename": "Map001.json", "error": "Stopped.", "result": spent}
        ], reported.getvalue()
        assert translation_task._result_figures(("RUN_STOPPED", "Stopped.", spent)) == {
            "input": 5,
            "output": 2,
            "cost": 0.01,
            "seconds": 0.5,
        }

        names_root = temporary / "names"
        names_root.mkdir()
        os.chdir(names_root)
        claude_bodies = []

        def claude_names(req):
            body = json.loads(req.content)
            claude_bodies.append(body)
            if req.url.path.endswith("/count_tokens"):
                return httpx2.Response(
                    200, json={"input_tokens": len(json.dumps(body))}
                )
            lines = re.findall(r'"(Line\d+)"', body["messages"][-1]["content"])
            return claude_reply(body, json.dumps(dict.fromkeys(lines, "Elder")))

        names = ["村長", "宿屋の主人"]
        names_config = translation.TranslationConfig(
            model="claude-opus-5-5",
            prompt="Translate the supplied text.",
            vocab="",
            batchSize=30,
            useSfxReference=False,
        )
        with (
            patch.dict(
                os.environ,
                {
                    "API_PROVIDER": "anthropic",
                    "key": "fixture-key",
                    "api": "https://api.anthropic.com",
                },
            ),
            patch.multiple(
                translation.openai,
                base_url=translation.openai.base_url,
                api_key=translation.openai.api_key,
            ),
            patch.object(
                anthropic,
                "Anthropic",
                side_effect=lambda **kwargs: native_anthropic(
                    **kwargs,
                    http_client=httpx2.Client(
                        transport=httpx2.MockTransport(claude_names)
                    ),
                ),
            ),
            patch.object(
                claude_tokens,
                "http_client",
                lambda timeout: httpx2.Client(
                    transport=httpx2.MockTransport(claude_names)
                ),
            ),
        ):
            estimate = TranslationTaskCore._estimate_grouped_speakers(
                names, "Name each speaker.", names_config, names_config.model
            )
            assert estimate["approximate_input"] and not claude_bodies, estimate
            del os.environ["DAZEDTL_TEST_OFFLINE"]
            estimate = TranslationTaskCore._estimate_grouped_speakers(
                names, "Name each speaker.", names_config, names_config.model
            )
            counts = list(claude_bodies)
            claude_bodies.clear()
            output = translation.translateAI(names, "Name each speaker.", names_config)
        assert output[0] == ["Elder", "Elder"], output
        assert not estimate["approximate_input"], estimate
        [sent] = claude_bodies
        sent = {
            key: value
            for key, value in sent.items()
            if key not in {"max_tokens", "stream"}
        }
        # The cached prefix alone and the whole request, counted in parallel.
        assert len(counts) == 2 and sent in counts, (counts, sent)
        assert estimate["input_tokens"] == len(json.dumps(sent)), estimate
        configure_builders(translation, None)
        # Real native collect -> submit -> fetch -> consume must reach the
        # installed inline adapter, including aliases already bound by history.
        # Reuse this offline process instead of paying another startup cost.
        import httpx
        from dazedtl.compatibility import openrouter_batch, openrouter_pricing
        from dazedtl.compatibility.batch_evidence import (
            install as retain_batch_evidence,
        )
        from dazedtl.compatibility.process_view import payload, request_view
        from dazedtl.compatibility.request_parameters import batch_routing
        from dazedtl.compatibility.request_scope import identities
        from dazedtl.compatibility.run_evidence import Evidence
        from dazedtl.settings.openrouter import STRUCTURED_OUTPUTS, TRANSPORT
        from util import batch_history, batch_providers, extensions

        router_root = temporary / "router-batch"
        router_root.mkdir()
        os.chdir(router_root)
        router_model = "google/fixture"
        router_policy = {
            "transport": TRANSPORT,
            "model": router_model,
            "host": "",
            "input": 0.8,
            "output": 3,
            "structuredOutputs": STRUCTURED_OUTPUTS,
            "providers": ["google-vertex"],
            "cache_read": 0.2,
            "cache_write": None,
            "max_requests": 1000,
            "max_bytes": 10_000_000,
        }
        sent_batches = []

        def router_response(req):
            if req.method == "POST" and req.url.path == "/api/v1/batches":
                sent_batches.append(json.loads(req.content))
                assert all(
                    row["body"]["max_tokens"] == 32768
                    for row in sent_batches[-1]["requests"]
                )
                assert sent_batches[-1]["provider"] == {"only": ["google-vertex"]}
                return httpx.Response(
                    202,
                    json={
                        "id": f"paid-router-{len(sent_batches)}",
                        "status": "validating",
                    },
                )
            assert req.method == "GET" and req.url.path.startswith(
                "/api/v1/batches/paid-router-"
            ), req.url
            identity = req.url.path.rsplit("/", 1)[-1]
            rows = sent_batches[int(identity.rsplit("-", 1)[-1]) - 1]["requests"]
            return httpx.Response(
                200,
                json={
                    "id": identity,
                    "status": "completed",
                    "request_counts": {
                        "total": len(rows),
                        "completed": len(rows),
                        "failed": 0,
                    },
                    "usage": {"cost": 0.001},
                    "results": [
                        {
                            "custom_id": row["custom_id"],
                            "response": {
                                "status_code": 200,
                                "body": {
                                    "choices": [
                                        {
                                            "message": {
                                                "content": json.dumps(
                                                    {
                                                        key: "Potion"
                                                        if required == ["Line1"]
                                                        else ""
                                                        for required in [
                                                            row["body"][
                                                                "response_format"
                                                            ]["json_schema"]["schema"][
                                                                "required"
                                                            ]
                                                        ]
                                                        for key in required
                                                    }
                                                )
                                            }
                                        }
                                    ],
                                    "usage": {
                                        "prompt_tokens": 10,
                                        "completion_tokens": 4,
                                        "prompt_tokens_details": {"cached_tokens": 2},
                                    },
                                },
                            },
                        }
                        for row in rows
                    ],
                },
            )

        original_http = httpx.Client
        with (
            patch.dict(
                os.environ,
                {
                    "API_PROVIDER": "openai",
                    "key": "fixture-key",
                    "api": openrouter_batch.BASE_URL,
                    "model": router_model,
                },
            ),
            patch.multiple(
                openrouter_batch,
                _worker_policy=router_policy,
                _worker_root=router_root,
                _worker_configured=True,
            ),
            patch.object(
                httpx,
                "Client",
                side_effect=lambda **kwargs: original_http(
                    **{**kwargs, "transport": httpx.MockTransport(router_response)}
                ),
            ),
            patch.multiple(
                translation,
                _batch_results=None,
                _batch_queue_pending={},
                _global_accurate_cost=0,
                getPricingConfig=lambda *_: {
                    "inputAPICost": 2,
                    "outputAPICost": 8,
                    "batchSize": 2,
                    "frequencyPenalty": 0,
                },
            ),
            # Restores the host layers this journey adds to the engine.
            patch.dict(extensions._layers),
        ):
            openrouter_pricing.configure(translation, router_policy)
            translation.STRICT_STRUCTURED_OUTPUTS = True
            batch_evidence = Evidence(router_root, "batch")
            batch_evidence.install(translation)
            retain_batch_evidence(translation, router_root, {"mode": "batch"})
            configure_builders(
                translation,
                GENERATION_PARAMETERS,
                batch_evidence.record,
                max_output_tokens=32768,
                structured_outputs=True,
                batch=True,
                openrouter_batch=router_policy,
            )
            config = translation.TranslationConfig(
                model=router_model,
                prompt="Translate the supplied text.",
                vocab="",
                batchSize=2,
                useSfxReference=False,
                logFilePath=str(router_root / "log/translation.txt"),
                mismatchLogPath=str(router_root / "log/mismatches.txt"),
            )
            translation.set_batch_phase("collect")
            # Each request records its own lines' identities, and their files
            # when a call gathers several files' lines as the grouped map
            # display names do, also after a line without Japanese stayed out
            # of an earlier request.
            with (
                patch.object(translation, "_batch_queue_pending", {}),
                patch.object(translation, "flush_batch_queue", lambda: None),
            ):
                names = ["村", "Town", "神殿", "塔"]
                translation.translateAI(
                    names,
                    [],
                    config,
                    filename="Map001.json",
                    line_files=[
                        ["Map001.json"],
                        ["Map002.json"],
                        ["Map003.json", "Map004.json"],
                        ["Map005.json"],
                    ],
                )
                queued_names = translation._batch_queue_pending.values()
                keys = identities("Map001.json", None, names)
                assert [
                    (entry["dazedtl_sources"], entry["dazedtl_line_files"])
                    for entry in queued_names
                ] == [
                    ([keys[0]], [["Map001.json"]]),
                    (keys[2:], [["Map003.json", "Map004.json"], ["Map005.json"]]),
                ], queued_names
            translation.translateAI(["薬"], [], config, filename="Items.json")
            translation.translateAI(["回復", "毒"], [], config, filename="Items.json")
            # Another file asking alike shares the request, queued once; its
            # own queue fragment still names the file.
            translation.translateAI(["回復", "毒"], [], config, filename="Weapons.json")
            collected = translation._read_batch_queue()
            assert [entry.get("dazedtl_files") for entry in collected.values()] == [
                None,
                ["Items.json", "Weapons.json"],
            ], collected
            assert set(request_view(router_root, {})["files"]) == {
                "Items.json",
                "Weapons.json",
            }
            estimate = translation.estimateBatchCost()
            assert estimate["provider"] == "openrouter", estimate
            assert (
                abs(
                    estimate["batch_nocache_cost"]
                    - (estimate["input_tokens"] * 0.8 + estimate["output_tokens"] * 3)
                    / 1_000_000
                )
                < 1e-12
            ), estimate
            assert translation.submitTranslationBatches(["Items.json"], estimate) == [
                "paid-router-1",
                "paid-router-2",
            ]
            assert [len(batch["requests"]) for batch in sent_batches] == [1, 1]
            assert [
                len(
                    batch["requests"][0]["body"]["response_format"]["json_schema"][
                        "schema"
                    ]["required"]
                )
                for batch in sent_batches
            ] == [1, 2]
            assert translation.checkTranslationBatchStatuses(False)[0]
            assert translation.fetchTranslationBatches() == (2, 0)
            translation.set_batch_phase("consume")
            translation.begin_file_cost_tracking(config.model)
            translated = translation.translateAI(
                ["薬"], [], config, filename="Items.json"
            )
            assert translated[0] == ["Potion"], translated
            # The file's line and the run's TOTAL take the policy's rates alike.
            for priced in (
                parser.calculateCost(10, 4, config.model),
                translation.priced_cost(),
            ):
                assert abs(priced - (8 * 0.8 + 2 * 0.2 + 4 * 3) / 1_000_000) < 1e-12, (
                    priced
                )
            # Schema-shaped responses can fail native content validation without
            # being refusals; here every line comes back empty. Retain the failed body and generic outcome before
            # the file finishes, even when human-readable logs are unavailable.
            # A call gathering several files' lines, as the grouped map display
            # names do, reports the rejection for those files, not its caller.
            mismatches = []
            failed_output = translation.translateAI(
                ["回復", "毒"],
                [],
                config,
                filename="Items.json",
                mismatchList=mismatches,
                line_files=[["Map002.json"], ["Map003.json", "Map004.json"]],
            )
            assert failed_output[0] == ["回復", "毒"], failed_output
            assert mismatches == ["Map002.json", "Map003.json", "Map004.json"], (
                mismatches
            )
            # The file sharing the request records the outcome last, and the
            # rejection still counts in both of them.
            translation.translateAI(["回復", "毒"], [], config, filename="Weapons.json")
            (router_root / "log/translation.txt").unlink()
            (router_root / "log/mismatches.txt").unlink()
            batch_rows = [payload(router_root, index) for index in range(2)]
            assert [row["state"] for row in batch_rows] == ["validated", "rejected"], (
                batch_rows
            )
            assert {
                name: entry["states"]
                for name, entry in request_view(router_root, {})["files"].items()
            } == {
                "Items.json": ["validated", "rejected"],
                "Weapons.json": ["rejected"],
            }
            assert json.loads(batch_rows[1]["response"]["text"]) == {
                "Line1": "",
                "Line2": "",
            }
            assert batch_rows[1]["error"]["code"] == "validation_failed", batch_rows[1]
            assert len(sent_batches) == 2
            # A miss tells a request the Batch never sent from one it sent
            # without a result, as a canceled Batch leaves; neither goes Live.
            for source, results, cause in (
                (["盾"], translation._batch_results, "changed"),
                (["回復", "毒"], {}, "unreturned"),
            ):
                with patch.object(translation, "_batch_results", results):
                    try:
                        translation.translateAI(
                            source, [], config, filename="Items.json"
                        )
                    except translation.BatchResultUnavailableError as error:
                        assert error.cause == cause, (source, error.cause)
                    else:
                        raise AssertionError(f"No Batch result for {source}.")
            # A request the provider ended with an error says why, not that
            # it may have been canceled, as the fetch kept the error.
            submitted = batch_history.submitted_results()
            stored = "{'code': 'invalid_request', 'message': 'Model is gone'}"
            with (
                patch.object(translation, "_batch_results", {}),
                patch.object(
                    batch_history,
                    "submitted_results",
                    lambda: {key: stored for key in submitted},
                ),
            ):
                try:
                    translation.translateAI(
                        ["回復", "毒"], [], config, filename="Items.json"
                    )
                except translation.BatchResultUnavailableError as error:
                    assert (error.cause, str(error).split(" No full-price")[0]) == (
                        "unreturned",
                        (
                            "The provider ended the Batch request for some of "
                            "this file's lines with an error: Model is gone."
                        ),
                    ), str(error)
                else:
                    raise AssertionError("No Batch result for the ended request.")
            assert len(sent_batches) == 2
            translation.set_batch_phase(None)
            # The run's new speaker names go out Live before any Batch phase;
            # OpenRouter's Live route refuses the Batch endpoint pin.
            names = translation.buildOpenAIRequest(
                "Translate.", "村長", [], 0, "json", router_model, 1
            )
            assert names["extra_body"]["provider"] == {"require_parameters": True}, (
                names
            )
            openrouter_pricing.configure(translation, None)
            configure_builders(translation, None)
            translation.STRICT_STRUCTURED_OUTPUTS = False
            from dazedtl.compatibility.translation import TranslationProvider

            compiled_root = router_root / "compiled"
            compiled_root.mkdir()
            provider = TranslationProvider(
                {
                    "provider": "openrouter",
                    "protocol": "openai",
                    "mode": "batch",
                    "endpoint": openrouter_batch.BASE_URL,
                    "model": router_model,
                    "openrouterBatch": router_policy,
                },
                "fixture-key",
                receipt_root=compiled_root,
            )
            try:
                assert provider.provider == "openrouter"
                assert (
                    provider.submit(
                        [
                            {
                                "custom_id": "dtl-compiled",
                                "params": batch_routing(
                                    sent_batches[0]["requests"][0]["body"],
                                    router_policy,
                                ),
                            }
                        ]
                    )["id"]
                    == "paid-router-3"
                )
                assert provider.status("paid-router-3")["ended"]
                received, errors, usage = provider.collect(
                    "paid-router-3", {"dtl-compiled": "compiled-request"}
                )
                assert not errors and json.loads(
                    received["compiled-request"]["text"]
                ) == {"Line1": "Potion"}
                assert usage["openrouter_cost"] == 0.001 and len(sent_batches) == 3
            finally:
                provider.client.close()
        from dazedtl.compatibility.process_view import (
            payload,
            request_view,
            source_values,
            summary,
        )
        from dazedtl.compatibility.request_parameters import configure_builders
        from dazedtl.compatibility.run_evidence import Evidence
        from dazedtl.settings.preferences import GENERATION_PARAMETERS

        # Requests skip glossary entries none of whose texts they contain; an
        # entry matched any other way must still reach the request.
        glossary = """# Game Characters
ネーナ エヴァンス (Nena Evans)
ニーナ / ミーナ・ルウ (Nina)
ユウ (Yuu)
# Items
▼ポーション (▼Potion)
# Terms
攻撃、アタック (Attack)
魔法 (Magic)
剣 (Sword)"""
        expected = {
            "[ネーナ]: こんにちは": ["ネーナ エヴァンス (Nena Evans)"],
            "ミーナ・ルウが来た": ["ニーナ / ミーナ・ルウ (Nina)"],
            "ユウイベント": ["ユウ (Yuu)"],
            "ポーションを飲む": ["ポーション (Potion)"],
            "アタック！": ["攻撃、アタック (Attack)"],
            "Magic power": ["魔法 (Magic)"],
            "盾": [],
        }
        pairs = translation.parseVocabWithCategories(glossary)
        for text, lines in expected.items():
            matched = translation.buildMatchedVocabText(pairs, text)
            found = [
                line
                for line in glossary.splitlines() + ["ポーション (Potion)"]
                if f"\n{line}\n" in matched + "\n" and not line.startswith("#")
            ]
            assert found == lines, (text, matched)
        # MV/MZ counts U+3007 as Japanese, so English keeping the source's 〇
        # censor mask was retried and then left untranslated. A mask the
        # author did not write still fails.
        # A kaomoji the source has, such as (ﾟдﾟ) or ヽ(・∀・)ﾉ, is no
        # Japanese left either; a kanji is, even one the source has. A line
        # given back unchanged, such as the interjection え？, kept no symbol:
        # it is untranslated, so it is sent again and not saved for reuse.
        assert translation.validate_translation_content(
            [
                "うん〇だ！",
                "うんこだ！",
                "な、何だ(ﾟдﾟ)",
                "やった ヽ(・∀・)ﾉ",
                "剣だ",
                "え？",
            ],
            ["Sh〇t!", "Sh〇t!", "W-what?! (ﾟдﾟ)", "Yay ヽ(・∀・)ﾉ", "The 剣", "え?"],
            parser.LANGREGEX,
            "English",
        )[1] == [1, 4, 5]
        # Placeholders are no text: a reply collapsed to them and a mark was
        # long enough to pass as a translation.
        assert translation.validate_translation_content(
            ["__PROTECTED_0__今日はとても良い天気ですね。__PROTECTED_1__"],
            ["__PROTECTED_0__.__PROTECTED_1__"],
            parser.LANGREGEX,
            "English",
        )[1] == [0]
        # Half-width kana words reach the model full-width, but a kaomoji's
        # lone kana and marks stay as the game wrote them: NFKC turned a lone
        # ﾟ into a combining mark, which the model echoed into the game.
        assert translation.protect_script_codes("ｷﾀ━(ﾉﾟ∀ﾟ)ﾉ ｢ﾜｰｲ｣(･ω･)")[0] == (
            "キタ━(ﾉﾟ∀ﾟ)ﾉ 「ワーイ」(･ω･)"
        )
        live_root = temporary / "live"
        live_root.mkdir()
        os.chdir(live_root)
        evidence = Evidence(live_root, "translate")
        sent = []
        contexts = []
        bodies = [
            "malformed provider JSON",
            '{"translations":["Potion"]}',
            '{"translations":["I cannot translate explicit sexual content."]}',
            '{"translations":["Heal"]}',
        ]

        def completion(**params):
            sent.append(source_values(params))
            contexts.append(
                "\n".join(
                    str(message["content"]) for message in params["messages"][1:-1]
                )
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(
                            content=bodies[len(sent) - 1], refusal=None
                        ),
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=5, completion_tokens=2, total_tokens=7
                ),
            )

        config = translation.TranslationConfig(
            model="gpt-4",
            prompt="Translate the supplied text.",
            vocab="",
            batchSize=1,
            useSfxReference=False,
            logFilePath=str(live_root / "log/translation.txt"),
            mismatchLogPath=str(live_root / "log/mismatchHistory.txt"),
        )
        evidence.install(translation)
        configure_builders(translation, GENERATION_PARAMETERS, evidence.record)
        with (
            patch.dict(
                os.environ,
                {
                    "BATCH_PHASE": "",
                    "API_PROVIDER": "openai",
                    "key": "fixture",
                    "api": "",
                    "TRANSLATION_RUN_LOG": str(live_root / "log/translation.txt"),
                },
            ),
            patch.object(
                translation.openai,
                "chat",
                SimpleNamespace(completions=SimpleNamespace(create=completion)),
            ),
        ):
            output, tokens = translation.translateAI(
                ["薬", "毒", "回復"],
                [],
                config,
                filename="Map001.json",
                mismatchList=[],
            )
        assert output == ["Potion", "毒", "Heal"], output
        assert tokens == [20, 8], tokens
        # Collection runs before the Batch cost review; text it cannot queue
        # stops it instead of becoming a Live request.
        with (
            patch.dict(
                os.environ,
                {"BATCH_PHASE": "collect", "API_PROVIDER": "openai", "api": ""},
            ),
            patch.object(
                translation.openai,
                "chat",
                SimpleNamespace(completions=SimpleNamespace(create=completion)),
            ),
        ):
            try:
                translation.translateAI(
                    "村", [], config, filename="Map001.json", mismatchList=[]
                )
            except translation.BatchResultUnavailableError:
                pass
            else:
                raise AssertionError("Batch collection sent a Live request.")
        assert len(sent) == 4, sent
        assert sent == [
            {"Line1": "薬"},
            {"Line1": "薬"},
            {"Line1": "毒"},
            {"Line1": "回復"},
        ], sent
        # A live chunk sees the English delivered for its source context, so a
        # split scene keeps its tense; a rejected chunk's kept source is not
        # passed on as delivered English.
        assert ["Potion" in context for context in contexts] == [
            False,
            False,
            True,
            False,
        ], contexts
        assert contexts[3].count("毒") == 1, contexts
        rows = [payload(live_root, index) for index in range(4)]
        assert [row["response"]["text"] for row in rows] == bodies
        assert [row["state"] for row in rows] == [
            "rejected",
            "validated",
            "rejected",
            "validated",
        ], rows
        assert [row["translations"] for row in rows] == [
            None,
            ["Potion"],
            None,
            ["Heal"],
        ]
        live_job = {"mode": "translate", "status": "complete"}
        result = summary(live_root, live_job)
        # The retry resends the first request's lines, so they count once.
        assert (
            result["received"],
            result["validated"],
            result["rejected"],
            result["retryBlocked"],
        ) == (4, 2, 1, False), result
        assert [
            row.get("retryOf") for row in request_view(live_root, live_job)["rows"]
        ] == [
            None,
            0,
            None,
            None,
        ], result
        assert [
            attempt["kind"] for attempt in payload(live_root, 1)["responseAttempts"]
        ] == ["original", "retry"]
        assert result["validationIssues"] == [{"file": "Map001.json", "rejected": 1}], (
            result
        )
        assert rows[0]["error"]["code"] == "replaced_response", rows[0]
        with evidence.connect() as connection:
            sources = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT sources FROM requests ORDER BY id"
                )
            ]
        assert sources[0] == sources[1] and sources[1] != sources[2] != sources[3], (
            sources
        )
        # One line still in Japanese keeps only that line's original text: the
        # rest of the response is saved, and a kaomoji whose ﾟ the source also
        # has is no Japanese left. The kept line is not saved for reuse, so the
        # next run sends it again.
        bodies.append('{"translations":["What?! (ﾟдﾟ)","Sword","盾"]}')
        config.batchSize = 3
        config.validationRetries = 0
        with (
            patch.dict(os.environ, {"BATCH_PHASE": "", "API_PROVIDER": "openai"}),
            patch.object(
                translation.openai,
                "chat",
                SimpleNamespace(completions=SimpleNamespace(create=completion)),
            ),
        ):
            output, _ = translation.translateAI(
                ["何だ(ﾟдﾟ)", "剣", "盾"], [], config, filename="Map002.json"
            )
        assert output == ["What?! (ﾟдﾟ)", "Sword", "盾"], output
        # A retry that fails whole keeps the lines an earlier attempt got right.
        bodies.extend(['{"translations":["Spear","弓"]}', "malformed provider JSON"])
        config.batchSize, config.validationRetries = 2, 1
        with (
            patch.dict(os.environ, {"BATCH_PHASE": "", "API_PROVIDER": "openai"}),
            patch.object(
                translation.openai,
                "chat",
                SimpleNamespace(completions=SimpleNamespace(create=completion)),
            ),
        ):
            output, _ = translation.translateAI(
                ["槍", "弓"], [], config, filename="Map003.json"
            )
        assert output == ["Spear", "弓"], output
        kept = payload(live_root, 4)
        assert kept["state"] == "validated", kept
        assert kept["keptLines"] == [
            {"line": "Line3", "reason": "Source-language text remains in translation"}
        ], kept
        assert request_view(live_root, live_job)["rows"][4]["keptLines"] == 1
        with evidence.connect() as connection:
            assert {
                row[0]
                for row in connection.execute("SELECT source FROM validated_items")
            } >= {"何だ(ﾟдﾟ)", "剣"} and not connection.execute(
                "SELECT 1 FROM validated_items WHERE source='盾'"
            ).fetchone()
        assert "Lines kept in Japanese: Map002.json" in (
            live_root / "log/mismatchHistory.txt"
        ).read_text(encoding="utf-8")
    # Structured refusals survive the real native normalizers, including empty
    # bodies; otherwise they are indistinguishable from generic parse failures.
    from dazedtl.compatibility.provider_responses import install as retain_refusals
    from util import batch_history, batch_providers

    retain_refusals()
    refusal, error = batch_providers._openai_result(
        {
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "refusal": "Cannot provide this translation.",
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            }
        }
    )
    assert not error and refusal["refusal"] and refusal["prompt_tokens"] == 5
    refusal = batch_history._result_entry_from_message(
        SimpleNamespace(
            content=[],
            stop_reason="refusal",
            usage=SimpleNamespace(
                input_tokens=5,
                output_tokens=2,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
    )
    assert refusal["refusal"] and refusal["prompt_tokens"] == 5
    # Batch cache writes are billed by the cache each request used: one-hour
    # at 2x input, five-minute at 1.25x. A result saved before Anthropic's
    # split was recorded counts as one-hour, as every Batch then asked for.
    split = batch_history._result_entry_from_message(
        SimpleNamespace(
            content=[],
            usage=SimpleNamespace(
                input_tokens=0,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=100,
                cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=0),
            ),
        )
    )
    assert split["cache_creation_1h_input_tokens"] == 0, split
    price = lambda **usage: batch_history._price_usage(
        {"cache_creation_input_tokens": 100, **usage}, "claude-opus-5-5"
    )
    five_minute = price(cache_creation_1h_input_tokens=0)
    assert abs(price() / five_minute - 2 / 1.25) < 1e-9, (price(), five_minute)
    # A run reads as finished only once its worker has exited and its outputs
    # are recorded; an Apply review taken earlier freezes files still changing.
    with app.backend.context():
        from desktop.backend.manual import ManualJobs

        runs = ManualJobs(temporary / "runs", threading.RLock())
        run = runs.jobs["finishing"] = {"id": "finishing", "status": "running"}
        run.update(mode="translate", phase="translate", log=[], completed=[], errors={})
        (runs.folder(run["id"]) / "translated").mkdir(parents=True)
        # A stopped file's saved progress is not a finished file; only the
        # file its module finished is.
        for saved in ("Stopped.json", "Done.json"):
            (runs.folder(run["id"]) / "translated" / saved).write_text("{}")
            runs._event(run, {"event": "progress", "args": [1, 2, saved]})
        runs._event(run, {"event": "file_finished", "args": ["Done.json"]})
        assert run["completed"] == ["Done.json"], run["completed"]
        outcome = runs._event(run, {"event": "finished", "args": [True, "Done"]})
        assert run["status"] == "running" and outcome["status"] == "complete"
        # A saved run of the retired synthetic "offline" mode stays in history
        # but never resumes, where it would run on the user's credential.
        runs.jobs["offline"] = {"id": "offline", "mode": "offline", "status": "stopped"}
        try:
            runs.resume("offline")
        except ValueError as error:
            assert "no longer supported" in str(error), error
        else:
            raise AssertionError("A saved offline test run resumed.")
        assert runs.worker is None
        # A run worker keeps the user's folders, where Claude's SDK looks for
        # settings whenever a client is created (failing on Windows without
        # them), and none of the app's provider keys.
        import anthropic
        from desktop.backend.manual import worker_environment

        # It also keeps a test scenario's OpenAI preset address, so its
        # Batches take OpenAI's own path there as they do in the app.
        from util.batch_providers import PROVIDER_OPENAI, detect_batch_provider

        preset = "http://127.0.0.1:9/v1"
        folders = {"HOME": str(temporary), "APPDATA": str(temporary)}
        with patch.dict(
            os.environ,
            {
                **folders,
                "ANTHROPIC_API_KEY": "app-key",
                "DAZEDTL_TEST_OPENAI_ENDPOINT": preset,
            },
        ):
            environment = worker_environment(
                temporary, {"mode": "estimate", "settings": {}}
            )
        assert (
            folders.items() <= environment.items()
            and "ANTHROPIC_API_KEY" not in environment
        )
        with patch.dict(os.environ, environment, clear=True):
            anthropic.Anthropic(api_key="run-key")
            assert detect_batch_provider("fixture", preset, "openai") == PROVIDER_OPENAI
    # Guided reads each file's lines from the file (translation/file_lines.py)
    # and must agree with what the engine sends: a line it counts that the
    # engine never sends would read unfinished forever, and text the engine
    # sends outside the lines it counts would leave a file reading done with
    # Japanese in it, or replace the game's own English. A real pass over the
    # fixture games, answered like the live test's stand-in, sends only
    # Japanese from the lines left, and exactly for the files with lines
    # left, and leaves none; a second pass over its own output sends nothing.
    with app.backend.context():
        from dazedtl.compatibility.worker_policy import configure_states
        from dazedtl.translation import file_lines
        from modules import rpgmakermvmz as parser
        from util import extensions
        from util import rpgmaker_blocks as blocks
        from util.rpgmaker_markers import PluginList, comment_markers
        from util.rpgmaker_profiles import DB_FILES, PHASE0_CONFIG, PHASE1_CONFIG
        from util.runtime_text import _CONTROL_CODE_RE
        from util.source_text import LETTERS, holds_source

        # A refusal note an older run saved in a database note tag, which the
        # database pass translates, is a line left.
        noted = [
            None,
            {
                "name": "Potion",
                "note": "<SG説明:[Not translated]>",
                "_original": {"name": "薬", "note": "<SG説明:薬です>"},
            },
        ]
        assert file_lines.count("Items.json", noted, "database", frozenset()) == {
            "lines": 2,
            "translated": 1,
            "notes": 1,
        }, file_lines.count("Items.json", noted, "database", frozenset())
        # A control code's argument names a plugin's asset, never text: the
        # engine sends such a line again on every pass, but it is translated.
        assert not holds_source(r"\SA[びっくり]Hello") and holds_source(
            r"\SA[びっくり]こんにちは"
        )
        # Furigana's base is text the player reads, which the engine sends.
        for ruby in (r"「\rb[魔王,まおう]！」", r"\\R[魔王,まおう]", "{魔王|まおう}！"):
            assert holds_source(ruby), ruby
        assert not holds_source(r"\rb[Demon King,まおう]!")
        # Other scripts and private-use icon glyphs are not Japanese.
        assert not holds_source("안녕  ꞌ")
        # A name box counts the name the engine translates, not what follows.
        for value in (
            "村長",
            "【開放条件】\n・レベル：1",
            r"\C[16]【スキル初期化】\C[0]" + "\n説明",
            r"ミカ\C[2]",
            "",
        ):
            assert file_lines.speaker_name(value) == parser._101_speaker_name(value), (
                value
            )

        def stand_in(value):
            # Like a model, it keeps control codes and their arguments.
            text = str(value)
            prefix = re.match(r"^(\[[^\n]*?\]:\s*)", text)
            body = text[prefix.end() :] if prefix else text
            pieces = _CONTROL_CODE_RE.split(body)
            codes = _CONTROL_CODE_RE.findall(body)
            kept = re.sub(
                r"\s+",
                " ",
                "".join(
                    LETTERS.sub(" ", piece)
                    + (codes[index] if index < len(codes) else "")
                    for index, piece in enumerate(pieces)
                ),
            ).strip()
            return (prefix[1] if prefix else "") + f"Tested {len(text)} {kept}".strip()

        sent = []
        # Lines holding a key come back as its reply, as the test scenarios'
        # stand-in answers them (scripts/testkit/provider.mjs).
        replies: dict[str, str] = {}

        def replied(value):
            text = str(value)
            reply = next((reply for key, reply in replies.items() if key in text), None)
            if reply is None:
                return stand_in(value)
            prefix = re.match(r"^(\[[^\n]*?\]:\s*)", text)
            return (prefix[1] if prefix else "") + reply

        def answer_all(text, *_args, **_kwargs):
            values = list(text) if isinstance(text, list) else [text]
            sent.extend(values)
            answers = [replied(value) for value in values]
            return [answers if isinstance(text, list) else answers[0], [0, 0]]

        def engine_pass(file, document, vxace, **settings):
            kind = str(parser.mvmz_file_kind(file))
            parsers = {
                "Map": parser.parseMap,
                "CommonEvents": parser.parseCommonEvents,
                "Troops": parser.parseTroops,
                "System": parser.parseSystem,
                "States": parser.parseSS,
            }
            options: dict[str, Any] = {
                "translateAI": extensions.point(answer_all),
                "VXACE": vxace,
                "FIXTEXTWRAP": True,
                **(
                    PHASE0_CONFIG
                    if file in DB_FILES
                    else {**PHASE1_CONFIG, "CODE408": True}
                ),
                **settings,
            }
            sent.clear()
            with (
                patch.multiple(parser, **options),
                patch.dict(os.environ, {"DAZED_GAME_ROOT": str(lines_game)}),
                # As openFiles reads a file, against its staged original.
                parser._MIRRORS.opened(parser._mirror(file, document)),
            ):
                if kind in parsers:
                    result = parsers[kind](document, file)
                else:
                    result = parser.parseNames(document, file, kind)
                assert result[2] is None, file
            return list(sent)

        lines_game = temporary / "lines-game"
        # The parser logs and saves progress beside the files it reads.
        for folder in ("data", "log", "translated"):
            (lines_game / folder).mkdir(parents=True)

        def step(code, *parameters):
            return {"code": code, "indent": 0, "parameters": list(parameters)}

        # What the fixtures lack: a name box with more after its name, a 401
        # label the engine reads as a speaker, a message split at a code,
        # scrolling text, choice help with Comment text on, and a name change
        # to a name the game reads as a file name.
        page = [
            step(320, 2, "立ち絵_笑顔"),
            step(101, "", 0, 0, 2, "【開放条件】\n・レベル：1"),
            step(401, r"\C[16]【チュートリアル】\C[0]"),
            step(401, "基本的な操作を説明します。"),
            step(101, "", 0, 0, 2, "ミカ"),
            step(401, "前半の文です。"),
            step(401, r"\C[2]後半の文です。"),
            step(105, 2, False),
            step(405, "遠い昔の物語。"),
            step(405, "村は静かだった。"),
            step(102, ["森", "村"], 1, 0, 2, 0),
            step(402, 0, "森"),
            step(108, "選択肢ヘルプ"),
            step(408, "森へ向かいます。"),
            step(402, 1, "村"),
            step(108, "選択肢ヘルプ"),
            step(408, "村に残ります。"),
            step(404),
            step(0),
        ]
        (lines_game / "data/Map002.json").write_text(
            json.dumps(
                {
                    "displayName": "森の入口",
                    "events": [None, {"id": 1, "pages": [{"list": page}]}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # Text the engine sends once and then never again, as the
        # finished-text game variant holds it for test scenarios.
        fixtures = Path(__file__).resolve().parent
        finished = json.loads(
            (fixtures / "game-variants/finished-text/variant.json").read_text("utf-8")
        )
        (lines_game / "data/Map003.json").write_text(
            json.dumps(
                {
                    "displayName": "",
                    "events": [
                        None,
                        *(
                            {**event, "id": number}
                            for number, event in enumerate(finished["events"], 1)
                        ),
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        markers = comment_markers(PluginList())
        policy = {
            "choiceCollection": CHOICE_COLLECTION,
            "speakerContext": SPEAKER_CONTEXT,
            "sameLineSpeakers": SAME_LINE_SPEAKERS,
            "pagePacking": PAGE_PACKING,
        }
        directory = os.getcwd()
        os.chdir(lines_game)
        try:
            # Runs frozen before the source-text policy keep their requests:
            # they send labels and map names again, and read 【】 as Japanese.
            configure_states({"engine": "MVMZ"}, temporary, policy)
            older = json.loads((lines_game / "data/Map003.json").read_text("utf-8"))
            assert engine_pass("Map003.json", older, False) == [
                "",
                "回想部屋へ",
                "→中継地点",
                "村人",
                "古びた井戸",
                "旅人",
                "えっ、本当に？",
                "【Saving beforehand is recommended】",
                "・・・・・。",
                ".......。 \\C[2]？\\C[0]",
            ]
            # A label ends at its own >, and its translation replaces only
            # it, leaving the note tags after it alone.
            assert older["events"][4]["note"].endswith(
                "><Shadow:false><Sound:古びた井戸>"
            )
            configure_states(
                {"engine": "MVMZ"}, temporary, {**policy, "sourceText": SOURCE_TEXT}
            )
            for folder, vxace in (
                (fixtures / "mz-game/data", False),
                (fixtures / "ace/ace_json", True),
                (lines_game / "data", False),
            ):
                for path in sorted(folder.glob("*.json")):
                    file = path.name
                    phase = "database" if file in DB_FILES else "dialogue"
                    if phase == "dialogue" and parser.mvmz_file_kind(file) not in {
                        "Map",
                        "CommonEvents",
                        "Troops",
                    }:
                        continue
                    document = json.loads(path.read_text("utf-8-sig"))
                    translated = deepcopy(document)
                    before = file_lines.count(file, document, phase, markers)
                    unfinished = "\n".join(
                        row["text"]
                        for row in file_lines.left(file, document, phase, markers)
                    )
                    sends = engine_pass(file, translated, vxace)
                    # Players read the names, nicknames and profiles events
                    # change, as the Ace fixture's common event does.
                    changed = [
                        command["parameters"]
                        for _listed, commands in blocks.command_lists(translated)
                        for command in commands
                        if isinstance(command, dict)
                        and command.get("code") in {320, 324, 325}
                        and "_" not in str(command["parameters"])
                        and holds_source(str(command["parameters"]))
                    ]
                    assert not changed, (folder.name, file, changed)
                    after = file_lines.count(
                        file, translated, phase, markers, lambda: document
                    )
                    # A translated map name's source is the original's name.
                    if after.pop("mapName", None) is not None and holds_source(
                        document.get("displayName")
                    ):
                        after["lines"] += 1
                        after["translated"] += 1
                    left = before["lines"] - before["translated"]
                    report = (folder.name, file, before, after, sends)
                    assert (left > 0) == bool(sends), report
                    # Each value sent holds Japanese, and only Japanese of a
                    # line left.
                    for value in sends:
                        assert holds_source(value), (report, value)
                        for word in re.findall(f"{LETTERS.pattern}+", value):
                            assert word in unfinished, (report, value, word)
                    assert after == {
                        "lines": before["lines"],
                        "translated": before["lines"],
                    }, (
                        report,
                        file_lines.left(file, translated, phase, markers),
                    )
                    again = engine_pass(file, translated, vxace)
                    assert not again, (report, again)
            # Messages and choices the game wrote without Japanese letters,
            # alone or below a speaker's name, show its Japanese punctuation
            # in English, and a code keeps its argument as the game wrote it.
            quiet = json.loads((lines_game / "data/Map003.json").read_text("utf-8"))
            engine_pass("Map003.json", quiet, False)
            assert [
                command["parameters"][0]
                for command in quiet["events"][5]["pages"][0]["list"]
                if command["code"] in {401, 102} and "_original" not in command
            ] == [
                ".....",
                ".......",
                r"\C[2]?\C[0]",
                '"……"',
                "...?",
                ["?????", "Leave"],
            ]
            assert (
                parser.target_text.english_punctuation(
                    r"\SE[ドン！]・・・。\C[0]OK。", True
                )
                == r"\SE[ドン！]...\C[0]OK."
            )
            # The kaomoji game variant, answered as its stand-in answers it but
            # for a word the model leaves as it was: a translation keeping a
            # lone kana or mark its source holds, the ﾟ of a kaomoji, the 〇
            # of a censor mask or the は of that word, reads translated and is
            # not sent again; a line given back unchanged reads left and is.
            kaomoji = json.loads(
                (fixtures / "game-variants/kaomoji/variant.json").read_text("utf-8")
            )
            replies.update(
                kaomoji["provider"]["reply"],
                まだ訳せない="This word は can't be translated yet.",
            )
            talk = {
                "displayName": "",
                "events": [None, *({**event, "id": 1} for event in kaomoji["events"])],
            }
            before = file_lines.count("Map004.json", talk, "dialogue", markers)
            engine_pass("Map004.json", talk, False)
            after = file_lines.count("Map004.json", talk, "dialogue", markers)
            assert after == {
                "lines": before["lines"],
                "translated": before["lines"] - 1,
            }, (
                before,
                after,
                file_lines.left("Map004.json", talk, "dialogue", markers),
            )
            assert engine_pass("Map004.json", talk, False) == ["え？"]
            # Runs frozen with the first source-text policy keep sending a
            # line that keeps a lone kana, so their requests rebuild.
            configure_states(
                {"engine": "MVMZ"},
                temporary,
                {**policy, "sourceText": "source-letters-v1"},
            )
            assert engine_pass("Map004.json", talk, False) == [
                "[Tested 2]: この言葉はまだ訳せない。",
                "[Tested 2]: うわっ、うん〇を踏んだ！",
                "え？",
            ]
            # Translated into Chinese, a line's hanzi are its own text and
            # only its kana read as Japanese left: read as Japanese, every
            # line was sent again and counted left. A name kept letter for
            # letter, 旅人, is translated too. Runs frozen with the second
            # source-text policy keep sending them.
            from util.languages import reading

            replies.clear()
            replies.update(
                {
                    "何だこれは": "这、这是什么？！(ﾟдﾟ)",
                    "うん〇": "呜哇，踩到〇了！",
                    "まだ訳せない": "这个词まだ不能翻译。",
                    "え？": "诶？",
                    "森の向こう": "森林那边有个村子。",
                    "旅人": "旅人",
                }
            )
            variant_events = json.loads(
                (fixtures / "game-variants/kaomoji/variant.json").read_text("utf-8")
            )["events"]
            # So are the map's name and an event's <LB> label, which kept no
            # source: read without one, they were sent again on every pass
            # and Lines counted them left.
            replies["魔王城"] = "魔王城"
            chinese = {
                "displayName": "魔王城",
                "events": [None, *({**event, "id": 1} for event in variant_events)],
            }
            chinese["events"][1] = {
                **chinese["events"][1],
                "name": "旅人の家",
                "note": "<LB>",
            }
            configure_states(
                {"engine": "MVMZ"}, temporary, {**policy, "sourceText": SOURCE_TEXT}
            )
            with reading("Japanese", "Chinese"):
                engine_pass("Map004.json", chinese, False)
                after = file_lines.count("Map004.json", chinese, "dialogue", markers)
                assert after == {
                    "lines": before["lines"] + 2,
                    "translated": before["lines"] + 1,
                }, (
                    after,
                    [
                        c["parameters"]
                        for e in chinese["events"][1:]
                        for p in e["pages"]
                        for c in p["list"]
                    ],
                )
                resent = engine_pass("Map004.json", chinese, False)
                assert len(resent) == 1 and "まだ" in resent[0], resent
                configure_states(
                    {"engine": "MVMZ"},
                    temporary,
                    {**policy, "sourceText": "source-letters-v2"},
                )
                assert len(engine_pass("Map004.json", chinese, False)) == 7

            # A map translated before names kept their source keeps none,
            # nor do a note label and a plugin command's argument: read
            # against the game's original file, which the app stages in the
            # run's folder, none is sent again, and the map and the <LB>
            # event keep the original's name as their source. Runs frozen
            # with the third source-text policy send them again.
            def upgraded(name, label, sign, message):
                event = deepcopy(variant_events[0])
                event.update(id=1, name=label, note=f"<LB><dn:{sign}>")
                event["pages"][0]["list"] = [
                    step(
                        357,
                        "TorigoyaMZ_NotifyMessage",
                        "notify",
                        "",
                        {"message": message},
                    ),
                    step(0),
                ]
                return {"displayName": name, "events": [None, event]}

            staged = lines_game / "originals/data"
            staged.mkdir(parents=True)
            (staged / "Map007.json").write_text(
                json.dumps(
                    upgraded("はじまりの村", "旅人の家", "古い井戸", "ようこそ")
                ),
                "utf-8",
            )
            chinese = upgraded("起始之村", "旅人之家", "古井", "欢迎")
            configure_states(
                {"engine": "MVMZ"}, temporary, {**policy, "sourceText": SOURCE_TEXT}
            )
            with reading("Japanese", "Chinese"):
                older = deepcopy(chinese)
                # Lines read them against the original as well: read without
                # it, the map name and both labels counted left.
                original = json.loads((staged / "Map007.json").read_text("utf-8"))
                counts = file_lines.count(
                    "Map007.json", older, "dialogue", markers, lambda: original
                )
                assert counts == {"lines": 3, "translated": 3}, counts
                assert not file_lines.left(
                    "Map007.json", older, "dialogue", markers, lambda: original
                )
                assert engine_pass("Map007.json", chinese, False, CODE357=True) == []
                assert chinese["_original"] == {"displayName": "はじまりの村"}
                assert chinese["events"][1]["_original"] == {"name": "旅人の家"}
                configure_states(
                    {"engine": "MVMZ"},
                    temporary,
                    {**policy, "sourceText": "source-letters-v3"},
                )
                assert engine_pass("Map007.json", older, False, CODE357=True) == [
                    "起始之村",
                    "旅人之家",
                    "古井",
                    "欢迎",
                ]
            configure_states(
                {"engine": "MVMZ"}, temporary, {**policy, "sourceText": SOURCE_TEXT}
            )
            replies.clear()
            # The help counts only while Comment text translates it.
            help_map = json.loads((lines_game / "data/Map002.json").read_text("utf-8"))
            assert file_lines.count("Map002.json", help_map, "dialogue", markers) == {
                "lines": 8,
                "translated": 0,
                "help": 2,
            }
            assert (
                file_lines.count("Map002.json", help_map, "dialogue", frozenset())[
                    "lines"
                ]
                == 6
            )
        finally:
            os.chdir(directory)
    for module_name, module in list(sys.modules.items()):
        if module_name.startswith(
            ("util.", "modules.", "desktop.backend.")
        ) and getattr(module, "__file__", None):
            assert Path(module.__file__).is_relative_to(ENGINE_ROOT), module_name
    print(
        "Bundled startup, frozen guidance, saved-run signature and isolated parser estimation passed."
    )
finally:
    app.guided.batch_monitor.close()
    app.translation.jobs.close()
    app.images.close()
    app.backend.close()
    app.workspace_lock.close()
