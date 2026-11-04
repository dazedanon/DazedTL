// Sums up what landings' independent reviews caught and which bugs got past
// them, so the review rule in the dazedtl-land skill is tuned on data. It
// reads every landed review record in the shared Git directory's
// dazedtl-reviews.jsonl and every commit on dev whose `Introduced-by:`
// trailer names the commit that brought in the bug it fixes (AGENTS.md),
// and matches that commit to the landing that holds it.
// Usage: node scripts/review-stats.mjs
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { gitIn } from "./land-lock.mjs";
import { readReview } from "./land.mjs";

/**
 * @typedef {{ range: string, reviews: number, findings: { kind?: string, outcome: string, review: number }[], commits: string[] }} Landing
 * A landed range, with how many independent reviews it ran (0 for one its
 * author reviewed, from before independent reviews), their findings and
 * the full hashes of its commits.
 * @typedef {{ fix: string, introduced: string }} Escape
 * A fix commit and the full hash of the commit that brought its bug in.
 */

/**
 * Landings and escaped bugs by how many reviews each landing ran, findings
 * by the review that reported them, their kind and outcome, and the bugs
 * whose commit no logged landing holds.
 * @param {Landing[]} landings
 * @param {Escape[]} escapes
 */
export function summarize(landings, escapes) {
  /** @type {Map<number, { landings: number, escapes: number }>} */
  const byReviews = new Map();
  /** @type {Map<number, Record<string, { fixed: number, dismissed: number }>>} */
  const rounds = new Map();
  /** @type {Map<string, Landing>} */
  const owner = new Map();
  for (const landing of landings) {
    for (const commit of landing.commits) owner.set(commit, landing);
    const group = byReviews.get(landing.reviews) ?? { landings: 0, escapes: 0 };
    group.landings += 1;
    byReviews.set(landing.reviews, group);
    for (const finding of landing.findings) {
      const round = rounds.get(finding.review) ?? {};
      const kind = (round[finding.kind ?? "unsorted"] ??= {
        fixed: 0,
        dismissed: 0,
      });
      kind[/** @type {"fixed" | "dismissed"} */ (finding.outcome)] += 1;
      rounds.set(finding.review, round);
    }
  }
  const escaped = [];
  const before = [];
  for (const escape of escapes) {
    const landing = owner.get(escape.introduced);
    if (!landing) {
      before.push(escape);
      continue;
    }
    /** @type {{ landings: number, escapes: number }} */ (
      byReviews.get(landing.reviews)
    ).escapes += 1;
    escaped.push({ ...escape, range: landing.range, reviews: landing.reviews });
  }
  const sorted = (/** @type {Map<number, any>} */ map) =>
    [...map].sort(([a], [b]) => a - b);
  return {
    byReviews: sorted(byReviews),
    rounds: sorted(rounds),
    escaped,
    before,
  };
}

/**
 * The landings in the reviews log, each with its range's commits.
 * @param {ReturnType<typeof gitIn>} git
 * @param {string} log
 * @returns {Landing[]}
 */
function landed(git, log) {
  if (!fs.existsSync(log)) return [];
  return fs
    .readFileSync(log, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const row = JSON.parse(line);
      let review = { reviews: 0, findings: [] };
      try {
        review = readReview(line);
      } catch {
        // An author's review, from before independent reviews.
      }
      const commits = git(["rev-list", row.range]).stdout.split("\n");
      return { range: row.range, ...review, commits: commits.filter(Boolean) };
    });
}

/**
 * Every fix on dev naming the commit that brought its bug in; a name Git
 * can't find is listed apart.
 * @param {ReturnType<typeof gitIn>} git
 */
function fixes(git) {
  const escapes = [];
  const unknown = [];
  const rows = git([
    "log",
    "dev",
    "--format=%H %(trailers:key=Introduced-by,valueonly,separator=%x20)",
  ]).stdout;
  for (const line of rows.split("\n")) {
    const [fix, ...named] = line.trim().split(/\s+/);
    for (const name of named) {
      const introduced = git([
        "rev-parse",
        "--verify",
        "--quiet",
        `${name}^{commit}`,
      ]).stdout.trim();
      if (introduced) escapes.push({ fix, introduced });
      else unknown.push({ fix, name });
    }
  }
  return { escapes, unknown };
}

function main() {
  const git = gitIn(process.cwd());
  const common = path.resolve(
    git(["rev-parse", "--git-common-dir"]).stdout.trim(),
  );
  const { escapes, unknown } = fixes(git);
  const summary = summarize(
    landed(git, path.join(common, "dazedtl-reviews.jsonl")),
    escapes,
  );
  const short = (/** @type {string} */ hash) => hash.slice(0, 8);
  const count = (/** @type {number} */ n, /** @type {string} */ noun) =>
    `${n} ${noun}${n === 1 ? "" : "s"}`;
  console.log("Landings by independent reviews run:");
  for (const [reviews, group] of summary.byReviews)
    console.log(
      `  ${reviews || "none"}: ${count(group.landings, "landing")}, ${count(group.escapes, "bug")} got past them`,
    );
  console.log("Findings by review and kind, fixed/dismissed:");
  for (const [review, kinds] of summary.rounds)
    console.log(
      `  review ${review}: ${Object.entries(kinds)
        .map(([kind, count]) => `${kind} ${count.fixed}/${count.dismissed}`)
        .join(", ")}`,
    );
  for (const escape of summary.escaped)
    console.log(
      `Fix ${short(escape.fix)}: bug from ${short(escape.introduced)}, landed in ${escape.range.split("..").map(short).join("..")} after ${escape.reviews || "no"} independent reviews`,
    );
  if (summary.before.length)
    console.log(
      `${count(summary.before.length, "fixed bug")} came from before the reviews log.`,
    );
  for (const { fix, name } of unknown)
    console.log(`Fix ${short(fix)} names ${name}, which Git can't find.`);
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) main();
