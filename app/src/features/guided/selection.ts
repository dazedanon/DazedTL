import type { GuidedFile } from "../../api/contracts.ts";

export type FileGroup = "all" | "database" | "maps" | "common";
export type SelectionGesture = "toggle" | "replace" | "range" | "add-range";

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});
export const sortFiles = (files: GuidedFile[]) =>
  [...files].sort((a, b) => collator.compare(a.name, b.name));
export const fileGroup = (file: GuidedFile): Exclude<FileGroup, "all"> =>
  file.group === "database"
    ? "database"
    : /^Map\d+\.json$/i.test(file.name)
      ? "maps"
      : "common";

export function filterFiles(
  files: GuidedFile[],
  group: FileGroup,
  query: string,
  selected?: ReadonlySet<string>,
) {
  const text = query.trim().toLocaleLowerCase();
  const range = /^(\d+)\s*[-–]\s*(\d+)$/.exec(text);
  const id = /^\d+$/.test(text) ? Number(text) : null;
  return files.filter((file) => {
    if (
      (group !== "all" && fileGroup(file) !== group) ||
      (selected && !selected.has(file.name))
    )
      return false;
    const map = /^Map(\d+)\.json$/i.exec(file.name);
    if (range)
      return (
        !!map &&
        Number(map[1]) >= Number(range[1]) &&
        Number(map[1]) <= Number(range[2])
      );
    if (id !== null) return !!map && Number(map[1]) === id;
    return (
      !text ||
      `${file.name} ${file.title || ""}`.toLocaleLowerCase().includes(text)
    );
  });
}

/** Change one phase's selection without replacing the other phase's checks. */
export function retainOtherScope(
  selected: readonly string[],
  files: readonly GuidedFile[],
  names: readonly string[],
) {
  const scope = new Set(files.map((file) => file.name));
  return [
    ...selected.filter((name) => !scope.has(name)),
    ...names.filter((name) => scope.has(name)),
  ];
}

/** Checkmarks are the scope. Focus is never a second, highlight-only selection. */
export function selectFile(
  selected: readonly string[],
  visible: readonly string[],
  target: string,
  gesture: SelectionGesture,
  anchor: string | null,
) {
  const end = visible.indexOf(target);
  if (end < 0) return { selected: [...selected], anchor };
  const start = anchor === null ? -1 : visible.indexOf(anchor);
  const range = gesture === "range" || gesture === "add-range";
  const names =
    range && start >= 0
      ? visible.slice(Math.min(start, end), Math.max(start, end) + 1)
      : [target];
  const result = new Set(
    gesture === "replace" || gesture === "range" ? [] : selected,
  );
  if (gesture === "toggle" && result.has(target)) result.delete(target);
  else for (const name of names) result.add(name);
  return {
    selected: [...result],
    anchor: range && start >= 0 ? anchor : target,
  };
}

export function selectMatching(
  selected: readonly string[],
  matching: readonly string[],
  add: boolean,
) {
  const result = new Set(selected);
  for (const name of matching) {
    if (add) result.add(name);
    else result.delete(name);
  }
  return [...result];
}
