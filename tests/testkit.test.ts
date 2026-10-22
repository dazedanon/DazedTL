import assert from "node:assert/strict";
import test from "node:test";
import { withRetry } from "../scripts/testkit/retry.mjs";

test("a check that fails once and then passes is a flake, and two failures still fail", async () => {
  const runs: number[] = [];
  const attempts =
    (...results: boolean[]) =>
    async (number: 1 | 2) => {
      runs.push(number);
      return results[number - 1];
    };
  assert.deepEqual(await withRetry(attempts(true, false)), {
    passed: true,
    flaky: false,
  });
  assert.deepEqual(runs, [1]);
  let cleared = 0;
  assert.deepEqual(await withRetry(attempts(false, true), () => cleared++), {
    passed: true,
    flaky: true,
  });
  assert.deepEqual(await withRetry(attempts(false, false)), {
    passed: false,
    flaky: false,
  });
  assert.equal(cleared, 1);
});
