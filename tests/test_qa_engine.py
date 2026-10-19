"""Text QA's engine: its mechanical rules, and its pipeline on a generated game."""

import json
import tempfile
import unittest
from pathlib import Path

from tests.engine import engine_module
from tests.probe import Probe

# The journeys run in their own interpreters, alongside the rest of the suite,
# because the engine's `util` package would clash with the fakes other tests
# install.
probe = Probe("qa_engine.py")
declines = Probe("qa_declines.py")
scenes = Probe("qa_scene.py")
interface = Probe("qa_interface.py")
glossary = Probe("qa_glossary.py")
manifest = engine_module("util/rpgmaker_qa_manifest.py")
verify = engine_module("util/rpgmaker_qa_verify.py")
lint = engine_module("util/rpgmaker_qa_lint.py")
checks = engine_module("util/rpgmaker_qa_checks.py")
headers = engine_module("util/rpgmaker_header_check.py")

WORDS = (
    "りんご",
    "みかん",
    "さくら",
    "うみ",
    "やま",
    "かぜ",
    "ほし",
    "つき",
    "はな",
    "くも",
)


def box(name, *lines, face=""):
    return [
        {"code": 101, "parameters": [face, 0, 0, 2, name]},
        *({"code": 401, "parameters": [line]} for line in lines),
    ]


def header_game():
    """Scenes in one game's conventions, with a slip of each kind beside the
    ordinary boxes each rule must leave alone."""
    arina = lambda word: box("アリナ", f"あたし、{word}が好きだよ！♥", face="arina")
    yuki = lambda word: box("ユーキ", f"ぼくは{word}が苦手なんだよね…", face="yuki")
    narration = lambda word: box("", f"{word}の部屋は静かだった。")
    effect = lambda word, name="": box(name, f"\\NK[1]{word}ぬちゅ\\NK[0]")
    common = [
        command
        for word in WORDS
        for command in (
            *arina(word),
            *box("アリナ", f"あたしも{word}を見たよ！♥", face="arina"),
            *box("アリナ", f"\\C[2]あたし\\C[0]、{word}が欲しいな！♥", face="arina"),
            *box("エリカ", f"私は{word}が好きよ！", face="erika"),
            *box("旅人", f"{word}を探しているの。", face="traveler"),
            *yuki(word),
            *narration(word),
            *effect(word),
            *effect(word),
            *effect(word),
            # A speaker who calls themself by name does it on purpose, even
            # when others call them the same.
            *box("ミナ", f"ミナちゃんはね、{word}が好き！", face="mina"),
            *box("エリカ", f"ミナちゃん、{word}よ！", face="erika"),
        )
    ]
    pages = [
        common,
        [
            *box("ユーキ", "ぼくもりんごが好きだよ！", face="arina"),  # face
            *box("ユーキ", "アリナちゃん、また明日ね…", face="yuki"),
            *box(
                "アリナ", "アリナちゃん、いらっしゃい！", face="arina"
            ),  # self-address, said as ユーキ says it
            *box("ユーキ", "私、もう帰るね…♥", face="yuki"),  # pronoun
            *effect("さくら", "ユーキ"),  # sound-effect
            *box("", "あたし、もうだめだよ！♥"),  # unnamed-line
            *arina("やま"),
            *yuki("ほし"),
        ],
        [
            # Names before a reveal, one shared by several characters, an
            # alias that recurs with another's face, a speaker naming or
            # introducing themself, 私 from a speaker who says あたし, a
            # pronoun no one in the scene says, unnamed speech and narration
            # between named boxes, and named boxes beside them.
            *box("謎の少年", "ぼくは誰でしょう…", face="yuki"),
            *box("？？？", "ぼくは誰でしょう…", face="yuki"),
            *box("？？？", "私は誰かしら…", face="erika"),
            *box("？？？", "ミナは誰でしょう！", face="mina"),
            *[
                command
                for word in WORDS[:3]
                for command in box("旅人", f"{word}を探しているの。", face="arina")
            ],
            *box("ユーキ", "おれについて来い！なんてね", face="yuki"),
            *box("エリカ", "ユーキ…どこ？", face="erika"),
            *box("ユーキ", "ユーキ、参上！", face="yuki"),
            *box("ユーキ", "エリカ様、お願い！", face="yuki"),
            *box("アリナ", "エリカちゃん、おはよう！♥", face="arina"),
            *box("エリカ", "このエリカ様に任せなさい！", face="erika"),
            *box("エリカ", "エリカちゃん、言うな！", face="erika"),
            *box("アリナ", "アリナはね、元気だよ！", face="arina"),
            *box("アリナ", "アリナちゃんがお手伝いするね！", face="arina"),
            *box("エリカ", "私はりんごが好きよ！", face="erika"),
            *box("アリナ", "私もりんごが好きだよ！♥", face="arina"),
            *box("アリナ", "\\C[2]あたし\\C[0]もだよ！♥", face="arina"),
            *box("", "あたし、うみに行きたいな！♥"),
            *arina("かぜ"),
            *narration("つき"),
            *effect("ほし", "アリナ"),
            *yuki("はな"),
            *effect("くも", "アリナ"),
            *arina("くも"),
        ],
    ]
    return {"events": [None, {"id": 1, "pages": [{"list": page} for page in pages]}]}


