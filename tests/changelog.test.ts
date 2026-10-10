import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  addRelease,
  parseChangelog,
  parseNotes,
} from "../scripts/changelog.mjs";
import { releaseNotes } from "../scripts/update.mjs";

test("release notes become the changelog's newest entry, and malformed notes stop the release", () => {
  const notes = parseNotes(
    "<!-- pending -->\n### Fixed\n- **Set up:** works.\n\n### Added\n- New thing.\n",
  );
  assert.deepEqual(
    notes.map((section) => section.kind),
    ["Added", "Fixed"],
  );
  const first = addRelease("", {
    version: "1.0.0",
    date: "2026-01-01",
    sections: notes,
    link: "https://example/v1.0.0",
  });
  const second = addRelease(first, {
    version: "1.1.0",
    date: "2026-02-01",
    sections: [{ kind: "Changed", items: ["Faster."] }],
    link: "https://example/compare/v1.0.0...v1.1.0",
  });
  assert.deepEqual(parseChangelog(second), [
    {
      version: "1.1.0",
      date: "2026-02-01",
      sections: [{ kind: "Changed", items: ["Faster."] }],
    },
    {
      version: "1.0.0",
      date: "2026-01-01",
      sections: [
        { kind: "Added", items: ["New thing."] },
        { kind: "Fixed", items: ["**Set up:** works."] },
      ],
    },
  ]);
  assert.match(
    second,
    /\n\[1\.1\.0\]: https:\/\/example\/compare\/v1\.0\.0\.\.\.v1\.1\.0\n\[1\.0\.0\]: https:\/\/example\/v1\.0\.0\n$/,
  );
  for (const malformed of [
    "### Improved\n- x\n",
    "Fixed a bug.\n",
    "### Fixed\n",
  ])
    assert.throws(() => parseNotes(malformed));
});

test("an update shows the notes of every release after the installed one", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-notes-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const entry = (version: string) => ({
    version,
    date: "2026-01-01",
    sections: [{ kind: "Fixed", items: [`In ${version}.`] }],
  });
  let changelog = "";
  for (const version of ["2.0.0", "2.0.1", "2.1.0"])
    changelog = addRelease(changelog, { ...entry(version), link: "L" });
  fs.writeFileSync(path.join(dir, "CHANGELOG.md"), changelog);
  fs.mkdirSync(path.join(dir, "release"));
  fs.writeFileSync(
    path.join(dir, "release/notes.md"),
    "### Added\n- In the beta.\n",
  );
  const versions = (after: string | null, upTo: string) =>
    releaseNotes(dir, after, upTo).map((release) => release.version);

  assert.deepEqual(versions("2.0.0", "2.1.0"), ["2.1.0", "2.0.1"]);
  assert.deepEqual(versions(null, "2.0.1"), ["2.0.1"]);
  // After Go back, the newer version it left names no range.
  assert.deepEqual(versions("2.1.0", "2.0.1"), ["2.0.1"]);
  assert.deepEqual(versions("2.1.0", "2.2.0-beta.1"), ["2.2.0-beta.1"]);
  assert.deepEqual(releaseNotes(dir, null, "2.2.0-beta.1")[0].sections, [
    { kind: "Added", items: ["In the beta."] },
  ]);
  fs.rmSync(path.join(dir, "CHANGELOG.md"));
  assert.deepEqual(versions("2.0.0", "2.1.0"), []);
});
