// Keeps each document short enough to help its reader. While every change
// added its own behavior to the docs, the user guide grew fourfold in three
// weeks into a catalog of edge cases, so each document has a word limit,
// counted as `wc -w` counts. A document over its limit is cut to what its
// reader needs to act; moving text to another document doesn't help, since
// each has a limit, and a limit rises only when the user agrees.
//
// Each pending release notes line has one too. Lines grew as every follow-up
// fix appended its conditions to the line it extended, until 2.69.0 shipped
// lines of 110 and 125 words that players reading Settings > Updates or the
// Discord post could not follow, so a line keeps only the main change.
import fs from "node:fs";
import path from "node:path";
import { NOTES, parseNotes } from "./changelog.mjs";
import { root } from "./dependencies.mjs";

const limits = {
  "AGENTS.md": 1000,
  "README.md": 1200,
  "docs/architecture.md": 9950,
  "docs/development.md": 3000,
  "docs/text-qa-redesign.md": 4000,
  "docs/translation-contract.md": 3200,
  "docs/ui-design.md": 2400,
  "docs/user-guide.md": 3980,
};
const noteLineLimit = 25;

const problems = [];
for (const file of fs.globSync("docs/*.md", { cwd: root })) {
  const name = file.replaceAll("\\", "/");
  if (!Object.hasOwn(limits, name))
    problems.push(
      `${name} has no word limit; add one in scripts/docs.mjs, once no other document serves its reader.`,
    );
}
let over = false;
for (const [name, limit] of Object.entries(limits)) {
  const file = path.join(root, name);
  if (!fs.existsSync(file)) {
    problems.push(`${name} is gone; remove its limit from scripts/docs.mjs.`);
    continue;
  }
  const words = fs.readFileSync(file, "utf8").split(/\s+/).filter(Boolean);
  if (words.length > limit) {
    problems.push(
      `${name} has ${words.length} words, over its limit of ${limit}.`,
    );
    over = true;
  }
}
try {
  const notes = fs.readFileSync(path.join(root, NOTES), "utf8");
  for (const { items } of parseNotes(notes))
    for (const text of items) {
      const words = text.split(/\s+/).filter(Boolean).length;
      if (words > noteLineLimit)
        problems.push(
          `${NOTES}: "${text}" has ${words} words, over a line's limit of ${noteLineLimit}; keep only the main change, as docs/development.md#release-notes says.`,
        );
    }
} catch (error) {
  problems.push(String(error instanceof Error ? error.message : error));
}
for (const problem of problems) console.error(problem);
if (over)
  console.error(
    "Cut what the reader doesn't need to act, as the documentation list in docs/development.md says, or ask the user to raise the limit.",
  );
if (problems.length) process.exitCode = 1;
