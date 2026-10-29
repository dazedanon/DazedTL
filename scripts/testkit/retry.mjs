// The flake rule CI, the release check and landings share: a check that fails
// is run once more, and one that passes the second time is reported as a
// flake, not as passed or failed outright; either report names what failed.
import os from "node:os";

const quietLimit = 5 * 60_000;
const quietPoll = 10_000;

// Where `node scripts/test.mjs` names a failure: a Python problem's header
// (tests/run.py), units it never ran, a Node test's cross, and the budget.
const pythonFailure = /^(?:FAIL|ERROR|CRASH|UNEXPECTED SUCCESS): /;
const failure = new RegExp(
  `${pythonFailure.source}|^\\s*✖ (?!failing tests:)|^\\d+ units were never run\\.|^Test runtime budget exceeded`,
);
/** The last `count` lines of a command's output. */
export const tail = (/** @type {string} */ text, count = 40) =>
  text.trimEnd().split("\n").slice(-count).join("\n");

/**
 * The lines of a test run's output that name what failed, each once and in
 * order, a Node test without its time; at most `limit`, then how many more.
 */
export function failedTests(/** @type {string} */ text, limit = 10) {
  const names = [
    ...new Set(
      text
        .split(/\r?\n/)
        .filter((line) => failure.test(line))
        .map((line) => line.trim().replace(/ \(\d[\d.]*m?s\)$/, "")),
    ),
  ];
  return names.length > limit
    ? [...names.slice(0, limit), `and ${names.length - limit} more`]
    : names;
}

/**
 * What a failed test run's report shows: the failures it names, then the
 * first one's details, its Python problem or else Node's failing tests, since
 * the summary that ends the run hides both; a run with no details, such as one
 * over its budget, or that names nothing, shows its last `count` lines.
 */
export function failureReport(/** @type {string} */ text, count = 40) {
  const names = failedTests(text);
  if (!names.length) return tail(text, count);
  const all = text.trimEnd().split(/\r?\n/);
  let first = all.findIndex((line) => pythonFailure.test(line));
  if (first < 0) {
    const node = all.findIndex((line) => line.startsWith("✖ failing tests:"));
    if (node >= 0)
      for (first = node + 1; first < all.length && !all[first].trim(); first++);
  }
  return [
    "Failed:",
    ...names.map((name) => `  ${name}`),
    ...(first < 0
      ? ["End of run:", tail(text, count)]
      : ["First failure:", ...all.slice(first, first + count)]),
  ].join("\n");
}

/**
 * Runs `attempt` (resolving whether it passed) and, if it failed, once more.
 * `between` runs before the second attempt, to clear what the first left.
 * @param {(number: 1 | 2) => Promise<boolean>} attempt
 * @param {() => void} [between]
 * @returns {Promise<{ passed: boolean, flaky: boolean }>}
 */
export async function withRetry(attempt, between = () => {}) {
  if (await attempt(1)) return { passed: true, flaky: false };
  between();
  const passed = await attempt(2);
  return { passed, flaky: passed };
}

/** The machine's one-minute load average per processor. */
export const loadPerProcessor = () =>
  os.loadavg()[0] / os.availableParallelism();

/**
 * Runs the test suite under the flake rule. The suite holds itself to a
 * wall-clock budget and its probes to deadlines, which a machine other
 * sessions' builds and scenarios oversubscribe misses whatever the code does,
 * so the second run first waits, at most five minutes, for the load to fall to
 * one task per processor.
 * @param {() => Promise<{ status: number, output: string }>} run
 * @param {{ wait: (ms: number) => Promise<unknown>, log: (line: string) => void, load?: () => number }} deps
 * @returns {Promise<{ passed: boolean, flaky: boolean, outputs: string[] }>}
 */
export async function testsWithRetry(
  run,
  { wait, log, load = loadPerProcessor },
) {
  /** @type {string[]} */
  const outputs = [];
  const outcome = await withRetry(async (attempt) => {
    if (attempt === 2) {
      let busy = load();
      if (busy > 1)
        log(
          `The machine is busy (load ${busy.toFixed(1)} per processor); running the tests again once it quiets, waiting at most ${quietLimit / 60_000} minutes.`,
        );
      for (let waited = 0; busy > 1 && waited < quietLimit;) {
        await wait(quietPoll);
        waited += quietPoll;
        busy = load();
      }
    }
    const result = await run();
    outputs.push(result.output);
    return result.status === 0;
  });
  return { ...outcome, outputs };
}
