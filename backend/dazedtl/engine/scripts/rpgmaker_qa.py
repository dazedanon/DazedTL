#!/usr/bin/env python3
"""Prepare and coordinate local AI-helper RPG Maker translation QA."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Standalone helpers use the same bundled runtime and shared resources as the app.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from dazedtl.compatibility.runtime import activate
activate()

from util import rpgmaker_qa  # noqa: E402
from util.rpgmaker_qa_manifest import FOCUSES  # noqa: E402


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--game-root", required=True, type=Path)
    prepare.add_argument("--data", required=True, type=Path)
    prepare.add_argument("--focus", required=True, choices=sorted(FOCUSES))
    prepare.add_argument("--output-root", required=True, type=Path)

    for name in ("status", "advance", "finalize"):
        command = sub.add_parser(name)
        command.add_argument("--task", required=True, type=Path)
        if name in {"advance", "finalize"}:
            command.add_argument(
                "--skip-declined",
                action="store_true",
                help="Report declined bundles no other reviewer took as not reviewed.",
            )
    rebuild = sub.add_parser("rebuild-deep")
    rebuild.add_argument("--task", required=True, type=Path)
    rebuild.add_argument("--output-root", type=Path)
    decide = sub.add_parser(
        "decide", help="Record a choice every reviewer follows, such as narration tense."
    )
    decide.add_argument("--task", required=True, type=Path)
    decide.add_argument("--worker", required=True)
    decide.add_argument("--key", required=True)
    decide.add_argument("--choice", required=True)
    decide.add_argument("--source", default="")
    decide.add_argument("--translation", default="")
    decisions = sub.add_parser("decisions", help="Print the recorded decisions.")
    decisions.add_argument("--task", required=True, type=Path)
    next_cmd = sub.add_parser("next")
    next_cmd.add_argument("--task", required=True, type=Path)
    next_cmd.add_argument("--worker", required=True)
    next_cmd.add_argument(
        "--bundle", help="Claim this waiting bundle, such as one another reviewer declined."
    )
    show = sub.add_parser("show", help="Print a bundle compactly for review.")
    show.add_argument("--task", required=True, type=Path)
    show.add_argument("--bundle", required=True)
    brief = sub.add_parser("brief", help="Print one reviewer role's fixed brief.")
    brief.add_argument("--task", required=True, type=Path)
    brief.add_argument("--role", required=True, choices=rpgmaker_qa.QA_ROLES)
    context = sub.add_parser(
        "context", help="Print read-only game text around an identity or command list."
    )
    context.add_argument("--task", required=True, type=Path)
    context.add_argument("--at", required=True)
    context.add_argument("--radius", type=int, default=12)
    accept = sub.add_parser("accept")
    accept.add_argument("--task", required=True, type=Path)
    accept.add_argument("--result", required=True, type=Path)
    release = sub.add_parser("release")
    release.add_argument("--task", required=True, type=Path)
    release.add_argument("--bundle", required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        task, state = rpgmaker_qa.prepare_task(
            args.game_root, args.data, args.focus, args.output_root
        )
        _print({"task": str(task), "status": state})
    elif args.command == "status":
        _print(rpgmaker_qa.status(args.task))
    elif args.command == "next":
        bundle = rpgmaker_qa.next_bundle(args.task, args.worker, args.bundle)
        _print(bundle or {"bundle": None, "status": rpgmaker_qa.status(args.task)})
    elif args.command == "accept":
        _print(rpgmaker_qa.accept_result(args.task, args.result))
    elif args.command == "release":
        _print(rpgmaker_qa.release_bundle(args.task, args.bundle))
    elif args.command == "advance":
        _print(rpgmaker_qa.advance(args.task, args.skip_declined))
    elif args.command == "show":
        print(rpgmaker_qa.render_bundle(args.task, args.bundle), end="")
    elif args.command == "brief":
        print(rpgmaker_qa.brief(args.task, args.role))
    elif args.command == "context":
        print(rpgmaker_qa.context_view(args.task, args.at, args.radius))
    elif args.command == "rebuild-deep":
        task, state = rpgmaker_qa.rebuild_deep_from_screen(
            args.task, args.output_root
        )
        _print({"task": str(task), "status": state})
    elif args.command == "decide":
        _print(rpgmaker_qa.record_decision(
            args.task, args.key, args.choice, args.worker, args.source, args.translation
        ))
    elif args.command == "decisions":
        _print(rpgmaker_qa._decisions(Path(args.task).expanduser().resolve()))
    elif args.command == "finalize":
        _print(rpgmaker_qa.finalize(args.task, args.skip_declined))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
