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
  const run = (...args: string[]) => {
    const result = git(args);
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  };
  run("init", "-q", "-b", "dev");
  const commit = (message: string) => {
    run(
      ...["-c", "user.name=t", "-c", "user.email=t@t"],
      ...["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"],
      ...["commit", "-q", "--allow-empty", "-m", message],
    );
    return run("rev-parse", "HEAD");
  };
  const approved = commit("approved");
  run("switch", "-q", "-c", "side");
  const side = commit("side");
  run("switch", "-q", "dev");
  // A landing took the lock first and moved dev.
  const landed = commit("landed");
  const shipped: Array<string | undefined> = [];
  const ship = async (head?: string) => void shipped.push(head);
  await assert.rejects(lockedRelease(git, dir, approved, ship), DevMoved);
  assert.notEqual(git(["rev-parse", "--verify", "--quiet", lockRef]).status, 0);
  // Neither a name, which always matches dev, nor a commit dev never held is
  // a race to ask again about.
  for (const head of ["dev", landed.slice(0, 12), side]) {
    const refused = await lockedRelease(git, dir, head, ship).catch((e) => e);
    assert.ok(refused instanceof Error && !(refused instanceof DevMoved), head);
  }
  assert.deepEqual(shipped, []);
  await lockedRelease(git, dir, landed.toUpperCase(), ship);
  await lockedRelease(git, dir, undefined, ship);
  assert.deepEqual(shipped, [landed, undefined]);
});
