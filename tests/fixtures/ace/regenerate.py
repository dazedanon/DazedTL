"""Rebuilds the synthetic RPG Maker VX Ace fixture the conversion tests use.

The data is made up and small, but shaped like the editor's: its instance
variable order, binary default names, shared move commands, out-of-range
tones, large integers, unusual floats and String hash keys stored apart.
Ruby 3.4 loads and dumps it to check that the port writes the same bytes,
and RV2JSON 1.2.1 then writes the expected JSON (ace_json) and packs the
translated JSON (translated, over ace_json) into the expected data (packed).
RV2JSON runs from a copy with the port's Change Vehicle BGM fix, so packing
keeps that command's BGM object.

    python tests/fixtures/ace/regenerate.py RUBY RV2JSON_CHECKOUT

RUBY is a Ruby 3.4 executable and RV2JSON_CHECKOUT a clone of
https://github.com/Sinflower/RV2JSON at the commit the port follows.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE.parents[2] / "backend/dazedtl/engine"))

from util.ace import ruby_marshal as rm
from util.ace.ruby_marshal import RHash, RObject, RString, RUserDef

# Each class's instance variables in the order the editor writes them.
ORDER = {
    "RPG::Actor": "name face_index character_index initial_level face_name class_id character_name id description features note nickname max_level equips",
    "RPG::BaseItem::Feature": "code data_id value",
    "RPG::Animation": "animation2_hue position name animation2_name frames animation1_hue frame_max animation1_name timings id",
    "RPG::Animation::Frame": "cell_data cell_max",
    "RPG::Animation::Timing": "flash_duration se flash_color frame flash_scope",
    "RPG::SE": "name pitch volume",
    "RPG::ME": "name pitch volume",
    "RPG::BGM": "name volume pitch",
    "RPG::BGS": "name volume pitch",
    "RPG::Armor": "description name icon_index price note id features etype_id params atype_id",
    "RPG::Class": "name learnings id icon_index description features note exp_params params",
    "RPG::Class::Learning": "level skill_id note",
    "RPG::CommonEvent": "trigger name switch_id list id",
    "RPG::EventCommand": "indent code parameters",
    "RPG::MoveRoute": "wait skippable repeat list",
    "RPG::MoveCommand": "code parameters",
    "RPG::Enemy": "name gold battler_hue exp battler_name actions note id features params drop_items icon_index description",
    "RPG::Enemy::Action": "condition_type rating skill_id condition_param2 condition_param1",
    "RPG::Enemy::DropItem": "denominator kind data_id",
    "RPG::Item": "description name consumable occasion icon_index price scope animation_id note speed id features success_rate repeats tp_gain hit_type damage effects itype_id",
    "RPG::UsableItem::Damage": "type element_id formula variance critical",
    "RPG::UsableItem::Effect": "code data_id value1 value2",
    "RPG::Map": "parallax_name height events parallax_sx bgm tileset_id encounter_step width data bgs parallax_loop_y autoplay_bgm encounter_list autoplay_bgs parallax_show scroll_type parallax_loop_x disable_dashing parallax_sy display_name specify_battleback note battleback1_name battleback2_name",
    "RPG::Map::Encounter": "troop_id weight region_set",
    "RPG::Event": "id name x y pages",
    "RPG::Event::Page": "condition graphic move_type move_speed move_frequency move_route walk_anime step_anime direction_fix through priority_type trigger list",
    "RPG::Event::Page::Condition": "switch1_valid switch2_valid variable_valid self_switch_valid item_valid actor_valid switch1_id switch2_id variable_id variable_value self_switch_ch item_id actor_id",
    "RPG::Event::Page::Graphic": "tile_id character_name character_index direction pattern",
    "RPG::MapInfo": "scroll_x name expanded order scroll_y parent_id",
    "RPG::Skill": "message2 description occasion name message1 icon_index scope animation_id note mp_cost speed id features success_rate repeats tp_gain hit_type damage effects stype_id tp_cost required_wtype_id1 required_wtype_id2",
    "RPG::State": "message2 name priority icon_index message1 message4 restriction message3 note id features remove_at_battle_end remove_by_restriction auto_removal_timing min_turns max_turns remove_by_damage chance_by_damage remove_by_walking steps_to_remove release_by_damage",
    "RPG::System": "elements start_y airship test_battlers edit_map_id battle_end_me party_members start_x ship battler_hue sounds variables battle_bgm version_id start_map_id battler_name magic_number switches gameover_me game_title title_bgm terms test_troop_id boat skill_types weapon_types armor_types currency_unit window_tone japanese opt_draw_title opt_use_midi opt_transparent opt_followers opt_slip_death opt_extra_exp opt_display_tp battleback1_name battleback2_name title1_name title2_name opt_floor_death",
    "RPG::System::Vehicle": "start_y bgm start_x character_index character_name start_map_id",
    "RPG::System::TestBattler": "actor_id level equips",
    "RPG::System::Terms": "params etypes commands basic",
    "RPG::Tileset": "id name mode tileset_names flags note",
    "RPG::Troop": "members name pages id",
    "RPG::Troop::Page": "list span condition",
    "RPG::Troop::Page::Condition": "turn_valid actor_hp turn_a turn_ending enemy_hp switch_valid enemy_index actor_valid actor_id enemy_valid switch_id turn_b",
    "RPG::Troop::Member": "y hidden x enemy_id",
    "RPG::Weapon": "description name icon_index price animation_id note id features etype_id params wtype_id",
}


def obj(cls: str, **values) -> RObject:
    names = ORDER[cls].split()
    if set(values) != set(names):
        raise ValueError(f"{cls}: {sorted(set(names) ^ set(values))}")
    return RObject(cls, {"@" + name: values[name] for name in names})


def s(text: str) -> RString:
    return RString(text.encode())


def b(text: str) -> RString:
    """A binary string, as the editor writes default event names."""
    return RString(text.encode(), None)


def table(xsize: int, ysize: int, zsize: int, values: list[int]) -> RUserDef:
    dim = 3 if zsize > 1 else 2 if ysize > 1 else 1
    header = struct.pack("<5i", dim, xsize, ysize, zsize, xsize * ysize * zsize)
    return RUserDef("Table", header + struct.pack(f"<{len(values)}H", *values))


def tone(*values: float) -> RUserDef:
    # Packed as given; RV2JSON's Tone clamps when it loads.
    return RUserDef("Tone", struct.pack("<4d", *values))


def color(*values: float) -> RUserDef:
    return RUserDef("Color", struct.pack("<4d", *values))


def audio(cls: str, name: str, volume: int, pitch: int) -> RObject:
    return obj(cls, name=s(name), volume=volume, pitch=pitch)


def cmd(code: int, parameters: list, indent: int = 0) -> RObject:
    return obj("RPG::EventCommand", indent=indent, code=code, parameters=parameters)


def move(code: int, parameters: list | None = None) -> RObject:
    return obj("RPG::MoveCommand", code=code, parameters=parameters or [])


def feature(code: int, data_id: int, value: float) -> RObject:
    return obj("RPG::BaseItem::Feature", code=code, data_id=data_id, value=value)


def damage(kind: int, element: int, formula: str) -> RObject:
    return obj(
        "RPG::UsableItem::Damage",
        type=kind,
        element_id=element,
        formula=s(formula),
        variance=20,
        critical=kind == 1,
    )


def effect(code: int, data_id: int, value1: float, value2: float) -> RObject:
    return obj(
        "RPG::UsableItem::Effect",
        code=code,
        data_id=data_id,
        value1=value1,
        value2=value2,
    )


def move_route(commands: list[RObject], repeat: bool = False) -> RObject:
    return obj(
        "RPG::MoveRoute", wait=not repeat, skippable=True, repeat=repeat, list=commands
    )


def route_commands(route: RObject, indent: int = 0, share: bool = True) -> list:
    """Set Move Route and its 505 lines; the editor usually reuses the route's
    move command objects in them."""
    commands = route.ivars["@list"][:-1]
    lines = [cmd(205, [-1, route], indent)]
    for item in commands:
        copy = (
            item
            if share
            else move(item.ivars["@code"], list(item.ivars["@parameters"]))
        )
        lines.append(cmd(505, [copy], indent))
    return lines


def talk_list() -> list:
    heap = rm.HeapFloat(5e-324)
    return [
        cmd(101, [s("Actor1"), 0, 0, 2]),
        cmd(401, [s('\\C[2]アリス\\C[0]：「ようこそ、"旅人"さん。」')]),
        cmd(401, [s("タブ\tと制御\u0001文字、\\\\と/と 、🐱")]),
        cmd(102, [[s("はい"), s("いいえ")], 2]),
        cmd(402, [0, s("はい")]),
        cmd(401, [s("はいを選んだ。")], 1),
        cmd(0, [], 1),
        cmd(402, [1, s("いいえ")]),
        cmd(0, [], 1),
        cmd(404, []),
        cmd(103, [1, 2]),
        cmd(105, [2, False]),
        cmd(405, [s("スクロールする文章")]),
        cmd(108, [s("コメント")]),
        cmd(408, [s("コメントの続き")]),
        cmd(111, [12, s("$game_party.gold > 100")]),
        cmd(122, [1, 1, 0, 0, 2147483648], 1),
        cmd(122, [2, 2, 0, 0, -1073741825], 1),
        cmd(122, [3, 3, 0, 0, 1073741823], 1),
        cmd(0, [], 1),
        cmd(412, []),
        cmd(355, [s("p 'スクリプト'")]),
        cmd(655, [s("p 2")]),
        cmd(320, [1, s("新しい名前")]),
        cmd(324, [1, s("新しい二つ名")]),
        cmd(325, [1, s("新しいプロフィール")]),
        cmd(117, [2]),
        cmd(250, [audio("RPG::SE", "Chime2", 90, 100)]),
        # One heap Float object twice, as a loaded file keeps it.
        cmd(999, [heap, heap, -0.0, 1e16, 1e15, 100.0, 1e-5, 123456789012345.67, 0.1]),
        cmd(0, []),
    ]


def staging_list() -> list:
    route = move_route(
        [
            move(1),
            move(45, [s("$game_variables[1] += 1")]),
            move(44, [audio("RPG::SE", "Jump1", 80, 100)]),
            move(41, [s("People1"), 2]),
            move(0),
        ]
    )
    copied = move_route([move(4), move(45, [s("p '別の移動'")]), move(0)])
    return [
        cmd(132, [audio("RPG::BGM", "Battle2", 100, 100)]),
        cmd(133, [audio("RPG::ME", "Victory2", 100, 100)]),
        cmd(140, [0, audio("RPG::BGM", "Ship", 100, 100)]),
        cmd(140, [2, audio("RPG::BGM", "Airship", 100, 100)]),
        cmd(138, [tone(300, -300, 0.5, -255.0)]),
        cmd(223, [tone(68, -68, 0, 255.0), 60, True]),
        cmd(224, [color(255, 255, 255, 170), 8, True]),
        cmd(234, [1, tone(0, 0, 0, 0), 30, False]),
        cmd(236, [rm.sym("rain"), 5, 60, True]),
        cmd(241, [audio("RPG::BGM", "Town2", 90, 100)]),
        cmd(245, [audio("RPG::BGS", "Wind", 80, 100)]),
        cmd(249, [audio("RPG::ME", "Inn", 100, 100)]),
        *route_commands(route),
        *route_commands(copied, share=False),
        cmd(0, []),
    ]


def page_condition() -> RObject:
    return obj(
        "RPG::Event::Page::Condition",
        switch1_valid=False,
        switch2_valid=False,
        variable_valid=False,
        self_switch_valid=False,
        item_valid=False,
        actor_valid=False,
        switch1_id=1,
        switch2_id=1,
        variable_id=1,
        variable_value=0,
        self_switch_ch=b("A"),
        item_id=1,
        actor_id=1,
    )


def event(event_id: int, name: RString, x: int, y: int, lines: list) -> RObject:
    page = obj(
        "RPG::Event::Page",
        condition=page_condition(),
        graphic=obj(
            "RPG::Event::Page::Graphic",
            tile_id=0,
            character_name=s("People1") if event_id == 1 else b(""),
            character_index=2,
            direction=2,
            pattern=1,
        ),
        move_type=1,
        move_speed=3,
        move_frequency=3,
        move_route=move_route(
            [move(9), move(45, [s("p 'うろうろ'")]), move(0)], repeat=True
        ),
        walk_anime=True,
        step_anime=False,
        direction_fix=False,
        through=False,
        priority_type=1,
        trigger=0,
        list=lines,
    )
    return obj("RPG::Event", id=event_id, name=name, x=x, y=y, pages=[page])


def vehicle(name: str, character: str, index: int) -> RObject:
    return obj(
        "RPG::System::Vehicle",
        start_y=0,
        bgm=audio("RPG::BGM", name, 100, 100),
        start_x=0,
        character_index=index,
        character_name=s(character),
        start_map_id=0,
    )


def data() -> dict:
    """Every data file by name."""
    actors = [
        None,
        obj(
            "RPG::Actor",
            name=s("アリス"),
            face_index=0,
            character_index=0,
            initial_level=1,
            face_name=s("Actor1"),
            class_id=1,
            character_name=s("Actor1"),
            id=1,
            description=s("村の見習い剣士。\n二行目の説明。"),
            features=[feature(23, 0, 1.0), feature(22, 0, 0.95)],
            note=s("<tag: 値>"),
            nickname=s("見習い剣士"),
            max_level=99,
            equips=[1, 1, 0, 0, 0],
        ),
        obj(
            "RPG::Actor",
            name=s("Bob"),
            face_index=1,
            character_index=1,
            initial_level=5,
            face_name=s("Actor1"),
            class_id=1,
            character_name=s("Actor1"),
            id=2,
            description=s(""),
            features=[],
            note=s(""),
            nickname=s(""),
            max_level=50,
            equips=[0, 0, 0, 0, 0],
        ),
    ]
    classes = [
        None,
        obj(
            "RPG::Class",
            name=s("戦士"),
            learnings=[
                obj("RPG::Class::Learning", level=1, skill_id=1, note=s("最初の技"))
            ],
            id=1,
            icon_index=0,
            description=s(""),
            features=[feature(22, 0, 0.95), feature(22, 1, 0.05), feature(51, 1, 0.0)],
            note=s(""),
            exp_params=[30, 20, 30, 30],
            params=table(
                8,
                3,
                1,
                [
                    1,
                    500,
                    520,
                    0,
                    50,
                    55,
                    0,
                    0,
                    10,
                    12,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    40000,
                    0,
                    0,
                    7,
                ],
            ),
        ),
    ]
    skills = [
        None,
        obj(
            "RPG::Skill",
            message2=s(""),
            description=s('敵単体に"炎"のダメージを与える。'),
            occasion=1,
            name=s("ファイア"),
            message1=s("は%1を唱えた！"),
            icon_index=96,
            scope=1,
            animation_id=1,
            note=s(""),
            mp_cost=5,
            speed=0,
            id=1,
            features=[],
            success_rate=100,
            repeats=1,
            tp_gain=0,
            hit_type=2,
            damage=damage(1, 3, "100 + a.mat * 2 - b.mdf * 2"),
            effects=[effect(21, 0, 1.0, 0.0)],
            stype_id=1,
            tp_cost=0,
            required_wtype_id1=0,
            required_wtype_id2=0,
        ),
    ]
    items = [
        None,
        obj(
            "RPG::Item",
            description=s("HPを500回復する。"),
            name=s("ポーション"),
            consumable=True,
            occasion=0,
            icon_index=192,
            price=50,
            scope=7,
            animation_id=1,
            note=s(""),
            speed=0,
            id=1,
            features=[],
            success_rate=100,
            repeats=1,
            tp_gain=0,
            hit_type=0,
            damage=damage(0, 0, "0"),
            effects=[effect(11, 0, 0.0, 500.0), effect(21, 2, 0.5, 0.0)],
            itype_id=1,
        ),
    ]
    weapons = [
        None,
        obj(
            "RPG::Weapon",
            description=s("よく切れる剣。"),
            name=s("ロングソード"),
            icon_index=147,
            price=500,
            animation_id=1,
            note=s(""),
            id=1,
            features=[feature(31, 1, 0.0), feature(22, 0, 0.0)],
            etype_id=0,
            params=[0, 0, 10, 0, 0, 0, 0, 0],
            wtype_id=2,
        ),
    ]
    armors = [
        None,
        obj(
            "RPG::Armor",
            description=s(""),
            name=s("レザーシールド"),
            icon_index=160,
            price=80,
            note=s(""),
            id=1,
            features=[feature(22, 1, 0.0)],
            etype_id=1,
            params=[0, 0, 0, 5, 0, 0, 0, 0],
            atype_id=5,
        ),
    ]
    enemies = [
        None,
        obj(
            "RPG::Enemy",
            name=s("スライム"),
            gold=10,
            battler_hue=0,
            exp=5,
            battler_name=s("Slime"),
            actions=[
                obj(
                    "RPG::Enemy::Action",
                    condition_type=0,
                    rating=5,
                    skill_id=1,
                    condition_param2=0,
                    condition_param1=0,
                )
            ],
            note=s(""),
            id=1,
            features=[feature(22, 0, 0.95)],
            params=[250, 0, 15, 10, 10, 10, 10, 10],
            drop_items=[
                obj("RPG::Enemy::DropItem", denominator=2, kind=1, data_id=1),
                obj("RPG::Enemy::DropItem", denominator=1, kind=0, data_id=0),
                obj("RPG::Enemy::DropItem", denominator=1, kind=0, data_id=0),
            ],
            icon_index=0,
            description=s(""),
        ),
    ]
    troop_condition = obj(
        "RPG::Troop::Page::Condition",
        turn_valid=False,
        actor_hp=50,
        turn_a=0,
        turn_ending=False,
        enemy_hp=50,
        switch_valid=False,
        enemy_index=0,
        actor_valid=False,
        actor_id=1,
        enemy_valid=False,
        switch_id=1,
        turn_b=0,
    )
    troops = [
        None,
        obj(
            "RPG::Troop",
            members=[obj("RPG::Troop::Member", y=288, hidden=False, x=272, enemy_id=1)],
            name=s("スライム*2"),
            pages=[
                obj(
                    "RPG::Troop::Page",
                    list=[
                        cmd(101, [s(""), 0, 0, 2]),
                        cmd(401, [s("スライムが現れた！")]),
                        cmd(0, []),
                    ],
                    span=0,
                    condition=troop_condition,
                )
            ],
            id=1,
        ),
    ]
    states = [
        None,
        obj(
            "RPG::State",
            message2=s("は毒にかかった！"),
            name=s("毒"),
            priority=50,
            icon_index=2,
            message1=s("は毒にかかった！"),
            message4=s("の毒が消えた！"),
            restriction=0,
            message3=s(""),
            note=s(""),
            id=1,
            features=[feature(22, 7, -0.1)],
            remove_at_battle_end=False,
            remove_by_restriction=False,
            auto_removal_timing=0,
            min_turns=1,
            max_turns=1,
            remove_by_damage=False,
            chance_by_damage=100,
            remove_by_walking=False,
            steps_to_remove=100,
            release_by_damage=False,
        ),
    ]
    animations = [
        None,
        obj(
            "RPG::Animation",
            animation2_hue=0,
            position=1,
            name=s("斬撃"),
            animation2_name=s(""),
            frames=[
                obj(
                    "RPG::Animation::Frame",
                    cell_data=table(1, 8, 1, [0, 160, 192, 100, 0, 0, 255, 1]),
                    cell_max=1,
                )
            ],
            animation1_hue=0,
            frame_max=1,
            animation1_name=s("Attack1"),
            timings=[
                obj(
                    "RPG::Animation::Timing",
                    flash_duration=5,
                    se=audio("RPG::SE", "Slash1", 80, 100),
                    flash_color=color(255, 255, 255, 153),
                    frame=0,
                    flash_scope=1,
                )
            ],
            id=1,
        ),
    ]
    tilesets = [
        None,
        obj(
            "RPG::Tileset",
            id=1,
            name=s("フィールド"),
            mode=0,
            tileset_names=[
                s(n)
                for n in ("World_A1", "World_A2", "", "", "", "World_B", "", "", "")
            ],
            flags=table(
                16, 1, 1, [16, 15, 0, 6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 32768]
            ),
            note=s(""),
        ),
    ]
    common_events = [
        None,
        obj(
            "RPG::CommonEvent",
            trigger=0,
            name=s("会話"),
            switch_id=1,
            list=talk_list(),
            id=1,
        ),
        obj(
            "RPG::CommonEvent",
            trigger=0,
            name=s("演出"),
            switch_id=1,
            list=staging_list(),
            id=2,
        ),
    ]
    sounds = [
        audio("RPG::SE", name, 80, 100) for name in ("Cursor1", "Decision1", "Cancel2")
    ]
    terms = obj(
        "RPG::System::Terms",
        params=[
            s(t)
            for t in (
                "最大HP",
                "最大MP",
                "攻撃力",
                "防御力",
                "魔法力",
                "魔法防御",
                "敏捷性",
                "運",
            )
        ],
        etypes=[s(t) for t in ("武器", "盾", "頭", "身体", "装飾品")],
        commands=[s(f"コマンド{n}") for n in range(23)],
        basic=[s(t) for t in ("レベル", "Lv", "HP", "HP", "MP", "MP", "TP", "TP")],
    )
    system = obj(
        "RPG::System",
        elements=[s(""), s("物理"), s("炎")],
        start_y=5,
        airship=vehicle("Airship", "Vehicle", 3),
        test_battlers=[
            obj("RPG::System::TestBattler", actor_id=1, level=1, equips=[1, 1, 0, 0, 0])
        ],
        edit_map_id=1,
        battle_end_me=audio("RPG::ME", "Victory1", 100, 100),
        party_members=[1],
        start_x=3,
        ship=vehicle("Ship", "Vehicle", 1),
        battler_hue=0,
        sounds=sounds,
        variables=[s(""), s("所持金")],
        battle_bgm=audio("RPG::BGM", "Battle1", 100, 100),
        version_id=3000000000,
        start_map_id=1,
        battler_name=s("Slime"),
        magic_number=1234567890,
        switches=[s(""), s("オープニング済")],
        gameover_me=audio("RPG::ME", "Gameover1", 100, 100),
        game_title=s("テストゲーム"),
        title_bgm=audio("RPG::BGM", "Theme1", 100, 100),
        terms=terms,
        test_troop_id=1,
        boat=vehicle("Boat", "Vehicle", 0),
        skill_types=[s(""), s("魔法")],
        weapon_types=[s(""), s("剣")],
        armor_types=[s(""), s("盾")],
        currency_unit=s("G"),
        window_tone=tone(-34, 0, 68, -255.0),
        japanese=True,
        opt_draw_title=True,
        opt_use_midi=False,
        opt_transparent=False,
        opt_followers=True,
        opt_slip_death=False,
        opt_extra_exp=False,
        opt_display_tp=True,
        battleback1_name=s("Grassland"),
        battleback2_name=s("Grassland"),
        title1_name=s("Book"),
        title2_name=s(""),
        opt_floor_death=False,
    )
    map_infos = RHash(
        [
            (
                1,
                obj(
                    "RPG::MapInfo",
                    scroll_x=0,
                    name=s("はじまりの村"),
                    expanded=False,
                    order=1,
                    scroll_y=0,
                    parent_id=0,
                ),
            )
        ]
    )
    villager = [
        cmd(101, [s("People1"), 2, 0, 2]),
        cmd(401, [s("いい天気ですね。")]),
        cmd(0, []),
    ]
    sign = [cmd(117, [1]), cmd(0, [])]
    map001 = obj(
        "RPG::Map",
        parallax_name=b(""),
        height=3,
        events=RHash(
            [
                (1, event(1, b("EV001"), 1, 1, villager)),
                (2, event(2, s("看板"), 2, 1, sign)),
            ]
        ),
        parallax_sx=0,
        bgm=audio("RPG::BGM", "Town1", 100, 100),
        tileset_id=1,
        encounter_step=30,
        width=3,
        data=table(
            3,
            3,
            4,
            [2816 + n for n in range(9)] + [0] * 18 + [0, 0, 0, 0, 1, 0, 0, 0, 0],
        ),
        bgs=obj("RPG::BGS", name=b(""), volume=80, pitch=100),
        parallax_loop_y=False,
        autoplay_bgm=True,
        encounter_list=[
            obj("RPG::Map::Encounter", troop_id=1, weight=5, region_set=[1, 2])
        ],
        autoplay_bgs=False,
        parallax_show=False,
        scroll_type=0,
        parallax_loop_x=False,
        disable_dashing=False,
        parallax_sy=0,
        display_name=s("村"),
        specify_battleback=False,
        note=s(""),
        battleback1_name=b(""),
        battleback2_name=b(""),
    )
    # Scripts keep their own data in objects too, such as String-keyed
    # hashes; the editor stores equal keys apart, Ruby 3.4 stores them once.
    map001.ivars["@script_data"] = [RHash([(s("key"), 1)]), RHash([(s("key"), 2)])]
    scripts = [
        [
            1500000000,
            s("Vocab: <用語>?"),
            RString(zlib.compress('VOCAB = "用語"\r\n'.encode()), None),
        ],
        [
            12345678,
            s("Main"),
            RString(zlib.compress(b"rgss_main { SceneManager.run }\n"), None),
        ],
        [23456, s(""), RString(zlib.compress(b""), None)],
    ]
    return {
        "Actors": actors,
        "Classes": classes,
        "Skills": skills,
        "Items": items,
        "Weapons": weapons,
        "Armors": armors,
        "Enemies": enemies,
        "Troops": troops,
        "States": states,
        "Animations": animations,
        "Tilesets": tilesets,
        "CommonEvents": common_events,
        "System": system,
        "MapInfos": map_infos,
        "Map001": map001,
        "Scripts": scripts,
    }


# Plain classes, so Ruby's Marshal loads and dumps the data as it is.
RUBY_REDUMP = """
ARGV[1].split(",").each do |path|
  path.split("::").inject(Object) do |parent, name|
    parent.const_defined?(name, false) ? parent.const_get(name, false) : parent.const_set(name, Class.new)
  end
