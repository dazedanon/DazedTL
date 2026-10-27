/** How the release playtest's report reads on the page. */

import type {
  PlaytestProblem,
  PlaytestState,
  PlaytestFix,
} from "../../api/contracts";
import type { DisplayState } from "../../ui/displayStatus";

export type PlaytestPhase =
  "not_started" | "running" | "done" | "outdated" | "blocked";

/** Why the playtest last started did not finish, when it ended after the
 * report shown. */
export function playtestFailure(
  playtest: PlaytestState,
  job?: {
    status: string;
    message?: string;
    updated?: string;
    created?: string;
  },
) {
  if (!job || !["failed", "interrupted", "stopped"].includes(job.status))
    return "";
  const ended = Date.parse(job.updated || job.created || "") || 0;
  const report = Date.parse(playtest.finished_at || "") || 0;
  return ended > report ? job.message || "it stopped." : "";
}

/** Where the playtest stands, from its report and whether one is running. */
export function playtestPhase(
  playtest: PlaytestState,
  running: boolean,
): PlaytestPhase {
  if (running) return "running";
  if (!playtest.report && !playtest.unreadable) return "not_started";
  // A report the app can't read, or a tour that could not play the game.
  if (playtest.unreadable || !playtest.played) return "blocked";
  return playtest.current ? "done" : "outdated";
}

/** The operations that play the game: a playtest, and a check of the
 * assistant's fixes. */
export const playtestActions = ["release_playtest", "playtest_fix"];

export const playtestDisplay: Record<PlaytestPhase, DisplayState> = {
  not_started: "not_started",
  running: "working",
  done: "done",
  outdated: "outdated",
  blocked: "blocked",
};

// The kind "japanese" is source text left in any source language; it keeps
// the name reports were saved with.
const kinds = (
  source: string,
): {
  kind: PlaytestProblem["kind"];
  title: string;
}[] => [
  { kind: "crash", title: "Crashes" },
  { kind: "japanese", title: `${source} left in the game` },
  { kind: "fit", title: "Text that doesn't fit" },
  { kind: "codes", title: "Lost names and codes" },
];

// How likely players are to see text, most likely first.
const reachOrder = [
  "drawn",
  "called",
  "runs",
  "may-show",
  "unknown",
  "disabled",
  "uncalled",
  "unread",
];
const likely = (problem: PlaytestProblem) =>
  problem.seen ? -1 : problem.reach ? reachOrder.indexOf(problem.reach) : 0;

/** Problems by kind, the worst first; within a kind, those the tour saw on
 * screen, then those players are likeliest to see. *source* is the game's
 * source language. */
export function playtestGroups(problems: PlaytestProblem[], source: string) {
  return kinds(source)
    .map(({ kind, title }) => ({
      kind,
      title,
      problems: problems
        .filter((problem) => problem.kind === kind)
        .sort((a, b) => likely(a) - likely(b)),
    }))
    .filter((group) => group.problems.length);
}

/** Whether players can see a problem's text, as its evidence says. */
export const playtestReach: Record<string, string> = {
  drawn: "Its code draws it",
  called: "Players may see this",
  runs: "Players may see this",
  unknown: "Players may see this",
  "may-show": "Players may see this",
  disabled: "Turned off in the code",
  uncalled: "Nothing runs it now",
  unread: "Nothing reads it now",
};

const fixes: Record<PlaytestFix, string> = {
  "text-qa": "Text QA corrects it",
  translate: "Translate it in Translate",
  "plugin-files": "Your assistant translates it",
  game: "The game's own code or data",
};
const reviews = {
  reviewing: "In Text QA's review",
  reviewed: "Text QA reviewed it",
  waiting: "Text QA corrects it when QA runs again",
  outside: "Not in QA's review",
};

/**
 * The task that fixes a problem, and for Text QA where it stands. A line
 * QA can't take is outside a narrower focus than the full game text, and
 * an event comment never translated waits for Maps & events' comment text.
 */
export const playtestFix = (problem: PlaytestProblem, focus = "release") =>
  problem.review === "outside" && focus !== "release"
    ? "Outside the QA focus"
    : problem.review
      ? reviews[problem.review]
      : problem.check === "untranslated-comment"
        ? "Maps & events, with Comment text on in Speaker detection"
        : fixes[problem.fix];

const fileName = (path: string) => path.split("/").pop() || path;

/** A problem's one-line name: its text, or what the check found, in a game
 * whose text is in *source*. */
export function playtestTitle(problem: PlaytestProblem, source: string) {
  const file = fileName(problem.file);
  switch (problem.check) {
    case "json":
      return `${file} doesn't load`;
    case "plugin-list":
      return "The plugin list doesn't load";
    case "plugin-missing":
      return `${file} is missing`;
    case "plugin-syntax":
      return `${file} doesn't compile`;
    case "runtime-crash":
      return "The game stopped";
    case "runtime-error":
      return "A script failed";
    case "untranslated":
      return `${problem.plugin || file} · ${(problem.count || 0).toLocaleString()} never translated`;
    case "plugin-text":
      return `${file} · ${(problem.count || 0).toLocaleString()} ${source} ${problem.count === 1 ? "string" : "strings"}`;
    case "placeholder-glyph":
      return problem.count
        ? `${file} · ${problem.count.toLocaleString()} ${problem.count === 1 ? "placeholder glyph" : "placeholder glyphs"}`
        : problem.text || problem.note;
    default:
      return problem.text || problem.note;
  }
}

/** Where a problem is: its file and line or entry, and where the tour saw
 * it. */
export function playtestWhere(problem: PlaytestProblem) {
  return [
    problem.file &&
      problem.file +
        (problem.line ? `:${problem.line}` : "") +
        (problem.pointer && !problem.line ? ` ${problem.pointer}` : ""),
    problem.seen
      ? problem.seen.scene
        ? `Seen on ${problem.seen.scene}`
        : `During ${problem.seen.stop}`
      : problem.kind !== "crash" && "Found in the files",
    !problem.seen && problem.reach && playtestReach[problem.reach],
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The report in a few words, for the panel. */
export function playtestSummary(playtest: PlaytestState) {
  const count = playtest.problems.length;
  const seen = playtest.problems.filter((problem) => problem.seen).length;
  if (!count)
    return playtest.since?.fixed
      ? "Everything the last playtest found is fixed."
      : "The playtest found nothing to fix.";
  const fixed = playtest.since?.fixed || 0;
  return (
    `${count.toLocaleString()} ${count === 1 ? "problem" : "problems"}` +
    (seen ? `, ${seen.toLocaleString()} seen in the game` : "") +
    (fixed ? `; ${fixed.toLocaleString()} fixed since the last playtest` : "") +
    "."
  );
}

/** How far the tour got, such as "Reached 8 of 9 stops · 274 messages". */
export function playtestCoverage(playtest: PlaytestState) {
  const coverage = playtest.coverage;
  if (!coverage?.stops.length) return "";
  return [
    `Reached ${coverage.reached} of ${coverage.stops.length} stops`,
    coverage.messages > 0 &&
      `${coverage.messages.toLocaleString()} ${coverage.messages === 1 ? "message" : "messages"}`,
    coverage.scenes > 0 &&
      `${coverage.scenes} ${coverage.scenes === 1 ? "screen" : "screens"}`,
  ]
    .filter(Boolean)
    .join(" · ");
}
