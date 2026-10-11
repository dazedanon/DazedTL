/** A stretch of one side of a changed line, marked when the other lacks it. */
export type WordRun = { text: string; changed: boolean };

type Edit = { kind: "same" | "removed" | "added"; text: string };

/* Words, numbers, runs of spaces and single other characters. A word ends
   where a capital or a digit starts another, so "BanditLv2" compares as
   three, and each kana or kanji stands alone, since Japanese has no spaces. */
const tokenPattern =
  /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]|(?:\p{Lu}+(?!\p{Ll})|\p{Lu}?[\p{Ll}\p{Lo}\p{Lm}\p{M}]+)(?:['’][\p{Ll}\p{Lo}\p{Lm}\p{M}]+)*|\p{N}+|\s+|./gsu;

/** Token pairs the comparison may weigh; a longer rewrite is one change. */
const comparisonLimit = 250_000;

/**
 * The words that differ between two versions of a line, so a correction can
 * mark what it changed. A short stretch between two changes joins them, as
 * a readable diff does, and a line that changed mostly comes back unmarked,
 * since marks would cover nearly all of it.
 */
export function changedWords(before: string, after: string) {
  const edits = joinShortSames(
    normalize(compare(tokens(before), tokens(after))),
  );
  const length = (kind: Edit["kind"]) =>
    edits
      .filter((edit) => edit.kind === kind)
      .reduce((total, edit) => total + edit.text.replace(/\s/gu, "").length, 0);
  if (length("same") * 2 < Math.max(length("removed"), length("added")))
    return {
      before: [{ text: before, changed: false }],
      after: [{ text: after, changed: false }],
    };
  return { before: side(edits, "removed"), after: side(edits, "added") };
}

function tokens(text: string) {
  return text.match(tokenPattern) || [];
}

/** The edits that turn one token list into the other, longest match kept. */
function compare(left: string[], right: string[]): Edit[] {
  let start = 0;
  while (
    start < left.length &&
    start < right.length &&
    left[start] === right[start]
  )
    start++;
  let end = 0;
  while (
    end < left.length - start &&
    end < right.length - start &&
    left[left.length - 1 - end] === right[right.length - 1 - end]
  )
    end++;
  const removed = left.slice(start, left.length - end);
  const added = right.slice(start, right.length - end);
  return [
    { kind: "same", text: left.slice(0, start).join("") },
    ...(removed.length * added.length > comparisonLimit
      ? ([
          { kind: "removed", text: removed.join("") },
          { kind: "added", text: added.join("") },
        ] as Edit[])
      : commonSubsequence(removed, added)),
    { kind: "same", text: left.slice(left.length - end).join("") },
  ];
}

function commonSubsequence(left: string[], right: string[]): Edit[] {
  const width = right.length + 1;
  // Each cell holds the longest common run of the two lists from there on.
  const table = new Uint32Array((left.length + 1) * width);
  for (let i = left.length - 1; i >= 0; i--)
    for (let j = right.length - 1; j >= 0; j--)
      table[i * width + j] =
        left[i] === right[j]
          ? table[(i + 1) * width + j + 1] + 1
          : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
  const edits: Edit[] = [];
  let i = 0;
  let j = 0;
  while (i < left.length || j < right.length) {
    if (i < left.length && j < right.length && left[i] === right[j]) {
      edits.push({ kind: "same", text: left[i++] });
      j++;
    } else if (
      j === right.length ||
      (i < left.length &&
        table[(i + 1) * width + j] >= table[i * width + j + 1])
    )
      edits.push({ kind: "removed", text: left[i++] });
    else edits.push({ kind: "added", text: right[j++] });
  }
  return edits;
}

/** Edits with each stretch between two sames as one removal and one addition. */
function normalize(edits: Edit[]) {
  const result: Edit[] = [];
  let removed = "";
  let added = "";
  const flush = () => {
    if (removed) result.push({ kind: "removed", text: removed });
    if (added) result.push({ kind: "added", text: added });
    removed = added = "";
  };
  for (const edit of edits) {
    if (edit.kind === "removed") removed += edit.text;
    else if (edit.kind === "added") added += edit.text;
    else if (edit.text) {
      flush();
      const last = result.at(-1);
      if (last?.kind === "same") last.text += edit.text;
      else result.push({ ...edit });
    }
  }
  flush();
  return result;
}

/**
 * Folds a same no longer than the changes on both sides into them, so a
 * rewrite reads as one change rather than words scattered around a shared
 * space or "the".
 */
function joinShortSames(edits: Edit[]) {
  for (;;) {
    const index = edits.findIndex(
      (edit, at) =>
        edit.kind === "same" &&
        at > 0 &&
        at < edits.length - 1 &&
        edit.text.length <=
          Math.min(changeBeside(edits, at, -1), changeBeside(edits, at, 1)),
    );
    if (index < 0) return edits;
    const { text } = edits[index];
    edits = normalize([
      ...edits.slice(0, index),
      { kind: "removed", text },
      { kind: "added", text },
      ...edits.slice(index + 1),
    ]);
  }
}

/** The longer side of the change next to a same, in characters. */
function changeBeside(edits: Edit[], at: number, step: number) {
  let removed = 0;
  let added = 0;
  for (let i = at + step; edits[i] && edits[i].kind !== "same"; i += step)
    if (edits[i].kind === "removed") removed += edits[i].text.length;
    else added += edits[i].text.length;
  return Math.max(removed, added);
}

/** One line's runs; spaces at a change's edges stay unmarked. */
function side(edits: Edit[], kind: "removed" | "added") {
  const runs: WordRun[] = [];
  const add = (text: string, changed: boolean) => {
    const last = runs.at(-1);
    if (!text) return;
    if (last?.changed === changed) last.text += text;
    else runs.push({ text, changed });
  };
  for (const edit of edits) {
    if (edit.kind === "same") add(edit.text, false);
    else if (edit.kind === kind) {
      const [, lead, text, trail] = /^(\s*)(.*?)(\s*)$/su.exec(edit.text)!;
      if (!text) add(edit.text, true);
      else {
        add(lead, false);
        add(text, true);
        add(trail, false);
      }
    }
  }
  return runs;
}
