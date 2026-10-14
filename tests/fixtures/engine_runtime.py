"""An offline startup and parser probe using only a generated miniature game."""

import json
import os
import re
import socket
import sys
import threading
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
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
    frozen = manual.folder(job["id"]) / "context/system.md"
    assert (
        frozen.read_bytes()
        == (root / "backend/dazedtl/engine/data/skills/system.md").read_bytes()
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
            PAGE_PACKING,
            SAME_LINE_SPEAKERS,
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
            # Batch collection queues a lone label or plugin argument with the
            # file text. It sent each one Live before the Batch cost review.
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
                parser.translateNoteOmitSpace({"note": "<LB:村>"}, r"<LB:(.*?)\s?>.*")
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
        from openai import BadRequestError
        from util import translation
        from util.batch_providers import detect_batch_provider

        with patch.dict(
            os.environ,
            {"API_PROVIDER": "openai", "api": "https://openrouter.ai/api/v1"},
        ):
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
        for protocol, endpoint, model, field in (
            (
                "openai",
                "https://api.openai.com/v1",
                "gpt-6-sol",
                "max_completion_tokens",
            ),
            (
                "openai",
                "https://openrouter.ai/api/v1",
                "z-ai/glm-5.3-flash",
                "max_tokens",
            ),
            (
                "gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai",
                "gemini-3.8-flash",
                "max_tokens",
            ),
            ("mistral", "https://api.mistral.ai/v1", "mistral-medium", "max_tokens"),
            ("openai", "https://fixture.invalid/v1", "local-model", "max_tokens"),
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
            "    print('FILE_RESULT:' + json.dumps({'filename': name, 'result': '[Input: 1]', 'mismatch_count': 1}), flush=True)\n",
            encoding="utf-8",
        )
        live_task = TranslationTask(
            live_root, ("RPG Maker MV/MZ", (".json",), None), runner_script=runner
        )
        errors, mismatched, done = [], [], []
        live_task.file_error_signal.connect(lambda *args: errors.append(args))
        live_task.file_mismatch_signal.connect(lambda *args: mismatched.append(args))
        live_task.progress_signal.connect(lambda *args: done.append(args[2]))
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
        # Concurrent files share the queue: each file goes to one worker once.
        for path in live_root.glob("launches-*.txt"):
            path.unlink()
        many = [f"Map1{number:02d}.json" for number in range(12)]
        with patch.dict(os.environ, {"fileThreads": "3"}):
            assert live_task._run_files(many, False) not in {"Fail", "Stopped"}
        handed = [name for names in worker_files() for name in names]
        assert sorted(handed) == many, handed
        # That worker saves a Batch's files one after another; a file missing
        # a result must not keep the files after it from saving theirs.
        from contextlib import redirect_stdout
        from io import StringIO

        from util import subprocess_runner, translation_task

        def consume(name, _estimate):
            if name == "Map001.json":
                raise translation.BatchResultUnavailableError("Missing.")
            return "Saved"

        reported = StringIO()
        with (
            patch.dict(os.environ, {"BATCH_PHASE": "consume"}),
            patch.object(
                translation_task, "translation_module", lambda _: (0, 0, consume)
            ),
            redirect_stdout(reported),
        ):
            subprocess_runner.run_handler(
                temporary, "Fixture", ["Map001.json", "Map002.json"], False
            )
        reports = [
            (kind, json.loads(value)["filename"])
            for kind, _, value in (
                line.partition(":") for line in reported.getvalue().splitlines()
            )
            if kind in {"FILE_ERROR", "FILE_RESULT"}
        ]
        assert reports == [
            ("FILE_ERROR", "Map001.json"),
            ("FILE_RESULT", "Map002.json"),
        ], reported.getvalue()

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
        from dazedtl.compatibility.process_view import payload
        from dazedtl.compatibility.request_parameters import batch_routing
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
                                                        if key == "Line1"
                                                        else ""
                                                        for key in row["body"][
                                                            "response_format"
                                                        ]["json_schema"]["schema"][
                                                            "required"
                                                        ]
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
            translation.translateAI(["薬"], [], config, filename="Items.json")
            translation.translateAI(["回復", "毒"], [], config, filename="Items.json")
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
            assert (
                abs(
                    parser.calculateCost(10, 4, config.model)
                    - (8 * 0.8 + 2 * 0.2 + 4 * 3) / 1_000_000
                )
                < 1e-12
            )
            # Schema-shaped responses can fail native content validation without
            # being refusals. Retain the failed body and generic outcome before
            # the file finishes, even when human-readable logs are unavailable.
            failed_output = translation.translateAI(
                ["回復", "毒"], [], config, filename="Items.json"
            )
            assert failed_output[0] == ["回復", "毒"], failed_output
            (router_root / "log/translation.txt").unlink()
            (router_root / "log/mismatches.txt").unlink()
            batch_rows = [payload(router_root, index) for index in range(2)]
            assert [row["state"] for row in batch_rows] == ["validated", "rejected"], (
                batch_rows
            )
            assert json.loads(batch_rows[1]["response"]["text"]) == {
                "Line1": "Potion",
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
        assert translation.validate_translation_content(
            ["うん〇だ！", "うんこだ！"],
            ["Sh〇t!", "Sh〇t!"],
            parser.LANGREGEX,
            "English",
        )[1] == [1]
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
        run.update(mode="translate", phase="translate", log=[])
        runs.folder(run["id"]).mkdir(parents=True)
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

        folders = {"HOME": str(temporary), "APPDATA": str(temporary)}
        with patch.dict(os.environ, {**folders, "ANTHROPIC_API_KEY": "app-key"}):
            environment = worker_environment(
                temporary, {"mode": "estimate", "settings": {}}
            )
        assert (
            folders.items() <= environment.items()
            and "ANTHROPIC_API_KEY" not in environment
        )
        with patch.dict(os.environ, environment, clear=True):
            anthropic.Anthropic(api_key="run-key")
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
