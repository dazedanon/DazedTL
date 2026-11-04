import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gitIn, lockRef } from "../scripts/land-lock.mjs";
import {
  DevMoved,
  lockedRelease,
  publishRelease,
} from "../scripts/release.mjs";

const changelog = `# Changelog

## [2.1.0] - 2026-10-31

### Added

- **Progress:** a new view.

### Fixed

- **Set up:** an old symptom.

## [2.0.0] - 2026-10-01

### Fixed

- **Settings:** an older fix.

[2.1.0]: https://github.test/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.test/releases/tag/v2.0.0
`;

/** GitHub with tag v2.1.0, and with its Release when `existing` is given. */
function github(existing?: { id: number }) {
  const writes: Array<{ route: string; method?: string; body?: any }> = [];
  return {
    writes,
    read: async (route: string) =>
      route === "repos/o/r/git/ref/tags/v2.1.0"
        ? { ref: "refs/tags/v2.1.0" }
        : route === "repos/o/r/releases/tags/v2.1.0"
          ? (existing ?? null)
          : null,
    write: async (
      route: string,
      request: { method?: string; body?: unknown },
    ) => {
      writes.push({ route, ...request });
      return { html_url: "https://github.test/releases/tag/v2.1.0" };
    },
  };
}

test("a release's GitHub Release carries its version's notes and is marked latest, and a rerun updates it", async () => {
  const fresh = github();
  assert.equal(
    await publishRelease({
      version: "2.1.0",
      changelog,
      repository: "o/r",
      ...fresh,
    }),
    "https://github.test/releases/tag/v2.1.0",
  );
  assert.equal(fresh.writes.length, 1);
  const [created] = fresh.writes;
  assert.equal(created.route, "repos/o/r/releases");
  assert.equal(created.method, undefined);
  assert.equal(created.body.tag_name, "v2.1.0");
  assert.equal(created.body.make_latest, "true");
  assert.equal(
    created.body.body,
    "### Added\n\n- **Progress:** a new view.\n\n### Fixed\n\n- **Set up:** an old symptom.",
  );

  const rerun = github({ id: 7 });
  await publishRelease({
    version: "2.1.0",
    changelog,
    repository: "o/r",
    ...rerun,
  });
  assert.deepEqual(
    rerun.writes.map(({ route, method }) => [route, method]),
    [["repos/o/r/releases/7", "PATCH"]],
  );
  assert.equal(rerun.writes[0].body.body, created.body.body);
});

test("a GitHub Release is not created for a tag GitHub lacks", async () => {
  const missing = github();
  await assert.rejects(
    publishRelease({
      version: "2.0.0",
      changelog,
      repository: "o/r",
      ...missing,
    }),
    /push it first/,
  );
  assert.equal(missing.writes.length, 0);
});

test("a release given --head refuses once locked if a landing moved dev past it, and releases the lock", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-release-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const git = gitIn(dir);
  const run = (...args: string[]) => git(args).stdout.trim();
  run("init", "-q", "-b", "dev");
  const commit = (message: string) => {
    run(
      "-c",
      "user.name=t",
      "-c",
      "user.email=t@t",
      "commit",
      "-q",
      "--allow-empty",
      "-m",
      message,
    );
    return run("rev-parse", "HEAD");
  };
  const approved = commit("approved");
  // A landing took the lock first and moved dev.
  const landed = commit("landed");
  let released = 0;
  const task = async () => void released++;
  await assert.rejects(lockedRelease(git, dir, approved, task), DevMoved);
  assert.equal(released, 0);
  assert.notEqual(git(["rev-parse", "--verify", "--quiet", lockRef]).status, 0);
  // A name always matches dev, so it is no approval.
  await assert.rejects(lockedRelease(git, dir, "dev", task), /commit hash/);
  await lockedRelease(git, dir, landed.slice(0, 12), task);
  await lockedRelease(git, dir, undefined, task);
  assert.equal(released, 2);
});
