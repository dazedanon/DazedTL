import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  addRelease,
  mergeNotes,
  notesTemplate,
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

test("release notes list every release and count the new ones", (t) => {
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
  const notes = (upTo: string, after: string | null) => {
    const { releases, recent } = releaseNotes(dir, upTo, after);
    return [releases.map((release) => release.version), recent];
  };

  assert.deepEqual(notes("2.1.0", "2.0.0"), [["2.1.0", "2.0.1", "2.0.0"], 2]);
  assert.deepEqual(notes("2.0.1", null), [["2.0.1", "2.0.0"], 1]);
  // After Go back, the newer version it left names no range.
  assert.deepEqual(notes("2.0.1", "2.1.0"), [["2.0.1", "2.0.0"], 1]);
  assert.deepEqual(notes("2.2.0-beta.1", "2.1.0"), [
    ["2.2.0-beta.1", "2.1.0", "2.0.1", "2.0.0"],
    1,
  ]);
  assert.deepEqual(
    releaseNotes(dir, "2.2.0-beta.1", null).releases[0].sections,
    [{ kind: "Added", items: ["In the beta."] }],
  );
  fs.rmSync(path.join(dir, "CHANGELOG.md"));
  assert.deepEqual(notes("2.1.0", "2.0.0"), [[], 0]);
});

test("parallel branches' notes merge by kind, and a release's filed notes stay filed", () => {
  const base = "<!-- c -->\n\n### Fixed\n\n- Old.\n";
  const merged = mergeNotes(
    base,
    `${base}- Ours.\n\n### Added\n\n- Our feature.\n`,
    `${base}- Theirs.\n\n### Added\n\n- Their feature.\n`,
  );
  assert.deepEqual(parseNotes(merged), [
    { kind: "Added", items: ["Their feature.", "Our feature."] },
    { kind: "Fixed", items: ["Old.", "Theirs.", "Ours."] },
  ]);
  // dev released and emptied the notes; the branch adds one line.
  assert.deepEqual(
    parseNotes(mergeNotes(base, `${base}- New.\n`, notesTemplate)),
    [{ kind: "Fixed", items: ["New."] }],
  );
});

test("a branch's notes never bring back a line a release filed, and a reworded one stops the merge", () => {
  const shipped = "**Translate:** a run stops on rejected requests.";
  const base = `${notesTemplate}\n### Changed\n\n- ${shipped}\n`;
  const released = parseChangelog(
    addRelease("", {
      version: "2.52.0",
      date: "2026-10-28",
      sections: [{ kind: "Changed", items: [shipped] }],
      link: "L",
    }),
  );
  const reworded = `${notesTemplate}\n### Changed\n\n- ${shipped} Its cost still counts.\n`;
  // The branch rewords a line dev released since: keeping the rewording
  // would repeat the released entry, and dropping it would lose the change.
  assert.throws(
    () => mergeNotes(base, reworded, notesTemplate, released),
    /rewords a line 2\.52\.0 released: "\*\*Translate:\*\* a run stops on rejected requests\."[^]*Its cost still counts\./,
  );
  // Without a release, the same edit merges as before.
  assert.deepEqual(parseNotes(mergeNotes(base, reworded, base)), [
    { kind: "Changed", items: [`${shipped} Its cost still counts.`] },
  ]);
  // A line added word for word as released stops it too.
  assert.throws(
    () => mergeNotes(notesTemplate, base, notesTemplate, released),
    /adds a line 2\.52\.0 released/,
  );
  // Dropping the released line and adding one under another heading is no
  // rewording.
  assert.deepEqual(
    parseNotes(
      mergeNotes(
        base,
        `${notesTemplate}\n### Fixed\n\n- New.\n`,
        notesTemplate,
        released,
      ),
    ),
    [{ kind: "Fixed", items: ["New."] }],
  );
});
