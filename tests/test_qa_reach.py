"""Whether players can reach a plugin's never-translated text."""

import tempfile
import unittest
from pathlib import Path

from tests.engine import engine_module

reach_module = engine_module("util/rpgmaker_qa_reach.py")

# The engine's own definitions, which plugins change or add to.
CORE = """
$gameMessage = null;
function Scene_Boot() {}
Scene_Boot.prototype.start = function() {};
function Window_Base() {}
Window_Base.prototype.drawText = function() {};
function SceneManager() {}
SceneManager.goto = function() {};
"""
PLUGINS = {
    # Its commands are never called and it only loads its data at boot,
    # like a synopsis plugin no event uses yet.
    "Synopsis": """
/*:
 * @command offer
 * @command show
 */
(() => {
    const _start = Scene_Boot.prototype.start;
    Scene_Boot.prototype.start = function() { load("data/Synopsis.json"); };
    window.Synopsis = { offer() {}, show() {} };
    PluginManager.registerCommand("Synopsis", "offer", () => {});
})();
""",
    # Adds an entry point another plugin calls, and swaps the engine's
    # message global, which ties no use to it.
    "Menus": """
SceneManager.callMenu = function(id) {};
window.$gameMessage = new Game_Message();
""",
    # Changes a screen, so it runs, and calls Menus.
    "Hud": """
Window_Base.prototype.drawText = function() { SceneManager.callMenu("Status"); };
""",
    "Clock": 'PluginManager.registerCommand("Clock", "SET", () => {});',
    "Notice": 'document.body.appendChild(document.createElement("div"));',
    "Retired": 'load("data/Legacy.json");',
}


class ReachTests(unittest.TestCase):
    def test_reach_follows_calls_uses_and_screen_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            game = Path(folder)
            (game / "data").mkdir()
            (game / "js/plugins").mkdir(parents=True)
            (game / "js/rmmz_scenes.js").write_text(CORE, encoding="utf-8")
            for name, source in PLUGINS.items():
                (game / f"js/plugins/{name}.js").write_text(source, encoding="utf-8")
            entries = reach_module.PluginList(
                {"name": name, "status": name != "Retired", "parameters": {}}
                for name in PLUGINS
            )
            reach = reach_module.Reach(game / "data", entries)
            reach.scan(
                "CommonEvents.json",
                [
                    None,
                    {
                        "list": [
                            {"code": 357, "parameters": ["Clock", "SET", "", {}]},
                            {"code": 355, "parameters": ['$gameMessage.add("x")']},
                        ]
                    },
                ],
            )
            states = {name: reach.plugin(name) for name in PLUGINS if name != "Retired"}
            self.assertEqual(
                {name: state for name, (state, _evidence) in states.items()},
                {
                    "Synopsis": "uncalled",
                    "Menus": "called",
                    "Hud": "runs",
                    "Clock": "called",
                    "Notice": "runs",
                },
            )
            # The running plugin that calls it, not the event script that
            # uses the engine's message global.
            self.assertIn("Hud", states["Menus"][1])
            self.assertIn("offer, show", states["Synopsis"][1])
            state, evidence = reach.data_file("Synopsis.json")
            self.assertEqual(state, "uncalled")
            self.assertIn("Synopsis", evidence)
            state, evidence = reach.data_file("Legacy.json")
            self.assertEqual(state, "unread")
            self.assertIn("Retired", evidence)
            self.assertEqual(reach.data_file("Other.json")[0], "unread")


if __name__ == "__main__":
    unittest.main()