end
%w[Table Tone Color].each do |name|
  Object.const_set(name, Class.new do
    def self._load(data) = new.tap { |value| value.instance_variable_set(:@data, data) }
    def _dump(_level) = @data
  end)
end
Dir[File.join(ARGV[0], "*.rvdata2")].each do |file|
  File.binwrite(file, Marshal.dump(Marshal.load(File.binread(file))))
end
"""


def translate(source: Path, target: Path) -> None:
    """Translates a few fields of each kind into ``target``."""

    def load(name):
        return json.loads((source / (name + ".json")).read_text(encoding="utf-8"))

    def save(name, value):
        (target / (name + ".json")).write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    target.mkdir()
    texts = {
        "アリス": "Alice",
        "見習い剣士": "Apprentice",
        "村の見習い剣士。\n二行目の説明。": "A village apprentice.\nSecond line.",
        "Bob": "Robert",
        "戦士": "Warrior",
        "最初の技": "First skill",
        "ファイア": "Fire",
        "は%1を唱えた！": " casts %1!",
        "ポーション": "Potion",
        "HPを500回復する。": "Restores 500 HP.",
        "ロングソード": "Long Sword",
        "スライム": "Slime",
        "スライム*2": "Slime*2",
        "スライムが現れた！": "A slime appears!",
        "毒": "Poison",
        "の毒が消えた！": " is no longer poisoned!",
        "斬撃": "Slash",
        '\\C[2]アリス\\C[0]：「ようこそ、"旅人"さん。」': '\\C[2]Alice\\C[0]: "Welcome, traveler."',
        "はい": "Yes",
        "いいえ": "No",
        "はいを選んだ。": "You chose yes.",
        "スクロールする文章": "Scrolling text",
        "新しい名前": "New name",
        "新しい二つ名": "New title",
        "いい天気ですね。": "Nice weather.",
        "EV001": "Villager",
        "看板": "Sign",
        "村": "Village",
        "はじまりの村": "First Village",
        "テストゲーム": "Test Game",
        "物理": "Physical",
        "所持金": "Money",
        "オープニング済": "Opening seen",
        "魔法": "Magic",
        "最大HP": "Max HP",
        "武器": "Weapon",
        "コマンド0": "Fight",
        "レベル": "Level",
        "p '別の移動'": "p 'another move'",
        "$game_variables[1] += 1": "$game_variables[1] += 2",
    }

    def walk(value):
        if isinstance(value, str):
            return texts.get(value, value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    for path in sorted(source.glob("*.json")):
        name = path.stem
        value = load(name)
        changed = walk(value)
        if name == "System" and isinstance(changed, dict):
            changed["windowTone"] = [17, -300, 0, 0]
        if changed != value:
            save(name, changed)
    scripts = target / "scripts"
    scripts.mkdir()
    for path in (source / "scripts").iterdir():
        code = path.read_bytes()
        if "用語".encode() in code:
            (scripts / path.name).write_bytes(code.replace("用語".encode(), b"Terms"))


def patched_rv2json(checkout: Path, target: Path) -> str:
    """A copy of RV2JSON that runs on case-sensitive file systems and keeps a
    Change Vehicle BGM command's BGM, as the port does."""
    shutil.copytree(checkout, target, ignore=shutil.ignore_patterns(".git"))
    rpg = target / "rgssV3/rpg"
    if not (rpg / "mapinfoMV.rb").exists():
        shutil.copy(rpg / "mapInfoMV.rb", rpg / "mapinfoMV.rb")
    commands = rpg / "eventCommand.rb"
    code = commands.read_text(encoding="utf-8")
    fixed = code.replace(
        "\t\t\t\twhen 132 # Change Battle BGM",
        "\t\t\t\twhen 132, 140 # Change Battle BGM",
    )
    if fixed.count("when 132, 140") != 1:
        raise RuntimeError("RV2JSON's Change Battle BGM case was not found.")
    commands.write_text(fixed, encoding="utf-8")
    return str(target / "RV2JSON.rb")


