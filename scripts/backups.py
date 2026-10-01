#!/usr/bin/env python3
"""Inspect and restore portable game backups without a running app or its profile."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from dazedtl.translation import backups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path)
    parser.add_argument("--legacy-backups", type=Path, help="Optional older profile backup directory for this project")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list")
    verify = commands.add_parser("verify")
    verify.add_argument("--id", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--id", required=True)
    restore.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        game = args.game.expanduser().resolve(strict=True)
        legacy = args.legacy_backups or backups.store_path(game) / "legacy-not-configured"
        if args.action == "list":
            result = backups.catalog(game, legacy)
        else:
            path = backups.lookup(game, legacy, args.id)
            if args.action == "verify":
                value = backups.verify(path)
                result = {"id": value["id"], "verified_files": len(value["files"])}
            else:
                destination = args.destination.expanduser().absolute()
                if destination.resolve().is_relative_to(game) or game.is_relative_to(destination.resolve()):
                    raise ValueError("Choose a new restore folder outside the selected game.")
                result = backups.restore(path, destination)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
