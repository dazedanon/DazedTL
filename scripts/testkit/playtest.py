"""Runs the release playtest on a game folder headless, as the app's playtest
operation does, and prints what it found: each problem with its check, fix and
identity, then the tour's stops. The report stays in OUT/report.json.

    python scripts/testkit/playtest.py GAME OUT [--minutes N] [--stops FILE]

The engine is this checkout's; run another checkout's copy of this script to
play the game with that version.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/dazedtl/engine"))
sys.path.insert(0, str(ROOT / "backend"))

from dazedtl.plugins import service
from util.playtest.run import run


def main() -> None:
    parser = argparse.ArgumentParser(description=str(__doc__).split("\n", 1)[0])
    parser.add_argument("game", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--stops", type=Path, help="a JSON file of extra stops")
    args = parser.parse_args()
    game = args.game.resolve()
    stops = json.loads(args.stops.read_text(encoding="utf-8")) if args.stops else None
    report = run(
        game,
        game / "data",
        args.out,
        stops=stops,
        minutes=args.minutes,
        log=lambda message: print(f"  {message}", file=sys.stderr),
        kept=service.kept_settings(game),
        literals=service.kept_literals(game),
    )
    for problem in report["problems"]:
        texts = [
            item.get("pointer", item.get("line")) for item in problem.get("texts", [])
        ]
        print(
            problem["kind"],
            problem["check"],
            "fix:",
            problem["fix"],
            problem.get("identity", ""),
            json.dumps(problem.get("text", ""), ensure_ascii=False),
            texts,
            "|",
            problem["note"][:160],
        )
    for stop in report["coverage"]["stops"]:
        print("stop", stop["id"], stop["status"], stop.get("note", ""))
    print(f"Report: {Path(args.out).resolve() / 'report.json'}")


if __name__ == "__main__":
    main()
