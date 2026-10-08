import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { root, dependencies } from "./dependencies.mjs";

// Writes the renderer contracts and protocol manifest from the Python API
// contracts; --check reports stale files instead.
const check = process.argv.includes("--check");
const prettier = await import(
  pathToFileURL(path.join(dependencies(), "prettier/index.mjs")).href
);
const python = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const result = spawnSync(
  python,
  [
    "-I",
    "-X",
    "utf8",
    "-B",
    "-c",
    "import sys; sys.path.insert(0, 'backend'); from dazedtl.api.contracts.typescript import main; main()",
  ],
  { cwd: root, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 },
);
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.error?.message || "");
  process.exit(result.status || 1);
}
const rendered = JSON.parse(result.stdout);
const outputs = [
  {
    file: "app/src/api/contracts.ts",
    text: await prettier.format(rendered.typescript, {
      filepath: path.join(root, "app/src/api/contracts.ts"),
    }),
  },
  {
    file: "backend/dazedtl/api/protocol.json",
    text: JSON.stringify(rendered.protocol, null, 2) + "\n",
  },
];
let stale = false;
for (const { file, text } of outputs) {
  const target = path.join(root, file);
  if (fs.existsSync(target) && fs.readFileSync(target, "utf8") === text)
    continue;
  if (check) {
    console.error(`${file} does not match the Python API contracts.`);
    stale = true;
  } else fs.writeFileSync(target, text);
}
if (stale) {
  console.error("Run node scripts/contracts.mjs to regenerate them.");
  process.exitCode = 1;
}
