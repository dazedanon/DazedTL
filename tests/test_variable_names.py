"""Which System.json variable names a game's plugins draw, which the database
pass translates, and which code may look up by name, which it never does."""

import json
import tempfile
import unittest
from pathlib import Path

from util import rpgmaker_variable_names as names

DRAWS = "Window_Base.prototype.drawText($dataSystem.variables[id], 0, 0, 200);\n"


def header(*tags):
    return "\n".join(("/*:", *(f" * {tag}" for tag in tags), " */", ""))


def drawn(plugins, sources, commands=(), extra=None):
    """The drawn ids of a game with these plugins, their files and common
    event commands, whose variables are 好感度 and 作業用."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        data, js = root / "data", root / "js/plugins"
        data.mkdir()
        js.mkdir(parents=True)
        (root / "js/plugins.js").write_text(
            f"var $plugins =\n{json.dumps(plugins, ensure_ascii=False)};\n", "utf-8"
        )
        for name, source in sources.items():
            (js / f"{name}.js").write_text(source, "utf-8")
        files = {
            "System.json": {"variables": ["", "好感度", "作業用"]},
            "CommonEvents.json": [
                None,
                {
                    "id": 1,
                    "list": [
                        {"code": code, "parameters": list(parameters)}
                        for code, *parameters in commands
                    ],
                },
            ],
            **(extra or {}),
        }
        for name, document in files.items():
            (data / name).write_text(json.dumps(document, ensure_ascii=False), "utf-8")
        return names.data_drawn(data)


def plugin(name, **parameters):
    return {"name": name, "status": True, "parameters": parameters}


class VariableNameTests(unittest.TestCase):
    def test_settings_and_structs_name_what_a_plugin_draws(self):
        # An MV setting's name may hold spaces, and an MZ HUD lists its
        # windows as structs.
        self.assertEqual(
            drawn(
                [plugin("Hud", **{"Display Variable": "1"})],
                {"Hud": header("@param Display Variable", "@type variable") + DRAWS},
            ),
            {1},
        )
        windows = json.dumps([json.dumps({"variableId": "1"})])
        struct = "/*~struct~Win:\n * @param variableId\n * @type variable\n */\n"
        self.assertEqual(
            drawn(
                [plugin("Hud", Windows=windows)],
                {
                    "Hud": header("@param Windows", "@type struct<Win>[]")
                    + struct
                    + DRAWS
                },
            ),
            {1},
        )

    def test_a_name_code_may_look_up_stays(self):
        # Hud draws variable 1, 好感度; each case also looks it up by name.
        hud = [plugin("Hud", hudVariable="1")]
        source = {"Hud": header("@param hudVariable", "@type variable") + DRAWS}
        self.assertEqual(drawn(hud, source), {1})
        lookup = "return $dataSystem.variables.indexOf('好感度');"
        for case, plugins, sources, commands, extra in (
            ("a code setting", [plugin("Gauge", **{"Value JS": lookup})], {}, (), None),
            ("an MV command's quoted word", [], {}, [(356, 'ShowVar "好感度"')], None),
            (
                "a note tag",
                [],
                {},
                (),
                {"Actors.json": [None, {"id": 1, "note": "<GaugeVar:好感度>"}]},
            ),
        ):
            with self.subTest(case):
                self.assertEqual(
                    drawn(hud + plugins, {**source, **sources}, commands, extra),
                    frozenset(),
                )


if __name__ == "__main__":
    unittest.main()
