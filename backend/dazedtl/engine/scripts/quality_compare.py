#!/usr/bin/env python3
"""Measure a change to translated text against a baseline on a frozen set.

build-set: the regression set from Text QA's correction export (util/quality_set).
estimate: what translating under variants and judging the runs would cost.
translate: one run of a variant; run again under the same ID to collect a
Batch or go on after a crash, which reuses every saved reply.
compare: judge two baseline runs and variant runs, calibrate the judge and
report each change against the noise floor (util/evaluation_quality).
Paid calls need --cap; the key comes on standard input with --key-stdin.
"""

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

from util import evaluation_quality as quality  # noqa: E402
from util import quality_set  # noqa: E402

VARIANT = "A variant's JSON file: name, method, provider, model, endpoint, execution, effort, prompt, context."
JUDGE = "The judge's JSON file: provider, model, endpoint, execution, effort, max_output_tokens, prompts."


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _secret(args) -> str:
    return sys.stdin.read().strip() if args.key_stdin else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-set", help="Build the regression set from a QA export.")
    build.add_argument("--export", required=True, type=Path, help="qa_corrections.py's export.")
    build.add_argument("--out", required=True, type=Path, help="The set to write, outside this checkout.")
    build.add_argument("--defects", type=int, default=quality_set.DEFECTS)
    build.add_argument("--controls", type=int, default=quality_set.CONTROLS)

    commands = {}
    for name, text in (
        ("estimate", "Print what runs and their judging would cost."),
        ("translate", "Translate the items as one run of a variant."),
        ("compare", "Judge runs and report each variant against the baseline."),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument("--set", required=True, type=Path, help="The regression set.")
        command.add_argument("--targeted", action="append", type=Path, default=[],
                             help="A targeted item file; repeat for more.")
        commands[name] = command
    commands["estimate"].add_argument("--variant", action="append", type=Path, required=True, help=VARIANT)
    commands["estimate"].add_argument("--repetitions", type=int, default=2)
    commands["estimate"].add_argument("--judge", type=Path, help=JUDGE)
    for name in ("translate", "compare"):
        command = commands[name]
        command.add_argument("--runs", required=True, type=Path, help="Where runs and comparisons are kept.")
        command.add_argument("--cap", type=float,
                             help="The approved most this run or comparison may spend, in dollars, counting what it spent before.")
        command.add_argument("--key-stdin", action="store_true", help="Read the API key from standard input.")
        command.add_argument("--wait", action="store_true", help="Wait for Batches to end.")
        command.add_argument("--poll", type=float, default=60.0, help="Seconds between Batch checks.")
    commands["translate"].add_argument("--variant", required=True, type=Path, help=VARIANT)
    commands["translate"].add_argument("--run-id", required=True)
    commands["translate"].add_argument("--retry-failed", action="store_true",
                                       help="Send requests that failed again.")
    commands["compare"].add_argument("--baseline", nargs=2, required=True, metavar="RUN_ID")
    commands["compare"].add_argument("--variant-run", action="append", default=[], metavar="RUN_ID",
                                     help="A variant's run; leave out to report the baseline and its noise floor.")
    commands["compare"].add_argument("--judge", type=Path, help=JUDGE)
    commands["compare"].add_argument("--stand-in-judge", action="store_true",
                                     help="Answer judgments from the set's labels: for dry runs; measures nothing.")
    commands["compare"].add_argument("--compare-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "build-set":
            header, items = quality_set.build(args.export, defects=args.defects, controls=args.controls)
            out = quality_set.write(args.out, header, items)
            print(f"Wrote {len(items)} items, set version {header['version']}, to {out}")
            print(json.dumps(header["counts"], indent=1, ensure_ascii=False))
            for reason in header["skipped"]:
                print(f"Skipped {reason}")
            return 0
        loaded = quality.load(args.set, args.targeted)
        if args.command == "estimate":
            values = [quality.variant(_json(path)) for path in args.variant]
            config = quality.judge(_json(args.judge)) if args.judge else None
            print(quality.render_plan(quality.estimate_plan(loaded, values, config, args.repetitions)))
            return 0
        if args.command == "translate":
            value = quality.variant(_json(args.variant))
            plan = quality.estimate_plan(loaded, [value], None, 1)
            print(quality.render_plan(plan))
            transport = quality.ProviderTransport(value, _secret(args))
            status = quality.translate(loaded, value, args.runs, args.run_id, transport=transport,
                                       cap=args.cap, wait=args.wait, retry_failed=args.retry_failed,
                                       poll_seconds=args.poll)
            print(json.dumps(status))
            return 0
        if args.judge:
            config = quality.judge(_json(args.judge))
        elif args.stand_in_judge:
            # It never sends a request; the connection only names it.
            config = quality.judge({"provider": "openai", "model": "stand-in", "execution": "live", "keyless": True})
        else:
            raise ValueError("Name the judge with --judge, or --stand-in-judge for a dry run")
        transport = None if args.stand_in_judge else quality.ProviderTransport(config, _secret(args))
        result = quality.compare(loaded, args.runs, args.baseline, args.variant_run, config,
                                 compare_id=args.compare_id, transport=transport, cap=args.cap,
                                 stand_in=args.stand_in_judge, wait=args.wait, poll_seconds=args.poll)
        print(quality.render(result))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
