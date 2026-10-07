/**
 * A path as people read it: inside the home folder it starts with ~, so the
 * part that names the game or file stays in view. Windows paths compare
 * without case.
 */
export function homeRelative(path: string, home = currentHome()) {
  const root = home.replace(/[\\/]+$/, "");
  if (!root) return path;
  const windows = root.includes("\\");
  const same = (a: string, b: string) =>
    windows ? a.toLowerCase() === b.toLowerCase() : a === b;
  if (same(path, root)) return "~";
  const head = path.slice(0, root.length);
  const separator = path[root.length];
  return same(head, root) && (separator === "/" || separator === "\\")
    ? "~" + path.slice(root.length)
    : path;
}

const currentHome = () =>
  typeof window === "undefined" ? "" : window.dazedtl?.home || "";
