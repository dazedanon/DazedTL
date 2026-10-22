import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  acquireLock,
  gitIn,
  lockRef,
  releaseLock,
} from "../scripts/land-lock.mjs";

test("a landing waits for a live lock and takes over a dead or unrenewed one", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-land-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  git(["init", "-q"]);
  let clock = 0;
  const context = {
    now: () => clock,
    namespace: "pid:[1]",
    alive: (pid: number) => pid === 10,
  };
  const who = (pid: number) => ({ pid, branch: `work-${pid}`, worktree: dir });
  await acquireLock(git, who(9), context);
  // Pid 9 is gone, so the next lander takes over at once.
  const ten = await acquireLock(git, who(10), {
    ...context,
    wait: async () => assert.fail("waited for a dead holder"),
  });
  // Pid 10 lives; after 21 minutes without renewing, it loses the lock anyway.
  let waits = 0;
  const eleven = await acquireLock(git, who(11), {
    ...context,
    wait: async () => {
      waits++;
      clock += 7 * 60_000;
    },
  });
  assert.equal(waits, 3);
  assert.equal(eleven.holder.started, new Date(21 * 60_000).toISOString());
  // The holder it replaced cannot release the new one.
  assert.equal(releaseLock(git, ten), false);
  assert.equal(releaseLock(git, eleven), true);
  assert.equal(git(["rev-parse", "-q", "--verify", lockRef]).stdout, "");
});
