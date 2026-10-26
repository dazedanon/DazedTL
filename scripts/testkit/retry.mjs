// The flake rule CI, the release check and landings share: a check that fails
// is run once more, and one that passes the second time is reported as a
// flake, not as passed or failed outright.
import os from "node:os";

const quietLimit = 5 * 60_000;
const quietPoll = 10_000;

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