class QAEngineTests(unittest.TestCase):
    def test_review_journey_gates_and_findings(self):
        returncode, output = probe.result()
        self.assertEqual(returncode, 0, output)

    def test_declined_items_stay_within_their_helper(self):
        returncode, output = declines.result()
        self.assertEqual(returncode, 0, output)

    def test_scene_corrections_apply_and_undo_as_one(self):
        returncode, output = scenes.result()
        self.assertEqual(returncode, 0, output)

    def test_squeezed_screen_text_is_reviewed_on_its_captures(self):
        returncode, output = interface.result()
        self.assertEqual(returncode, 0, output)

    def test_glossary_fixes_only_renderings_and_applies_accepted_ones(self):
        returncode, output = glossary.result()
        self.assertEqual(returncode, 0, output)

    def test_numbers_beside_stat_letters_count(self):
        # Skill descriptions from a release, where English moves the stat away
        # from its number.
        for source, live in (
            (
                "敵全体へ90%威力の旋風斬り。TP24増加。",
                "A whirlwind slash against all enemies at 90% power. Increases TP by 24.",
            ),
            ("ＴＰ２０増加", "Increases TP by 20."),
            ("1000Gを手に入れた", "Obtained 1,000 G."),
        ):
            evidence = manifest._mechanical_evidence(source, live, None)
            self.assertNotIn("visible-number-mismatch", evidence["flags"], source)
            # The verifier recomputes the evidence, so it must count the same.
            self.assertEqual(verify._mechanical(source, live, None), evidence)
        # Runtime codes and identifiers still show no number.
        evidence = manifest._mechanical_evidence(
            "\\V[5]でHP30回復、EV024", "Restores 30 HP with \\V[5], EV024", None
        )
        self.assertEqual(evidence["source_visible_numbers"], ["30"])

    def test_header_check_flags_slips_but_not_the_games_conventions(self):
        game = header_game()
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / "Map001.json").write_text(json.dumps(game), encoding="utf-8")
            found = headers.check(data)
            flagged = {
                (flag["pointer"].rsplit("/", 1)[-1], flag["kind"])
                for flag in found["flags"]
                if flag["pointer"].startswith("/events/1/pages/1/")
            }
            self.assertEqual(
                flagged,
                {
                    ("0", "face"),
                    ("4", "self-address"),
                    ("6", "pronoun"),
                    ("8", "sound-effect"),
                    ("10", "unnamed-line"),
                },
                found["flags"],
            )
            self.assertEqual(found["total"], len(flagged), found["flags"])
            # Once translated, the check reads each header's and line's
            # Japanese, and a nameplate the translation already gave another
            # speaker is not flagged again.
            for page in game["events"][1]["pages"]:
                for command in page["list"]:
                    parameters = command["parameters"]
                    if command["code"] == 401:
                        command["_original"] = parameters[0]
                        parameters[0] = "English"
                    elif command["code"] == 101 and parameters[4]:
                        command["_original"] = parameters[4]
                        parameters[4] = "Speaker " + parameters[4]
            game["events"][1]["pages"][1]["list"][4]["parameters"][4] = "Speaker 店主"
            (data / "Map001.json").write_text(json.dumps(game), encoding="utf-8")
            again = headers.check(data)
            self.assertEqual(
                [flag["kind"] for flag in again["flags"]],
                ["face", "pronoun", "sound-effect", "unnamed-line"],
                again["flags"],
            )

    def test_dakuten_apostrophes_spare_slurs_and_moans(self):
        # Lines from a release whose reviewer rejected the proposed fixes.
        for source, live in (
            ("頭がぐるぐるしゅる゛…", "My head'sh shpinning"),
            ("うおぉ゛…お゛ぉ", "Whoa'…o'oh"),
        ):
            self.assertEqual(lint.proposals(source, live, lint.Game()), {}, live)
        # An apostrophe inside or after an ordinary word is still a leftover.
        self.assertEqual(
            lint.proposals("な゛んで…や゛めて", "Wh'y… Sto'p it'…", lint.Game()),
            {"lint:dakuten-apostrophe": "Why… Stop it…"},
        )

    def test_quoted_titles_spare_lines_that_are_speech(self):
        # Released lines: speech in 「」 that another line's translation of a
        # shorter source would have overwritten.
        titles = lint.Game(
            titles={
                "神！": {"God!!"},
                "トレイタースライム！": {"The Traitor Slime!!"},
                "魔法の書": {"Book of Magic"},
            }
        )
        for source, live in (
            ("「神！」", '"God!"'),
            (
                "「あ、そ、そうだ…！\n　トレイタースライム！」",
                '"Oh, r-right...! The Traitor Slime!"',
            ),
        ):
            self.assertEqual(lint.proposals(source, live, titles), {}, live)
        # A title quoted inside a sentence still follows the title it names.
        self.assertEqual(
            lint.proposals("『魔法の書』を読んだ", 'I read "Book of Magics".', titles),
            {"lint:quoted-title": 'I read "Book of Magic".'},
        )

    def test_label_numbers_spare_runtime_codes(self):
        # Released lines put a color or plugin code right before a number,
        # and lint used to space every one of them.
        self.assertEqual(
            lint.proposals(
                "_PUM[0]1\\G 手に入れた！", "_PUM[0]1\\G obtained!", lint.Game()
            ),
            {},
        )
        self.assertEqual(
            lint.proposals(
                "【噂Lv】3で\\c[14]25000G",
                "[Rumor Lv.]3 for \\c[14]25000G",
                lint.Game(),
            ),
            {"lint:level-tag-spacing": "[Rumor Lv.] 3 for \\c[14]25000G"},
        )

    def test_database_checks_find_what_reviewers_read_apart(self):
        # Defects a release's reviewers found only by luck: a skill named like
        # another and an MZ message without its subject.
        rows = [
            ("Skills.json", 42, "name", "払い斬り", "Sweeping Slash"),
            ("Skills.json", 173, "name", "薙ぎ払い", "Sweeping Slash"),
            (
                "States.json",
                42,
                "message4",
                "の幻惑が解けた",
                "was freed from the Illusion.",
            ),
            # A capital hides a missing subject only after a source that
            # starts with a particle.
            ("Skills.json", 341, "message1", "は仲間を呼んだ！", "Called for allies!"),
            ("Skills.json", 342, "message1", "仲間を呼んだ！", "Called for allies!"),
            # Map names players never see, a complete sentence and a message
            # with its %1 all pass.
            ("MapInfos.json", 1, "name", "森", "Sweeping Slash"),
            ("MapInfos.json", 2, "name", "林", "Sweeping Slash"),
            ("States.json", 43, "message4", "の毒が消えた", "The poison wore off."),
            ("States.json", 44, "message1", "%1は倒れた！", "%1 fell!"),
        ]
        records = [
            {
                "identity": f"{file}#{entry}/{field}",
                "file": file,
                "classification": "database",
                "database_entity": {"id": entry, "field": field},
                "source": source,
                "live": live,
            }
            for file, entry, field, source, live in rows
        ]
        manifest = {
            "records": records,
            "clusters": [
                {
                    "representative": record["identity"],
                    "identities": [record["identity"]],
                }
                for record in records
            ],
        }
        found = checks.database_checks(manifest, "MZ")
        self.assertEqual(
            {
                identity: [entry["check"] for entry in entries]
                for identity, entries in found.items()
            },
            {
                "Skills.json#42/name": ["name-collision"],
                "Skills.json#173/name": ["name-collision"],
                "States.json#42/message4": ["battler-name"],
                "Skills.json#341/message1": ["battler-name"],
            },
        )
        self.assertIn(
            "Skills.json 173 薙ぎ払い", found["Skills.json#42/name"][0]["note"]
        )
        # MV writes the name right before the message, so only a glued one fails.
        for live, failing in (("collapsed!", True), (" collapsed!", False)):
            records[2]["live"] = live
            found = checks.database_checks(manifest, "MV")
            self.assertEqual("States.json#42/message4" in found, failing, live)
