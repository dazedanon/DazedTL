import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  parseGuide,
  searchGuide,
} from "../app/src/features/guide/guideDocument.ts";
import { guideSections } from "../app/src/ui/guideSections.ts";

const { Guide } = createRequire(import.meta.url)("../app/electron/guide.cjs");
const guide = fs.readFileSync(
  new URL("../docs/user-guide.md", import.meta.url),
  "utf8",
);

// Links such as #checkpoints-and-undo must open the same place in the app
// and on the forge, and the app's Learn more links must still find theirs.
test("guide sections take GitHub's anchors, and every link to one finds it", () => {
  const sample = parseGuide(
    "# Using it\n\nIntro.\n\n## Go back `here`?\n\n## Go back here\n\n### 1. Set up\n\nText about remotes.\n\n## Using it\n",
  );
  assert.equal(sample.title, "Using it");
  assert.deepEqual(
    sample.headings.map((heading) => [heading.id, heading.parent]),
    [
      ["go-back-here", undefined],
      ["go-back-here-1", undefined],
      ["1-set-up", "go-back-here-1"],
      ["using-it-1", undefined],
    ],
  );
  // A subsection that mentions the words brings its section along.
  assert.deepEqual(
    searchGuide(sample.headings, "REMOTES text").map((heading) => [
      heading.id,
      heading.match,
    ]),
    [
      ["go-back-here-1", false],
      ["1-set-up", true],
    ],
  );

  const ids = new Set(parseGuide(guide).headings.map((heading) => heading.id));
  for (const id of ["1-set-up", "checkpoints-and-undo", "game-updates"])
    assert.ok(ids.has(id), id);
  const links = [...guide.matchAll(/\]\(#([^)]+)\)/g)].map((match) => match[1]);
  assert.ok(links.length > 10);
  for (const id of [...links, ...guideSections]) assert.ok(ids.has(id), id);
});

test("the guide reads only its own file and images, and opens only web links and repository files", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-guide-"));
  fs.mkdirSync(path.join(root, "docs/media/nested"), { recursive: true });
  fs.mkdirSync(path.join(root, "release"));
  fs.writeFileSync(path.join(root, "docs/user-guide.md"), "# Guide\n");
  fs.writeFileSync(path.join(root, "docs/architecture.md"), "private");
  fs.writeFileSync(path.join(root, "docs/media/shot.png"), "png");
  fs.writeFileSync(path.join(root, "docs/media/notes.txt"), "text");
  fs.writeFileSync(path.join(root, "docs/media/nested/deep.png"), "png");
  fs.writeFileSync(path.join(root, "secret.png"), "secret");
  fs.symlinkSync("../../secret.png", path.join(root, "docs/media/leak.png"));
  fs.writeFileSync(path.join(root, "README.md"), "readme");
  fs.writeFileSync(
    path.join(root, "release/mirrors.json"),
    JSON.stringify([
      { type: "gitlab", url: "https://forge.example/team/DazedTL" },
      { type: "github", url: "https://github.example/team/DazedTL" },
    ]),
  );
  const reader = new Guide(root);
  assert.equal(reader.read(), "# Guide\n");
  assert.equal(
    reader.image("media/shot.png"),
    `data:image/png;base64,${Buffer.from("png").toString("base64")}`,
  );
  for (const source of [
    "user-guide.md",
    "architecture.md",
    "../README.md",
    "media/../architecture.md",
    "media/notes.txt",
    "media/nested/deep.png",
    "media/leak.png",
    "media/missing.png",
    path.join(root, "secret.png"),
    "media/shot.png?x",
    "",
    undefined,
  ])
    assert.throws(() => reader.image(source as string), String(source));

  assert.equal(reader.link("https://ntfy.sh/app"), "https://ntfy.sh/app");
  assert.equal(
    reader.link("../README.md#install"),
    "https://forge.example/team/DazedTL/-/blob/main/README.md#install",
  );
  for (const href of [
    "http://example.com",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "../../outside.md",
    "missing.md",
    "#section",
    "",
  ])
    assert.throws(() => reader.link(href), href);
  fs.rmSync(root, { recursive: true });
});
