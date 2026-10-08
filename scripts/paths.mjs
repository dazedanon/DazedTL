// Keeps tracked paths short enough to unpack from a Windows ZIP; the budget is
// explained under Distribution and updates in docs/architecture.md.
import { execFileSync } from "node:child_process";
import { root } from "./dependencies.mjs";

const limit = 185;
const long = execFileSync("git", ["ls-files", "-z"], {
  cwd: root,
  encoding: "utf8",
})
  .split("\0")
  .filter((file) => file.length > limit);
for (const file of long) console.error(`${file.length} ${file}`);
if (long.length) {
  console.error(`Shorten these paths to ${limit} characters or fewer.`);
  process.exitCode = 1;
}
