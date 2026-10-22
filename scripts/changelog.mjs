// Reads and writes CHANGELOG.md in the Keep a Changelog format
// (https://keepachangelog.com/en/1.1.0/). The next release's notes wait in
// release/notes.md; scripts/release.mjs files them under their version, so
// nobody edits CHANGELOG.md by hand.
import fs from "node:fs";

export const CHANGELOG = "CHANGELOG.md";
export const NOTES = "release/notes.md";
/** Keep a Changelog's kinds of change, in the order an entry lists them. */
export const KINDS = [
  "Added",
  "Changed",
  "Deprecated",
  "Removed",
  "Fixed",
  "Security",
];
/** What release/notes.md holds between releases. */
export const notesTemplate =
  "<!-- The next release's notes; see docs/development.md#release-notes. -->\n";
const header = [
  "# Changelog",
  "",
  "Every DazedTL release, newest first, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.",
  "[release.mjs](scripts/release.mjs) writes each entry from [release/notes.md](release/notes.md).",
  "",
].join("\n");

/** @typedef {{ kind: string, items: string[] }} Section */
/** @typedef {{ version: string, date: string, sections: Section[] }} Release */

const comment = /^<!--.*-->$/;
const kindHeading = /^### (.+)$/;
const item = /^- (\S.*)$/;
const versionHeading = /^## \[([^\]]+)\](?: - (\d{4}-\d{2}-\d{2}))?/;
const linkReference = /^\[[^\]]+\]: /;

/**
 * The sections of pending release notes, in Keep a Changelog order. Refuses
 * anything but `### Kind` headings and one-line `- ` items under them.
 * @param {string} text
 * @returns {Section[]}
 */
export function parseNotes(text) {
  /** @type {Map<string, string[]>} */
  const sections = new Map();
  /** @type {string[] | null} */
  let items = null;
  for (const [index, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim();
    const where = `${NOTES} line ${index + 1}`;
    if (!line || comment.test(line)) continue;
    const heading = kindHeading.exec(line);
    if (heading) {
      if (!KINDS.includes(heading[1]))
        throw new Error(
          `${where}: use one of ${KINDS.join(", ")} as a heading, not "${heading[1]}".`,
        );
      if (sections.has(heading[1]))
        throw new Error(`${where}: "${heading[1]}" appears twice.`);
      sections.set(heading[1], (items = []));
    } else if (item.test(line) && items) items.push(line.slice(2));
    else
      throw new Error(
        `${where}: write each change as one "- " line under a "### Kind" heading.`,
      );
  }
  for (const [kind, list] of sections)
    if (!list.length) throw new Error(`${NOTES}: "${kind}" lists no changes.`);
  return KINDS.filter((kind) => sections.has(kind)).map((kind) => ({
    kind,
    items: /** @type {string[]} */ (sections.get(kind)),
  }));
}

/** @param {Section[]} sections */
export const formatSections = (sections) =>
  sections
    .map(
      ({ kind, items }) =>
        `### ${kind}\n\n${items.map((text) => `- ${text}`).join("\n")}\n`,
    )
    .join("\n");

/**
 * Merges two branches' pending notes by kind: `theirs` keeps its lines, less
 * those `ours` removed or reworded, and gains the lines `ours` added under
 * their own headings. Git's line merges would misfile one branch's Fixed line
 * under the other's new Added heading, repeat headings, or bring back lines a
 * release filed away. Refuses notes parseNotes refuses.
 * @param {string} base The notes where the branches parted.
 * @param {string} ours
 * @param {string} theirs
 */
export function mergeNotes(base, ours, theirs) {
  const lines = (/** @type {string} */ text) =>
    parseNotes(text).flatMap(({ kind, items }) =>
      items.map((text) => `${kind}\n${text}`),
    );
  const before = new Set(lines(base));
  const kept = new Set(lines(ours));
  const merged = lines(theirs).filter(
    (line) => kept.has(line) || !before.has(line),
  );
  for (const line of kept)
    if (!before.has(line) && !merged.includes(line)) merged.push(line);
  const sections = KINDS.map((kind) => ({
    kind,
    items: merged
      .filter((line) => line.startsWith(`${kind}\n`))
      .map((line) => line.slice(kind.length + 1)),
  })).filter((section) => section.items.length);
  return sections.length
    ? `${notesTemplate}\n${formatSections(sections)}`
    : notesTemplate;
}

/**
 * Every release CHANGELOG.md lists, newest first.
 * @param {string} text
 * @returns {Release[]}
 */
export function parseChangelog(text) {
  /** @type {Release[]} */
  const releases = [];
  /** @type {Section | null} */
  let section = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    const version = versionHeading.exec(line);
    const heading = kindHeading.exec(line);
    const release = releases.at(-1);
    if (version) {
      releases.push({
        version: version[1],
        date: version[2] ?? "",
        sections: [],
      });
      section = null;
    } else if (/^#{1,2} /.test(line)) section = null;
    else if (heading && release)
      release.sections.push((section = { kind: heading[1], items: [] }));
    else if (item.test(line) && section) section.items.push(line.slice(2));
  }
  return releases;
}

/**
 * Adds a release's entry above the newest one, with the link its version
 * heading points to.
 * @param {string} text The current CHANGELOG.md, or "" to start one.
 * @param {{ version: string, date: string, sections: Section[], link: string }} release
 */
export function addRelease(text, { version, date, sections, link }) {
  const lines = (text.trim() ? text : header).trimEnd().split("\n");
  let links = lines.findIndex((line) => linkReference.test(line));
  if (links < 0) links = lines.length;
  let first = lines.findIndex((line) => versionHeading.test(line));
  if (first < 0) first = links;
  const part = (start = 0, end = lines.length) =>
    lines.slice(start, end).join("\n").trim();
  return `${[
    part(0, first),
    `## [${version}] - ${date}\n\n${formatSections(sections).trimEnd()}`,
    part(first, links),
    [`[${version}]: ${link}`, part(links)].filter(Boolean).join("\n"),
  ]
    .filter(Boolean)
    .join("\n\n")}\n`;
}

// Git's merge driver for release/notes.md, which scripts/land.mjs names when
// it merges dev: node scripts/changelog.mjs merge <base> <ours> <theirs>
// writes the merged notes over <ours>; notes it cannot read stay a conflict.
if (import.meta.main && process.argv[2] === "merge") {
  const [base, ours, theirs] = process.argv
    .slice(3)
    .map((file) => fs.readFileSync(file, "utf8"));
  try {
    fs.writeFileSync(process.argv[4], mergeNotes(base, ours, theirs));
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
