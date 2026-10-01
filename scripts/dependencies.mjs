import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
export const app = path.join(root, "app");
export const legacy =
  process.env.DAZEDTL_LEGACY_ROOT || path.resolve(root, "../DazedMTLTool");
export function requireNode({ exact = false } = {}) {
  const expected = fs
    .readFileSync(path.join(root, ".node-version"), "utf8")
    .trim();
  const current = process.versions.node;
  const [major, minor, patch] = expected.split(".").map(Number);
  const [currentMajor, currentMinor, currentPatch] = current.split(".").map(Number);
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
