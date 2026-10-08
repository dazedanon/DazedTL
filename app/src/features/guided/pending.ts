/** Everything reviewed and waiting to go into the game, from observed state. */

import type { Preview } from "../../api/contracts.ts";

export type PendingPartId = "plugins" | "images" | "text" | "rewraps" | "qa";

export interface PendingPart {
  id: PendingPartId;
  title: string;
  count: number;
  /** The amount in words, such as "12 files". */
  summary: string;
  /** The game data files a text part writes. */
  files: string[];
  /** Why the part waits for another part of the same apply, or "". */
  held: string;
}

/**
 * Apply order: plugin files and images touch their own files; text goes
 * next, and rewraps and QA fixes last, because they edit applied text.
 */
export const applyOrder: PendingPartId[] = [
  "plugins",
  "images",
  "text",
  "rewraps",
  "qa",
];

const plural = (count: number, one: string, many = one + "s") =>
  `${count.toLocaleString()} ${count === 1 ? one : many}`;

export function pendingParts({
  unapplied,
  plugins,
  images,
  rewraps,
  qa,
  excluded = new Set(),
}: {
  /** Selected files with saved output not yet in the game. */
  unapplied: string[];
  /** Plugin files checked and ready to apply. */
  plugins: number;
  /** Images reviewed and ready to apply. */
  images: number;
  /** Changes a current line width check would write, with their files. */
  rewraps: { changes: number; files: string[] } | null;
  /** Chosen QA fixes for the current QA task, with their files. */
  qa: { fixes: number; files: string[] } | null;
  /** Parts left out of this apply. */
  excluded?: ReadonlySet<PendingPartId>;
}): PendingPart[] {
  const included = (id: PendingPartId, count: number) =>
    !excluded.has(id) && count > 0;
  const text = included("text", unapplied.length);
  // Rewraps were checked against the game's text, which the text part
  // replaces. QA was checked against the text and plugin files, which the
  // plugin, text and rewrap parts all change, so it waits for any of them.
  // Each is checked again afterwards.
  const before = [
    included("plugins", plugins) && "plugin files",
    text && "translated text",
    included("rewraps", rewraps?.changes || 0) && "line rewraps",
  ].filter((name): name is string => !!name);
  const after = (waits: string[], what: string) =>
    waits.length
      ? `Waits for the ${new Intl.ListFormat("en", { type: "conjunction" }).format(waits)} in this apply; ${what} again afterwards.`
      : "";
  const parts: PendingPart[] = [];
  if (plugins)
    parts.push({
      id: "plugins",
      title: "Plugin files",
      count: plugins,
      summary: plural(plugins, "plugin file"),
      files: [],
      held: "",
    });
  if (images)
    parts.push({
      id: "images",
      title: "Images",
      count: images,
      summary: plural(images, "image"),
      files: [],
      held: "",
    });
  if (unapplied.length)
    parts.push({
      id: "text",
      title: "Translated text",
      count: unapplied.length,
      summary: plural(unapplied.length, "file"),
      files: unapplied,
      held: "",
    });
  if (rewraps?.changes)
    parts.push({
      id: "rewraps",
      title: "Rewrapped lines",
      count: rewraps.changes,
      summary: plural(rewraps.changes, "line rewrap"),
      files: rewraps.files,
      held: after(text ? ["translated text"] : [], "check line widths"),
    });
  if (qa?.fixes)
    parts.push({
      id: "qa",
      title: "QA fixes",
      count: qa.fixes,
      summary: plural(qa.fixes, "QA fix", "QA fixes"),
      files: qa.files,
      held: after(before, "prepare QA"),
    });
  return parts;
}

/**
 * What a text, rewrap or QA review would write, so a fresh preview taken just
 * before Apply can be compared with the reviewed one. It binds the exact
 * bytes by hash: the visible diff is cut off on large files.
 */
export const reviewSignature = (preview: Preview) =>
  JSON.stringify([
    preview.action,
    [...preview.paths].sort(),
    preview.rewrap?.previews.map((row) => [row.file_name, row.after]),
    preview.publication?.map((row) => [row.path, row.before, row.after]),
  ]);

/** The parts an apply includes, in words: "12 files, 1 image, 3 QA fixes". */
export const pendingSummary = (parts: PendingPart[]) =>
  parts.map((part) => part.summary).join(", ");
