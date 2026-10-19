"""The game's fixes from the release playtest: one plugin of DazedTL's own,
js/plugins/DazedTL_Fixes.js, which an assistant writes for what translated
text can't fix, such as a crash or a window sized for the Japanese, and one
line in js/main.js that loads it after the game's own plugins.

Keeping every fix in a plugin of its own leaves the game's plugin files and
plugin list as their own tasks applied them, and one file says what changed.
Nothing here writes the game: the playtest plays these files in place of the
game's, and DazedTL writes them only once that play finds nothing new broken.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

NAME = "DazedTL_Fixes"
# Paths under the game's web folder, which holds index.html.
PLUGIN = f"js/plugins/{NAME}.js"
MAIN = "js/main.js"
SETUP = "PluginManager.setup($plugins);"
LOADER = (
    f'$plugins.push({{ name: "{NAME}", status: true, '
    'description: "Fixes from DazedTL\'s release playtest", parameters: {} });'
)
LIMIT = 1_000_000
TEMPLATE = f"""//=============================================================================
// {NAME}.js
//=============================================================================
/*:
 * @plugindesc Fixes from DazedTL's release playtest.
 * @author DazedTL
 * @help js/main.js loads this plugin after the game's own plugins.
 * Each fix starts with a comment naming the problem it fixes.
 */
(() => {{
  "use strict";
}})();
"""


def with_loader(raw: bytes) -> bytes:
    """main.js with the line that loads the fixes before the engine sets up
    plugins; unchanged once it has it."""
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    main = raw.decode("utf-8-sig")
    if LOADER in main:
        return raw
    found = [match for match in re.finditer(r"^([ \t]*)" + re.escape(SETUP), main, re.M)]
    if len(found) != 1:
        raise ValueError(
            "This game's js/main.js does not set up its plugins with one "
            f"{SETUP} line, so DazedTL can't load fixes in it."
        )
    match = found[0]
    newline = "\r\n" if "\r\n" in main else "\n"
    loaded = main[: match.start()] + match.group(1) + LOADER + newline + main[match.start() :]
    return bom + loaded.encode("utf-8")


def check(source: bytes) -> str:
    """The fixes as text, once they compile as a browser script."""
    if len(source) > LIMIT:
        raise ValueError(f"{NAME}.js must stay under 1 MB.")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{NAME}.js must be UTF-8 text.") from exc
    node = shutil.which("node")
    if not node:
        raise ValueError(f"{NAME}.js can't be checked without the app's Node runtime.")
    # Compiled as a script, as the game loads it, without running it.
    response = subprocess.run(
        [node, "-e", COMPILE],
        input=source,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if response.returncode:
        message = response.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(
            f"{NAME}.js does not compile: " + (message[-1] if message else "unknown error")
        )
    return text


COMPILE = """
const vm = require("node:vm");
const source = require("node:fs").readFileSync(0, "utf8");
try {
  new vm.Script(source, { filename: "DazedTL_Fixes.js" });
} catch (error) {
  const line = /DazedTL_Fixes\\.js:(\\d+)/.exec(error.stack || "");
  console.error(`${error.message}${line ? ` (line ${line[1]})` : ""}`);
  process.exit(1);
}
"""


def served(web: Path, fixes: bytes, out: Path) -> dict[str, Path]:
    """The two files the playtest serves in place of the game's: the fixes,
    and main.js loading them; written under `out`, never into the game."""
    files = {PLUGIN: fixes, MAIN: with_loader((web / MAIN).read_bytes())}
    paths = {}
    for name, raw in files.items():
        path = out / "served" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        paths[name] = path
    return paths


def refusal(previous: dict[str, Any], report: dict[str, Any]) -> str:
    """Why fixes stay out of the game, or "" once a play with them in place
    still plays, stops nowhere new and no longer shows something the last
    playtest found."""
    if not report.get("played"):
        return (
            "With these fixes the game did not play: "
            + ((report.get("gaps") or ["it stopped before its title."])[-1])
        )
    stopped = [
        problem["note"]
        for problem in report["problems"]
        if problem["kind"] == "crash" and problem.get("new")
    ]
    if stopped:
        return "With these fixes the game stops where it did not before: " + stopped[0]
    if report["coverage"]["reached"] < (previous.get("coverage") or {}).get("reached", 0):
        return "With these fixes the playtest reached fewer places than before."
    if not (report.get("since") or {}).get("fixed"):
        return (
            "Nothing the last playtest found changed with these fixes, so they "
            "stay out of the game."
        )
    return ""
