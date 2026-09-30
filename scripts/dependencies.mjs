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
export function requireNode() {
  const expected = fs
    .readFileSync(path.join(root, ".node-version"), "utf8")
    .trim();
  if (process.versions.node !== expected)
    throw new Error(`Use Node ${expected}, as pinned in .node-version.`);
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
