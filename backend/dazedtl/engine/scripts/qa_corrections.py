#!/usr/bin/env python3
"""Count what Text QA corrected and export the corrections as a dataset.

report: corrected lines by kind and per 1,000 translated lines, game by game,
with the fixes that recur most. export: the same corrections as versioned
JSON Lines (util/qa_corrections.py). Both only read QA records and games.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Standalone helpers use the same bundled runtime and shared resources as the app.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from dazedtl.compatibility.runtime import activate
activate()
# A task reads its game where the project list says it is now.
from dazedtl.compatibility.text import install_locations  # noqa: E402
install_locations()

from util import qa_corrections  # noqa: E402

TARGETS = (
    "Task folders, receipts runs, folders holding task folders (such as the app "
    "workspace's engine/workflows) or game folders (their .dazedtl/qa-receipts)."
)
WORKSPACE = "The app workspace, searched for the tasks of the game folders named."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="Print corrections per kind and per 1,000 lines.")
    export = sub.add_parser("export", help="Write the corrections as JSON Lines.")
    for command in (report, export):
        command.add_argument("targets", nargs="+", type=Path, help=TARGETS)
        command.add_argument("--workspace", type=Path, help=WORKSPACE)
    report.add_argument("--top", type=int, default=10, help="Recurring groups to list.")
    export.add_argument("--out", required=True, type=Path, help="The JSONL file to write.")
    args = parser.parse_args()
    try:
        origins, skipped = qa_corrections.find_origins(args.targets, args.workspace)
        out = (
            qa_corrections.check_destination(args.out, origins, args.workspace)
            if args.command == "export" else None
        )
        corrections = qa_corrections.collect(origins, skipped)
        if out is None:
            sys.stdout.write(qa_corrections.render(qa_corrections.summary(corrections, args.top)))
            return 0
        rows = qa_corrections.export(corrections, out)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {rows} corrections from {len(corrections.games)} games to {out}")
    for reason in corrections.skipped:
        print(f"Skipped {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
