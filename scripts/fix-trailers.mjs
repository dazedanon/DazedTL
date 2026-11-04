// The trailers a fix commit ends with (AGENTS.md), so review-stats.mjs can
// tell which landings let a bug through and what caught it, and land.mjs
// refuses a fix without them. Both read them through Git's own trailer
// parsing, with this one reader.
//
// `Introduced-by:` names the commit that brought the bug in by its hash, a
// commit of the same branch included, and may appear once per such commit.
// `unknown` says the history doesn't show which commit did, and `none` that
// no commit did, such as for a provider's API change. A note may follow the
// value. `Found-by:` names, once, who found the bug: one of `finders`.

/** Who can find a bug: a landing's reviewer, CI, a test scenario, a playtest, a Discord post, the user, or the fix's author. */
export const finders = [
  "review",
  "ci",
  "scenario",
  "playtest",
  "discord",
  "user",
  "author",
];

/** The `git log --format` that `readCommits` reads. */
export const commitFormat = [
  "%H",
  "%s",
  "%(trailers:key=Introduced-by,valueonly,unfold,separator=%x1e)",
  "%(trailers:key=Found-by,valueonly,unfold,separator=%x1e)",
].join("%x1f");

/** Whether a commit subject is a fix's, such as `fix(ui): ...`. */
export function isFix(/** @type {string} */ subject) {
  return /^fix\b/i.test(subject);
}

/**
 * Each commit in `commitFormat` output, with its trailers' values read by
 * their first word, so a note after one is never read as part of it.
 * `unread` keeps each value that is no hash, mark or finder.
 * @param {string} text
 */
export function readCommits(text) {
  const values = (/** @type {string | undefined} */ field) =>
    (field ?? "")
      .split("\x1e")
      .map((value) => value.trim())
      .filter(Boolean);
  // Brackets and punctuation around a value, but no # or other prefix.
  const first = (/** @type {string} */ value) =>
    (value.split(/\s+/)[0] ?? "").replace(/^[(]+|[),.;:]+$/g, "");
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const [commit, subject = "", introduced, found] = line.split("\x1f");
      /** @type {string[]} */ const hashes = [];
      /** @type {("unknown" | "none")[]} */ const marks = [];
      /** @type {string[]} */ const finds = [];
      /** @type {{ key: string, value: string }[]} */ const unread = [];
      for (const value of values(introduced)) {
        const word = first(value);
        const mark = word.toLowerCase();
        if (/^[0-9a-f]{7,64}$/i.test(word)) hashes.push(word);
        else if (mark === "unknown" || mark === "none") marks.push(mark);
        else unread.push({ key: "Introduced-by", value });
      }
      for (const value of values(found)) {
        const word = first(value).toLowerCase();
        if (finders.includes(word)) finds.push(word);
        else unread.push({ key: "Found-by", value });
      }
      return {
        commit: commit.trim(),
        subject,
        hashes,
        marks,
        found: finds,
        unread,
      };
    });
}

/**
 * What a fix commit's trailers lack, each as a short clause; empty when they
 * say where its bug came from and who found it. The hashes they name are
 * the caller's to resolve.
 * @param {ReturnType<typeof readCommits>[number]} commit
 */
export function missingTrailers({ hashes, marks, found, unread }) {
  const lacks = [];
  for (const { key, value } of unread)
    lacks.push(
      key === "Found-by"
        ? `Found-by "${value}" is none of ${finders.join(", ")}`
        : `Introduced-by "${value}" is no commit hash, unknown or none`,
    );
  if (
    !hashes.length &&
    !marks.length &&
    !unread.some(({ key }) => key === "Introduced-by")
  )
    lacks.push("no Introduced-by trailer");
  if (found.length > 1)
    lacks.push(`${found.length} Found-by trailers, not the one that found it`);
  else if (!found.length && !unread.some(({ key }) => key === "Found-by"))
    lacks.push("no Found-by trailer");
  return lacks;
}
