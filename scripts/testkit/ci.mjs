// The scenario runs CI's workflow lists, which the release check runs too and
// the behavior tests hold to the scenarios scripts/scenario.mjs builds.
import fs from "node:fs";
import path from "node:path";
import { root } from "../dependencies.mjs";
import { scenarios } from "./scenarios.mjs";

/**
 * The scenario runs in `workflow`'s matrix, each a name and the options after
 * it. Throws when the matrix leaves out a scenario, so none lands without CI.
 */
export function ciScenarios(
  workflow = fs.readFileSync(
    path.join(root, ".github/workflows/ci.yml"),
    "utf8",
  ),
) {
  const block = /\n(\s+)scenarios:\n((?:\1\s+- .+\n)+)/.exec(
    workflow.replaceAll("\r\n", "\n"),
  );
  if (!block) throw new Error("CI's workflow lists no scenarios.");
  const runs = [];
  for (const line of block[2].trim().split("\n")) {
    let previous = "";
    for (const word of line
      .replace(/^\s*- /, "")
      .trim()
      .split(/\s+/)) {
      if (word.startsWith("--") || previous.startsWith("--"))
        runs[runs.length - 1].push(word);
      else runs.push([word]);
      previous = word;
    }
  }
  const missing = Object.keys(scenarios).filter(
    (name) => !runs.some(([run]) => run === name),
  );
  if (missing.length)
    throw new Error(
      `CI runs no ${missing.join(", ")} scenario; add it to .github/workflows/ci.yml.`,
    );
  return runs;
}
