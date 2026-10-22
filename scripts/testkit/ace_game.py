"""Converts and encrypts a VX Ace test game the way its developer's tools
would, with this checkout's own Ace conversion, for scripts/testkit/games.mjs.

    python scripts/testkit/ace_game.py extract|pack|encrypt GAME

extract writes the game's Data as JSON into ace_json, pack writes ace_json
back into Data (its data files, not its scripts) and removes it, and encrypt
packs Data into an encrypted Game.rgss3a, as shipped games have it, and
removes Data.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    sys.path[:0] = [str(ROOT / "backend/dazedtl/engine"), str(ROOT)]
    from util.ace import actions
    from util.system import remove_tree

    from tests.rgssad_archives import archive_v3

    command, game = sys.argv[1], Path(sys.argv[2])
    if command == "extract":
        actions.run(game, "ace_extract", log=lambda _line: None)
    elif command == "pack":
        # The data files only, as the editor saves them: packing the scripts
        # from their file names would rename one whose name a file can't
        # hold, a change the developer never made.
        exports = (game / "ace_json").glob("*.json", case_sensitive=False)
        data = [path.stem for path in exports]
        if not data:
            sys.exit(f"{game} has no ace_json to pack.")
        actions.run(game, "ace_pack", log=lambda _line: None, only=data)
        remove_tree(game / "ace_json")
    elif command == "encrypt":
        data = game / "Data"
        entries = [
            ("Data\\" + path.name, path.read_bytes())
            for path in sorted(data.iterdir())
            if path.is_file()
        ]
        (game / "Game.rgss3a").write_bytes(archive_v3(entries, seed=7))
        remove_tree(data)
    else:
        sys.exit(f"Unknown command {command}.")


if __name__ == "__main__":
    main()