def main(ruby: str, rv2json: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        script = patched_rv2json(Path(rv2json), work / "rv2json")
        (work / "Data").mkdir()
        files = data()
        for name, value in files.items():
            (work / "Data" / (name + ".rvdata2")).write_bytes(rm.dump(value))
        shutil.copytree(work / "Data", work / "redump")
        subprocess.run(
            [ruby, "-e", RUBY_REDUMP, str(work / "redump"), ",".join(ORDER)], check=True
        )
        for path in sorted((work / "redump").iterdir()):
            editor = (work / "Data" / path.name).read_bytes()
            if rm.dump(rm.load(editor)) != path.read_bytes():
                print("The port re-dumps differently from Ruby:", path.name)
        subprocess.run(
            [ruby, script, "-c", "-d", "Data", "-j", "ace_json"],
            cwd=work,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        translate(work / "ace_json", work / "translated")
        merged = work / "merged"
        shutil.copytree(work / "ace_json", merged)
        shutil.copytree(work / "translated", merged, dirs_exist_ok=True)
        subprocess.run(
            [ruby, script, "-u", "-d", "Data", "-j", "merged", "-o", "packed"],
            cwd=work,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        for name in ("Data", "ace_json", "translated", "packed"):
            shutil.rmtree(FIXTURE / name, ignore_errors=True)
            shutil.copytree(work / name, FIXTURE / name)


if __name__ == "__main__":
    main(*sys.argv[1:3])
