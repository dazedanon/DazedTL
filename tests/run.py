"""Runs the Python suite in worker interpreters at once, with one report.

scripts/test.mjs runs `python tests/run.py --times <file>`. Each test module
is a unit, and a slow one is split into shards of its tests; the workers take
the slowest units first, by the times the previous run saved in <file>. A
module that starts a background process when imported (tests/probe.py) stays
whole, so its process starts once. Each worker is a fresh interpreter with the
suite's own options that runs units until its input ends, then exits as any
test run does.
"""

import importlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Isolated mode (-I) leaves the checkout off the import path.
sys.path.insert(0, str(ROOT))
LINE = "-" * 70


def interpreter():
    """This interpreter with the options it was started with."""
    return [sys.executable, *sys.orig_argv[1 : len(sys.orig_argv) - len(sys.argv)]]


def run_unit(unit):
    """Runs one unit's tests and describes the result."""
    from tests.probe import Background

    started = time.perf_counter()
    try:
        module = importlib.import_module(unit["module"])
    except Exception:
        return {
            **unit,
            "import": time.perf_counter() - started,
            "seconds": 0.0,
            "background": False,
            "dots": "E",
            "run": 0,
            "problems": [
                ["ERROR", f"importing {unit['module']}", traceback.format_exc()]
            ],
            "skipped": 0,
            "durations": [],
        }
    imported = time.perf_counter()
    tests = list(_flatten(unittest.defaultTestLoader.loadTestsFromModule(module)))
    # A part takes a run of neighboring tests, so a class's fixtures mostly
    # run once.
    count, shard, shards = len(tests), unit["shard"], unit["shards"]
    chosen = tests[count * shard // shards : count * (shard + 1) // shards]
    stream = io.StringIO()
    result = unittest.TextTestResult(stream, descriptions=True, verbosity=1)
    unittest.TestSuite(chosen).run(result)
    describe = result.getDescription
    return {
        "module": unit["module"],
        "import": imported - started,
        "seconds": time.perf_counter() - imported,
        "background": any(
            isinstance(value, Background) for value in vars(module).values()
        ),
        "dots": stream.getvalue().strip(),
        "run": result.testsRun,
        "problems": [
            [
                kind,
                describe(test) if isinstance(test, unittest.TestCase) else str(test),
                text,
            ]
            for kind, found in (("ERROR", result.errors), ("FAIL", result.failures))
            for test, text in found
        ]
        + [
            ["UNEXPECTED SUCCESS", describe(test), ""]
            for test in result.unexpectedSuccesses
        ],
        "skipped": len(result.skipped),
        "durations": [[name, seconds] for name, seconds in result.collectedDurations],
    }


def _flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flatten(test)
        else:
            yield test


def worker():
    """Runs the units named on standard input, one JSON line each, and answers
    each on the original standard output. What tests print goes to standard
    error instead, and the processes they start read the null device, as the
    app's own do (dazedtl.system.private_stdin)."""
    answers = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    # The suite's setup, as every test module has it.
    import tests

    # Its stacks at the deadline go to the file the runner names, which it
    # shows once the worker has exited, apart from the other workers' stacks.
    # It stays open until the worker exits, for faulthandler to write.
    stacks = open(sys.argv[sys.argv.index("--stacks") + 1], "w", encoding="utf-8")  # noqa: SIM115
    tests.stop_at_deadline(stacks)
    # Importable once the suite's setup put the backend on the path.
    private_stdin = importlib.import_module("dazedtl.system").private_stdin
    for line in private_stdin():
        answers.write(json.dumps(run_unit(json.loads(line))) + "\n")
        answers.flush()


def plan(modules, times, workers):
    """The units to run, slowest first: a module the saved `times` found slow
    split into shards, a module without a saved time first."""
    known = [times[name]["seconds"] for name in modules if name in times]
    target = max(0.25, sum(known) / workers / 2)
    units = []
    for name in modules:
        saved = times.get(name)
        if saved is None:
            units.append((math.inf, {"module": name, "shard": 0, "shards": 1}))
            continue
        shards = 1
        if not saved["background"]:
            shards = max(1, min(workers, math.ceil(saved["seconds"] / target)))
        units += [
            (
                saved["seconds"] / shards,
                {"module": name, "shard": shard, "shards": shards},
            )
            for shard in range(shards)
        ]
    return [unit for _, unit in sorted(units, key=lambda item: -item[0])]


def main():
    started = time.perf_counter()
    # The suite keeps its compiled modules between runs (scripts/test.mjs);
    # the app's rule drops those of modules tests wrote into temporary
    # folders, which never come back.
    sys.path.insert(0, str(ROOT / "backend"))
    importlib.import_module("dazedtl.system").prune_bytecode()
    store = Path(sys.argv[sys.argv.index("--times") + 1])
    modules = sorted(
        f"tests.{path.stem}" for path in (ROOT / "tests").glob("test_*.py")
    )
    try:
        times = json.loads(store.read_text(encoding="utf-8"))
    except OSError, ValueError:
        times = {}
    workers = min(8, os.process_cpu_count() or 1, len(modules))
    queue = plan(modules, times, workers)
    results, crashed, files = [], [], []
    lock = threading.Lock()

    def drive():
        descriptor, stacks = tempfile.mkstemp(prefix="dazedtl-worker-")
        os.close(descriptor)
        with lock:
            files.append(stacks)
        process = subprocess.Popen(
            [*interpreter(), __file__, "--worker", "--stacks", stacks],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert process.stdin and process.stdout
        with process:
            while True:
                with lock:
                    if not queue:
                        break
                    unit = queue.pop(0)
                try:
                    process.stdin.write(json.dumps(unit) + "\n")
                    process.stdin.flush()
                    result = json.loads(process.stdout.readline())
                except OSError, ValueError:
                    # The worker exited, or wrote something else.
                    with lock:
                        crashed.append((unit["module"], stacks))
                    break
                with lock:
                    results.append(result)
                    print(result["dots"], end="", file=sys.stderr, flush=True)
            try:
                process.stdin.close()
            except OSError:
                pass  # The worker is gone already.

    threads = [threading.Thread(target=drive) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    print(file=sys.stderr)
    try:
        return report(results, crashed, queue, store, time.perf_counter() - started)
    finally:
        for stacks in files:
            Path(stacks).unlink(missing_ok=True)


def report(results, crashed, unrun, store, seconds):
    """Prints the run as unittest does and saves each module's time."""
    for kind, description, text in (
        problem for result in results for problem in result["problems"]
    ):
        print(f"{'=' * 70}\n{kind}: {description}\n{LINE}\n{text}", file=sys.stderr)
    for module, stacks in crashed:
        print(
            f"{'=' * 70}\nCRASH: a worker running {module} exited\n{LINE}\n"
            + Path(stacks).read_text(encoding="utf-8", errors="replace"),
            file=sys.stderr,
        )
    if unrun and not crashed:
        print(f"{len(unrun)} units were never run.", file=sys.stderr)
    durations = sorted(
        (item for result in results for item in result["durations"]),
        key=lambda item: -item[1],
    )[:5]
    print("Slowest test durations\n" + LINE, file=sys.stderr)
    for name, elapsed in durations:
        print(f"{elapsed:.3f}s     {name}", file=sys.stderr)
    total = sum(result["run"] for result in results)
    print(f"\n{LINE}\nRan {total} tests in {seconds:.3f}s\n", file=sys.stderr)
    problems = sum(len(result["problems"]) for result in results)
    skipped = sum(result["skipped"] for result in results)
    passed = not problems and not crashed and not unrun
    notes = [f"problems={problems}"] if problems else []
    notes += [f"crashed={len(crashed)}"] if crashed else []
    notes += [f"skipped={skipped}"] if skipped else []
    status = "OK" if passed else "FAILED"
    print(f"{status} ({', '.join(notes)})" if notes else status, file=sys.stderr)
    if passed:
        # A module's time counts its import once, however many parts it ran
        # in, so splitting it does not make it look slower the next time.
        times = {}
        for result in results:
            saved = times.setdefault(
                result["module"],
                {"seconds": 0.0, "import": 0.0, "background": result["background"]},
            )
            saved["seconds"] += result["seconds"]
            saved["import"] = max(saved["import"], result["import"])
        for saved in times.values():
            saved["seconds"] += saved.pop("import")
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(times, indent=1, sort_keys=True), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    if "--worker" in sys.argv:
        worker()
    else:
        sys.exit(main())
