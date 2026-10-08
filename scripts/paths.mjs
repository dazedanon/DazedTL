// Keeps tracked paths unpackable and importable on Windows: short enough for a
// Windows ZIP, and distinct without letter case. Both rules are explained under
// Distribution and updates in docs/architecture.md.
import path from "node:path";
import { execFileSync } from "node:child_process";
import { root } from "./dependencies.mjs";

const limit = 185;
// Extensions an import may leave out, in Vite's default resolve order.
const modules = /\.(mjs|js|mts|ts|jsx|tsx|json)$/;
const files = execFileSync("git", ["ls-files", "-z"], {
  cwd: root,
  encoding: "utf8",
})
  .split("\0")
  .filter(Boolean);

const long = files.filter((file) => file.length > limit);
for (const file of long) console.error(`${file.length} ${file}`);
if (long.length)
  console.error(`Shorten these paths to ${limit} characters or fewer.`);

// Windows treats names that differ only in case as one file, so an import such
// as "./Review" can load review.ts instead of Review.tsx.
const spellings = new Map();
const add = (name) => {
  const key = name.toLowerCase();
  spellings.set(key, (spellings.get(key) || new Set()).add(name));
};
for (const file of files) {
  let dir = file;
  while ((dir = path.posix.dirname(dir)) !== ".") add(dir);
  add(file);
  if (modules.test(file)) add(file.replace(modules, ""));
}
const clashes = [...spellings.values()].filter((names) => names.size > 1);
for (const names of clashes) console.error([...names].join("  "));
if (clashes.length)
  console.error("Rename these so they differ by more than letter case.");

if (long.length || clashes.length) process.exitCode = 1;
