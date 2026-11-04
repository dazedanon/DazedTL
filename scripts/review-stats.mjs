// Sums up what landings' reviews caught and which bugs got past them, so
// the review rule in the dazedtl-land skill is tuned on data. It reads every
// landed review record in the shared Git directory's reviews log and every
// commit on dev whose `Introduced-by:` trailer (fix-trailers.mjs) names the
// commit that brought in the bug it fixes, and matches that commit to the
// landing that holds it. Bugs take days to surface, so escapes are set
// beside landings only once those are `exposureDays` old.
// Usage: node scripts/review-stats.mjs
import fs from "node:fs";
import path from "node:path";
import { generated } from "./contracts.mjs";
import { commitFormat, isFix, readCommits } from "./fix-trailers.mjs";
import { gitIn, reviewLog } from "./land-lock.mjs";

/**
 * @typedef {{ kind?: string, outcome: string, review: number }} Finding
 * @typedef {{ range: string, reviews: number, findings: Finding[], landed: number | null }} Logged
 * A landed range with how many independent reviews it ran, their findings
 * and when it landed, in milliseconds; one its author reviewed or skipped,
 * before independent reviews, ran none, and its findings count as review 0.
 * @typedef {Logged & { commits: string[], lines: number }} Landing
 * A logged landing with the full hashes of its range's commits and its
 * `codeLines`.
 * @typedef {{ fix: string, introduced: string[], marks: string[], found: string | null }} Fix
 * A commit with an Introduced-by trailer: the full hashes of the commits it
 * names, its `unknown` or `none` marks and who found the bug.
 */

/** How many days old a landing is before the bugs that got past it count. */
export const exposureDays = 14;

/** The upper ends of the landing size buckets, in code lines. */
const sizes = [100, 300, 1000];

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
    const landed = Date.parse(row.landed);
    landings.push({
      range: row.range,
      reviews: independent ? (row.reviews ?? 1) : 0,
      findings: findings.map((/** @type {any} */ item) => ({
        ...(item.kind === undefined ? {} : { kind: item.kind }),
        outcome: item.outcome,
        review: independent ? (item.review ?? 1) : 0,
      })),
      landed: Number.isFinite(landed) ? landed : null,
    });
  }
  return { landings, unread };
}

/**
 * The lines a landing changed in code, from its `git diff --numstat
 * --no-renames` output: tests, Markdown, JSON and the generated API
 * contracts are left out, and binary files count none.
 * @param {string} text
 */
export function codeLines(text) {
  let total = 0;
  for (const line of text.split("\n")) {
    const [added, deleted, file] = line.split("\t");
    if (
      !file ||
      file.startsWith("tests/") ||
      /\.(md|json)$/i.test(file) ||
      generated.includes(file)
    )
      continue;
    total += (Number(added) || 0) + (Number(deleted) || 0);
  }
  return total;
}

/**
 * The most bugs that got past landings that `low` known ones suggest, when
 * the fixes marked `unknown` got past landings as often as those that name
 * a commit.
 * @param {number} low
 * @param {{ named: number, unknown: number }} origins
 */
export function highEnd(low, { named, unknown }) {
  if (!unknown) return low;
  if (!named) return Infinity;
  return Math.ceil((low * (named + unknown)) / named);
}

/**
 * Landings old enough to count and the bugs that got past them, by how many
 * reviews each ran and by its code lines; findings by the review that
 * reported them, their kind and outcome; who found the bugs that got past;
 * how the fixes name where their bug came from; chains of fixes whose bug
 * came from another landing's fix; and the bugs whose commit no listed
 * landing holds. A bug counts once per landing it got past, however many of
 * that landing's commits its fix names, and only among the outside ones
 * when no landing holds any of them; a bug fixed in the landing that brought
 * it in never got past it.
 * @param {Landing[]} landings
 * @param {Fix[]} fixes
 * @param {{ now: number, fixCommits: Set<string> }} options `fixCommits`
 *   holds every commit whose subject is a fix's.
 */
