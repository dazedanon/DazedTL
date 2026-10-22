// The release check's flake rule, as CI's: a check that fails is run once
// more, and one that passes the second time is reported as a flake, not as
// passed or failed outright.

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
