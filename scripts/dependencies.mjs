import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
export const app = path.join(root, "app");
/** Downloads, runtimes and update staging live here, outside version control. */
export const runtime = path.join(root, ".runtime");
/** The checkout's Python environment, created by setup. */
export const python = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
/** Download names of the pinned runtimes for each supported system. */
export const platforms = {
  "win32-x64": { node: "win-x64.zip", python: "x86_64-pc-windows-msvc" },
  "linux-x64": { node: "linux-x64.tar.gz", python: "x86_64-unknown-linux-gnu" },
  "linux-arm64": {
    node: "linux-arm64.tar.gz",
    python: "aarch64-unknown-linux-gnu",
  },
  "darwin-x64": { node: "darwin-x64.tar.gz", python: "x86_64-apple-darwin" },
  "darwin-arm64": {
    node: "darwin-arm64.tar.gz",
    python: "aarch64-apple-darwin",
  },
};
// Windows on Arm runs the x64 runtimes, which every Python wheel supports.
export const platform =
  process.platform === "win32"
    ? "win32-x64"
    : `${process.platform}-${process.arch}`;
export function requireNode({ exact = false } = {}) {
  const expected = fs
    .readFileSync(path.join(root, ".node-version"), "utf8")
    .trim();
  const current = process.versions.node;
  const [major, minor, patch] = expected.split(".").map(Number);
  const [currentMajor, currentMinor, currentPatch] = current
    .split(".")
    .map(Number);
  const compatible =
    /^\d+\.\d+\.\d+$/.test(current) &&
    currentMajor === major &&
    (currentMinor > minor || (currentMinor === minor && currentPatch >= patch));
  if (exact ? current !== expected : !compatible)
    throw new Error(
      exact
        ? `Use Node ${expected} for setup, as pinned in .node-version. Found ${current}.`
        : `Use Node ${expected} or a newer Node ${major} release. Found ${current}.`,
    );
}
export function dependencies() {
  requireNode();
  const local = path.join(app, "node_modules");
  if (
    fs.lstatSync(local, { throwIfNoEntry: false })?.isSymbolicLink() ||
    !fs.existsSync(path.join(local, "vite/bin/vite.js"))
  )
    throw new Error(
      "Run node scripts/setup.mjs to install the locked application dependencies.",
    );
  return local;
}