export function summarize(landings, fixes, { now, fixCommits }) {
  /** @type {Map<number, { landings: number, escapes: number }>} */
  const byReviews = new Map();
  /** @type {Map<number, { landings: number, escapes: number }>} */
  const bySize = new Map();
  /** @type {Map<number, Record<string, { fixed: number, dismissed: number }>>} */
  const rounds = new Map();
  /** @type {Map<string, Landing>} */
  const owner = new Map();
  const exposed = new Set();
  const size = (/** @type {Landing} */ landing) =>
    sizes.filter((top) => landing.lines >= top).length;
  /** Adds one to a field of an old enough landing's groups. */
  const tally = (
    /** @type {Landing} */ landing,
    /** @type {"landings" | "escapes"} */ field,
  ) => {
    for (const [map, key] of /** @type {const} */ ([
      [byReviews, landing.reviews],
      [bySize, size(landing)],
    ])) {
      const group = map.get(key) ?? { landings: 0, escapes: 0 };
      group[field] += 1;
      map.set(key, group);
    }
  };
  let recent = 0;
  for (const landing of landings) {
    for (const commit of landing.commits) owner.set(commit, landing);
    if (
      landing.landed !== null &&
      now - landing.landed >= exposureDays * 86_400_000
    ) {
      exposed.add(landing);
      tally(landing, "landings");
    } else recent += 1;
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
  /** @type {Map<string, number>} */
  const foundBy = new Map();
  for (const { fix, introduced, found } of fixes) {
    for (const commit of introduced) {
      const landing = owner.get(commit);
      if (!landing) {
        outside.push({ fix, introduced: commit });
        continue;
      }
      const key = `${fix} ${landing.range}`;
      if (owner.get(fix) === landing || counted.has(key)) continue;
      counted.add(key);
      if (exposed.has(landing)) tally(landing, "escapes");
      if (!escaped.some((escape) => escape.fix === fix))
        foundBy.set(found ?? "", (foundBy.get(found ?? "") ?? 0) + 1);
      escaped.push({
        fix,
        introduced: commit,
        found,
        range: landing.range,
        reviews: landing.reviews,
      });
    }
  }
  const blamed = new Set(
    fixes
      .filter((fix) => fix.introduced.some((commit) => owner.has(commit)))
      .map((fix) => fix.fix),
  );
  const firsts = new Set();
  const unheld = outside.filter(
    (escape) =>
      !blamed.has(escape.fix) &&
      !firsts.has(escape.fix) &&
      firsts.add(escape.fix),
  );
  const named = fixes.filter((fix) => fix.introduced.length).length;
  const unknown = fixes.filter(
    (fix) => !fix.introduced.length && fix.marks.includes("unknown"),
  ).length;
  const sorted = (/** @type {Map<any, any>} */ map) =>
    [...map].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return {
    byReviews: sorted(byReviews),
    bySize: sorted(bySize).map(([bucket, group]) => [
      bucket === 0
        ? `under ${sizes[0]}`
        : bucket < sizes.length
          ? `${sizes[bucket - 1]}-${sizes[bucket] - 1}`
          : `${sizes[bucket - 1]} or more`,
      group,
    ]),
    recent,
    rounds: sorted(rounds),
    foundBy: [...foundBy].sort(([, a], [, b]) => b - a),
    origins: {
      named,
      unknown,
      none: fixes.filter(
        (fix) =>
          !fix.introduced.length &&
          !fix.marks.includes("unknown") &&
          fix.marks.includes("none"),
      ).length,
    },
    chains: fixChains(fixes, owner, fixCommits),
    escaped,
    outside: unheld,
  };
}

/**
 * Each chain of fixes, newest first, whose bug came from a fix that another
 * landing, or none in the log, held: the place AGENTS.md sends to a rework
 * instead of another fix. A fix of the fix its own landing brought in is a
 * review's catch, not a link.
 * @param {Fix[]} fixes
 * @param {Map<string, Landing>} owner
 * @param {Set<string>} fixCommits
 */
function fixChains(fixes, owner, fixCommits) {
  /** @type {Map<string, string[]>} */
  const links = new Map();
  for (const { fix, introduced } of fixes) {
    const fixed = introduced.filter(
      (commit) =>
        fixCommits.has(commit) &&
        commit !== fix &&
        (!owner.has(commit) || owner.get(commit) !== owner.get(fix)),
    );
    if (fixed.length) links.set(fix, fixed);
  }
  const later = new Set([...links.values()].flat());
  /** @returns {string[][]} */
  const walk = (/** @type {string} */ fix, /** @type {Set<string>} */ seen) => {
    const next = (links.get(fix) ?? []).filter((commit) => !seen.has(commit));
    if (!next.length) return [[fix]];
    return next.flatMap((commit) =>
      walk(commit, new Set([...seen, commit])).map((chain) => [fix, ...chain]),
    );
  };
  return [...links.keys()]
    .filter((fix) => !later.has(fix))
    .flatMap((fix) => walk(fix, new Set([fix])))
    .sort((a, b) => b.length - a.length);
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
    const diff = git([
      "diff",
      "--numstat",
      "--no-renames",
      "--end-of-options",
      landing.range,
    ]);
    if (listed.status === 0 && diff.status === 0)
      return [
        {
          ...landing,
          commits: listed.stdout.split("\n").filter(Boolean),
          lines: codeLines(diff.stdout),
        },
      ];
    problems.push(
      `Landing ${landing.range} can't be listed, so it is left out: ${(listed.stderr || diff.stderr).trim()}`,
    );
    return [];
  });
  const history = git(["log", `--format=${commitFormat}`, "refs/heads/dev"]);
  if (history.status !== 0)
    problems.push(`dev's history can't be read: ${history.stderr.trim()}`);
  const commits = readCommits(history.stdout);
  const fixCommits = new Set(
    commits
      .filter((commit) => isFix(commit.subject))
      .map((commit) => commit.commit),
  );
  const traced = commits.filter(
    (commit) =>
      commit.hashes.length ||
      commit.marks.length ||
      commit.unread.some(({ key }) => key === "Introduced-by"),
  );
  // One Git process resolves every name: its full hash, or why not.
  const names = traced.flatMap((commit) => commit.hashes);
  const resolving = git(
    ["cat-file", "--batch-check=%(objectname)"],
    names.map((name) => `${name}^{commit}\n`).join(""),
  );
  if (names.length && resolving.status !== 0)
    problems.push(`Git can't resolve commits: ${resolving.stderr.trim()}`);
  const resolved = resolving.stdout.split("\n");
  /** @type {Fix[]} */
  const fixes = [];
  let at = 0;
  for (const { commit: fix, hashes, marks, found, unread } of traced) {
    for (const { key, value } of unread)
      problems.push(
        `Fix ${fix.slice(0, 8)} has a ${key} trailer that is none of its values: ${value}`,
      );
    const introduced = [];
    for (const name of hashes) {
      const answer = resolved[at++] ?? "";
      if (/^[0-9a-f]{40,64}$/.test(answer)) introduced.push(answer);
      else
        problems.push(
          answer.endsWith(" ambiguous")
            ? `Fix ${fix.slice(0, 8)} names ${name}, which matches several objects; give more of the hash.`
            : `Fix ${fix.slice(0, 8)} names ${name}, which Git can't find.`,
        );
    }
    fixes.push({ fix, introduced, marks, found: found[0] ?? null });
  }
  const tracedCommits = new Set(traced);
  const untraced = commits.filter(
    (commit) => fixCommits.has(commit.commit) && !tracedCommits.has(commit),
  ).length;
  const summary = summarize(withCommits, fixes, {
    now: Date.now(),
    fixCommits,
  });
  const short = (/** @type {string} */ hash) => hash.slice(0, 8);
  const count = (/** @type {number} */ n, /** @type {string} */ noun) =>
    `${n} ${noun}${n === 1 ? "" : "s"}`;
  const { origins } = summary;
  const bugs = (/** @type {number} */ low) => {
    const high = highEnd(low, origins);
    return high === low
      ? count(low, "bug")
      : `${low}${high === Infinity ? " or more" : `-${high}`} bugs`;
  };
  const buckets = (
    /** @type {string} */ title,
    /** @type {[any, { landings: number, escapes: number }][]} */ rows,
    /** @type {(key: any) => string} */ name,
  ) => {
    console.log(`Landings ${exposureDays} days old or more, ${title}:`);
    if (!rows.length) console.log("  none yet");
    for (const [key, group] of rows)
      console.log(
        `  ${name(key)}: ${count(group.landings, "landing")}, ${bugs(group.escapes)} got past them`,
      );
  };
  buckets(
    "by independent reviews run",
    summary.byReviews,
    (reviews) => `${reviews || "none"}`,
  );
  buckets(
    "by code lines changed, leaving out tests, docs, JSON and generated contracts",
    summary.bySize,
    (bucket) => bucket,
  );
  console.log(
    `${count(summary.recent, "landing")} under ${exposureDays} days old ${summary.recent === 1 ? "is" : "are"} left out of these until then.`,
  );
  console.log(
    `Introduced-by: ${origins.named} name a commit, ${origins.unknown} unknown, ${origins.none} none; a range's high end counts the unknown ones as getting past landings as often as the named ones.`,
  );
  if (untraced)
    console.log(
      `${count(untraced, "fix commit")} on dev carry no Introduced-by trailer, most from before land.mjs required it, so their bugs are in no count.`,
    );
  if (summary.foundBy.length)
    console.log(
      `Bugs that got past a landing, by who found them: ${summary.foundBy
        .map(([found, n]) => `${found || "not recorded"} ${n}`)
        .join(", ")}`,
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
  if (summary.chains.length)
    console.log("Fix chains, each fix's bug from the fix after it:");
  for (const chain of summary.chains)
    console.log(
      `  ${chain.map(short).join(" <- ")}${chain.length >= 3 ? `: ${chain.length} fixes in a row, so the next goes to a rework (AGENTS.md)` : ""}`,
    );
  for (const escape of summary.escaped)
    console.log(
      `Fix ${short(escape.fix)}: bug from ${short(escape.introduced)}, landed in ${escape.range.split("..").map(short).join("..")} after ${escape.reviews ? count(escape.reviews, "independent review") : "no independent review"}, found by ${escape.found ?? "an unrecorded finder"}`,
    );
  if (summary.outside.length)
    console.log(
      `${count(summary.outside.length, "fixed bug")} came from commits no listed landing holds, such as those from before the log.`,
    );
  for (const problem of problems) console.log(problem);
}

if (import.meta.main) main();
