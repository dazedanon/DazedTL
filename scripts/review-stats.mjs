// Sums up what landings' independent reviews caught and which bugs got past
// them, so the review rule in the dazedtl-land skill is tuned on data. It
// reads every landed review record in the shared Git directory's reviews log
// and every commit on dev whose `Introduced-by:` trailer names the commit
// that brought in the bug it fixes (AGENTS.md), and matches that commit to
// the landing that holds it.
// Usage: node scripts/review-stats.mjs
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { gitIn } from "./land-lock.mjs";
import { readReview, reviewLog } from "./land.mjs";

/**
 * @typedef {{ range: string, reviews: number, findings: { kind?: string, outcome: string, review: number }[] }} Logged
 * A landed range with how many independent reviews it ran, 0 for one its
 * author reviewed before independent reviews, and their findings.
 * @typedef {Logged & { commits: string[] }} Landing
 * A logged landing with the full hashes of its range's commits.
 * @typedef {{ fix: string, introduced: string }} Escape
 * A fix commit and the full hash of the commit that brought its bug in.
 */

/**
 * The landings in a reviews log's text; a line that can't be read is
 * listed apart instead of ending the report.
 * @param {string} text
 */
export function loggedLandings(text) {
  /** @type {Logged[]} */
  const landings = [];
  const unread = [];
  for (const [index, line] of text.split("\n").entries()) {
    if (!line.trim()) continue;
    const where = `Reviews log line ${index + 1}`;
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      unread.push(`${where} is not JSON.`);
      continue;
    }
    if (typeof row?.range !== "string") {
      unread.push(`${where} has no range.`);
      continue;
    }
    // Before independent reviews, records named no reviewer.
    if (row.reviewer === undefined) {
      landings.push({ range: row.range, reviews: 0, findings: [] });
      continue;
    }
    try {
      const { reviews, findings } = readReview(line);
      landings.push({ range: row.range, reviews, findings });
    } catch (error) {
      unread.push(`${where}: ${/** @type {Error} */ (error).message}`);
    }
  }
  return { landings, unread };
}

/**
 * The fixes in `git log --format="%H %(trailers:key=Introduced-by,...)"`
 * output, each with the commit names its trailers give; words that can't
 * be a hash, such as a note after it, are left out.
 * @param {string} text
 */
export function namedFixes(text) {
  const fixes = [];
  for (const line of text.split("\n")) {
    const [fix, ...words] = line.trim().split(/\s+/);
    const names = words
      .map((word) => word.replace(/^[^0-9a-f]+|[^0-9a-f]+$/gi, ""))
      .filter((word) => /^[0-9a-f]{7,40}$/i.test(word));
    if (fix && names.length) fixes.push({ fix, names });
  }
  return fixes;
}

/**
 * Landings and escaped bugs by how many reviews each landing ran, findings
 * by the review that reported them, their kind and outcome, and the bugs
 * whose commit no logged landing holds. A bug fixed in the landing that
 * brought it in never got past that landing, so it is left out.
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
  const outside = [];
  for (const escape of escapes) {
    const landing = owner.get(escape.introduced);
    if (!landing) {
      outside.push(escape);
      continue;
    }
    if (owner.get(escape.fix) === landing) continue;
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
    outside,
  };
}

function main() {
  const git = gitIn(process.cwd());
  const problems = [];
  const log = path.join(
    path.resolve(git(["rev-parse", "--git-common-dir"]).stdout.trim()),
    reviewLog,
  );
  const { landings, unread } = loggedLandings(
    fs.existsSync(log) ? fs.readFileSync(log, "utf8") : "",
  );
  problems.push(...unread);
  const withCommits = landings.map((landing) => {
    const listed = git(["rev-list", landing.range]);
    if (listed.status !== 0)
      problems.push(
        `Landing ${landing.range} can't be listed: ${listed.stderr.trim()}`,
      );
    return { ...landing, commits: listed.stdout.split("\n").filter(Boolean) };
  });
  const fixes = namedFixes(
    git([
      "log",
      "dev",
      "--format=%H %(trailers:key=Introduced-by,valueonly,separator=%x20)",
    ]).stdout,
  );
  // One Git process resolves every name: a full hash, or "<name> missing".
  const names = fixes.flatMap((fix) => fix.names);
  const resolved = git(
    ["cat-file", "--batch-check=%(objectname)"],
    names.map((name) => `${name}^{commit}\n`).join(""),
  ).stdout.split("\n");
  const escapes = [];
  let at = 0;
  for (const { fix, names } of fixes)
    for (const name of names) {
      const introduced = resolved[at++] ?? "";
      if (/^[0-9a-f]{40,64}$/.test(introduced))
        escapes.push({ fix, introduced });
      else
        problems.push(
          `Fix ${fix.slice(0, 8)} names ${name}, which Git can't find.`,
        );
    }
  const summary = summarize(withCommits, escapes);
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
        .map(([kind, tally]) => `${kind} ${tally.fixed}/${tally.dismissed}`)
        .join(", ")}`,
    );
  for (const escape of summary.escaped)
    console.log(
      `Fix ${short(escape.fix)}: bug from ${short(escape.introduced)}, landed in ${escape.range.split("..").map(short).join("..")} after ${escape.reviews ? count(escape.reviews, "independent review") : "no independent review"}`,
    );
  if (summary.outside.length)
    console.log(
      `${count(summary.outside.length, "fixed bug")} came from commits no logged landing holds, such as those from before the log.`,
    );
  for (const problem of problems) console.log(problem);
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) main();
