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
export function dependencies() {
  const local = path.join(app, "node_modules");
  if (fs.existsSync(path.join(local, "vite/bin/vite.js"))) return local;
  const existing = path.join(legacy, "desktop/node_modules");
  if (!fs.existsSync(path.join(existing, "vite/bin/vite.js")))
    throw new Error(
      "Install app dependencies, or set DAZEDTL_LEGACY_ROOT to the current DazedMTLTool checkout.",
    );
  // Temporary development dependency link, excluded from Git. The new app has
  // its own package manifest and can use a normal local install instead.
  if (!fs.existsSync(local))
    fs.symlinkSync(
      existing,
      local,
      process.platform === "win32" ? "junction" : "dir",
    );
  return local;
}
