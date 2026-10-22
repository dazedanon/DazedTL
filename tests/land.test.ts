import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { acquireLock, redBuild, releaseLock } from "../scripts/land.mjs";

const holder = (pid: number, started: number) => ({
  pid,
  pidNamespace: "pid:[1]",
  branch: `work-${pid}`,
  worktree: "/w",
  started: new Date(started).toISOString(),
});

test("a landing waits for a live lock and takes over a dead or expired one", async () => {
  const dir = path.join(
    fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-")),
    "land.lock",
  );
  let clock = 0;
  const context = {
    now: () => clock,
    namespace: "pid:[1]",
    alive: (pid: number) => pid === 10,
    log: () => {},
  };
  await acquireLock(dir, holder(9, 0), context);
  // Pid 9 is gone, so the next lander takes over at once.
  await acquireLock(dir, holder(10, 0), {
    ...context,
    wait: async () => assert.fail("waited for a dead holder"),
  });
  // Pid 10 lives; after 21 minutes its lock is stale anyway.
  let waits = 0;
  await acquireLock(dir, holder(11, 0), {
    ...context,
    wait: async () => {
      waits++;
      clock += 7 * 60_000;
    },
  });
  assert.equal(waits, 3);
  releaseLock(dir, holder(10, 0));
  assert.equal(
    JSON.parse(fs.readFileSync(path.join(dir, "owner.json"), "utf8")).pid,
    11,
  );
  releaseLock(dir, holder(11, 0));
  assert.equal(fs.existsSync(dir), false);
  fs.rmSync(path.dirname(dir), { recursive: true });
});

test("a red dev build is rerun once, then stops the next landing unless a live branch fixes it", () => {
  const run = (
    id: number,
    conclusion: string | null,
    attempt = 1,
    status = "completed",
  ) => ({
    id,
    status,
    conclusion,
    run_attempt: attempt,
    created_at: new Date(id * 1000).toISOString(),
  });
  const decide = (runs: object[], claim: object | null = null) =>
    redBuild({
      runs,
      claim: claim as never,
      branch: "mine",
      branchExists: (name: string) => name !== "deleted",
      now: () => 10 * 60_000,
    }).action;
  const claim = (branch: string, at = 9 * 60_000) => ({
    branch,
    at: new Date(at).toISOString(),
  });
  assert.equal(decide([run(2, "cancelled"), run(1, "success")]), "land");
  assert.equal(decide([run(1, "failure")]), "rerun");
  // A newer run on dev decides; a rerun of this one would cancel it.
  assert.equal(
    decide([run(2, null, 1, "in_progress"), run(1, "failure")]),
    "land",
  );
  assert.equal(decide([run(1, "failure", 2)]), "own");
  assert.equal(decide([run(1, "failure", 2)], claim("other")), "warn");
  assert.equal(decide([run(1, "failure", 2)], claim("deleted")), "own");
  assert.equal(
    decide([run(1, "failure", 2)], claim("other", -3 * 3600_000)),
    "own",
  );
});
