// Sums up what landings' reviews caught and which bugs got past them, so
// the review rule in the dazedtl-land skill is tuned on data. It reads every
// landed review record in the shared Git directory's reviews log and every
// commit on dev whose `Introduced-by:` trailer names the commit that
// brought in the bug it fixes (AGENTS.md), and matches that commit to the
// landing that holds it.
// Usage: node scripts/review-stats.mjs
import fs from "node:fs";
import path from "node:path";
import { gitIn, reviewLog } from "./land-lock.mjs";

/**
 * @typedef {{ kind?: string, outcome: string, review: number }} Finding
 * @typedef {{ range: string, reviews: number, findings: Finding[] }} Logged
 * A landed range with how many independent reviews it ran and their
 * findings; one its author reviewed or skipped, before independent
 * reviews, ran none, and its findings count as review 0.
 * @typedef {Logged & { commits: string[] }} Landing
 * A logged landing with the full hashes of its range's commits.
 * @typedef {{ fix: string, introduced: string }} Escape
 * A fix commit and the full hash of a commit that brought its bug in.
 */

/**
 * The landings in a reviews log's text, read as land.mjs logged them, so
 * a later, stricter readReview leaves old lines readable; a line that can't
 * be read is listed apart instead of ending the report.
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
    const independent = row?.reviewer === "independent";
    // An early landing could skip its review, recording why instead.
    const findings = Array.isArray(row?.findings)
      ? row.findings
      : !independent && typeof row?.skipped === "string"
        ? []
        : null;
    if (
      typeof row?.range !== "string" ||
      !findings ||
      findings.some(
        (/** @type {any} */ item) =>
          item?.outcome !== "fixed" && item?.outcome !== "dismissed",
      )
    ) {
      unread.push(`${where} has no range or a finding without an outcome.`);
      continue;
    }
    landings.push({
      range: row.range,
      reviews: independent ? (row.reviews ?? 1) : 0,
      findings: findings.map((/** @type {any} */ item) => ({
        ...(item.kind === undefined ? {} : { kind: item.kind }),
        outcome: item.outcome,
        review: independent ? (item.review ?? 1) : 0,
      })),
    });
  }
  return { landings, unread };
}

/**
 * The fixes in `git log --format="%H%x1f%(trailers:key=Introduced-by,
 * valueonly,separator=%x1e)"` output, each with the commit each trailer
 * names: the first word of its value, so a note after the hash is never
 * read as one. A trailer that names no hash is kept in `unnamed`, for the
 * report to point out.
 * @param {string} text
 */
export function namedFixes(text) {
  const fixes = [];
  for (const line of text.split("\n")) {
    const [fix, trailers = ""] = line.split("\x1f");
    if (!fix.trim() || !trailers.trim()) continue;
    const names = [];
    const unnamed = [];
    for (const value of trailers.split("\x1e")) {
      // Brackets and punctuation around a hash, but no # or prefix.
      const first = (value.trim().split(/\s+/)[0] ?? "").replace(
        /^[(]+|[),.;:]+$/g,
        "",
      );
      if (/^[0-9a-f]{7,64}$/i.test(first)) names.push(first);
      else if (value.trim()) unnamed.push(value.trim());
    }
    fixes.push({ fix: fix.trim(), names, unnamed });
  }
  return fixes;
}

/**
 * Landings and escaped bugs by how many reviews each landing ran, findings
 * by the review that reported them, their kind and outcome, and the bugs
 * whose commit no listed landing holds. A bug counts once per landing it
 * got past, however many of that landing's commits its fix names, and only
 * among the outside ones when no landing holds any of them; a bug fixed in
 * the landing that brought it in never got past it.
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
  const counted = new Set();
  for (const escape of escapes) {
    const landing = owner.get(escape.introduced);
    if (!landing) {
      outside.push(escape);
      continue;
    }
    const key = `${escape.fix} ${landing.range}`;
    if (owner.get(escape.fix) === landing || counted.has(key)) continue;
    counted.add(key);
    /** @type {{ landings: number, escapes: number }} */ (
      byReviews.get(landing.reviews)
    ).escapes += 1;
    escaped.push({ ...escape, range: landing.range, reviews: landing.reviews });
  }
  const blamed = new Set(
    escapes
      .filter((escape) => owner.has(escape.introduced))
      .map((escape) => escape.fix),
  );
  const firsts = new Set();
  const unheld = outside.filter(
    (escape) =>
      !blamed.has(escape.fix) &&
      !firsts.has(escape.fix) &&
      firsts.add(escape.fix),
  );
  const sorted = (/** @type {Map<number, any>} */ map) =>
    [...map].sort(([a], [b]) => a - b);
  return {
    byReviews: sorted(byReviews),
    rounds: sorted(rounds),
    escaped,
    outside: unheld,
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
  // A landing Git can't list is left out, so it skews no review count.
  const withCommits = landings.flatMap((landing) => {
    const listed = git(["rev-list", "--end-of-options", landing.range]);
    if (listed.status === 0)
      return [
        { ...landing, commits: listed.stdout.split("\n").filter(Boolean) },
      ];
    problems.push(
      `Landing ${landing.range} can't be listed, so it is left out: ${listed.stderr.trim()}`,
    );
    return [];
  });
  const history = git([
    "log",
    "--format=%H%x1f%(trailers:key=Introduced-by,valueonly,unfold,separator=%x1e)",
    "refs/heads/dev",
  ]);
  if (history.status !== 0)
    problems.push(`dev's history can't be read: ${history.stderr.trim()}`);
  const fixes = namedFixes(history.stdout);
  // One Git process resolves every name: its full hash, or why not.
  const names = fixes.flatMap((fix) => fix.names);
  const resolving = git(
    ["cat-file", "--batch-check=%(objectname)"],
    names.map((name) => `${name}^{commit}\n`).join(""),
  );
  if (names.length && resolving.status !== 0)
    problems.push(`Git can't resolve commits: ${resolving.stderr.trim()}`);
  const resolved = resolving.stdout.split("\n");
  const escapes = [];
  let at = 0;
  for (const { fix, names, unnamed } of fixes) {
    for (const value of unnamed)
      problems.push(
        `Fix ${fix.slice(0, 8)} has an Introduced-by trailer with no commit hash: ${value}`,
      );
    for (const name of names) {
      const answer = resolved[at++] ?? "";
      if (/^[0-9a-f]{40,64}$/.test(answer))
        escapes.push({ fix, introduced: answer });
      else
        problems.push(
          answer.endsWith(" ambiguous")
            ? `Fix ${fix.slice(0, 8)} names ${name}, which matches several objects; give more of the hash.`
            : `Fix ${fix.slice(0, 8)} names ${name}, which Git can't find.`,
        );
    }
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
  if (summary.rounds.length)
    console.log("Findings by review and kind, fixed/dismissed:");
  for (const [review, kinds] of summary.rounds)
    console.log(
      `  ${review ? `review ${review}` : "author's review"}: ${Object.entries(
        kinds,
      )
        .map(([kind, tally]) => `${kind} ${tally.fixed}/${tally.dismissed}`)
        .join(", ")}`,
    );
  for (const escape of summary.escaped)
    console.log(
      `Fix ${short(escape.fix)}: bug from ${short(escape.introduced)}, landed in ${escape.range.split("..").map(short).join("..")} after ${escape.reviews ? count(escape.reviews, "independent review") : "no independent review"}`,
    );
  if (summary.outside.length)
    console.log(
      `${count(summary.outside.length, "fixed bug")} came from commits no listed landing holds, such as those from before the log.`,
    );
  for (const problem of problems) console.log(problem);
}

if (import.meta.main) main();
