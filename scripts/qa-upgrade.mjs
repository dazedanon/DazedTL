// The previous-release QA check: Text QA tasks the latest earlier release
// made, one finished and one in review, continue, finish and apply with this
// checkout's code. It fails when a change breaks saved QA work without
// bumping QA_RULES_VERSION. See "Previous-release QA check" in
// docs/development.md.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { bundledGit, python, requireNode, root } from "./dependencies.mjs";
import { extract } from "./tar.mjs";
import { previousRelease } from "./testkit/checkout.mjs";
import { readOptions } from "./testkit/options.mjs";

requireNode();
const { option } = readOptions(
  "Usage: node scripts/qa-upgrade.mjs [--tag <release tag>] [--work <folder>]",
  { "--tag": "value", "--work": "value" },
);
if (!fs.existsSync(python))
  throw new Error("Run node scripts/setup.mjs first; it creates .venv.");
const gitBin = bundledGit()?.bin;
const git = (...args) =>
  execFileSync(
    gitBin && fs.existsSync(gitBin) ? path.join(gitBin, "git.exe") : "git",
    args,
    { cwd: root, maxBuffer: 1 << 30 },
  );
const tag = option("--tag") || previousRelease();

// A folder with spaces and Japanese, as users' folders often have.
const work = path.join(
  path.resolve(
    option("--work") ||
      fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-qa-upgrade-")),
  ),
  "QA チェック (前版)",
);
if (fs.existsSync(work) && fs.readdirSync(work).length)
  throw new Error(`Choose an empty work folder; ${work} has files.`);
const release = path.join(work, "release");
extract(git("archive", "--format=tar.gz", tag, "backend", "scripts"), release);

// The release's own copy of the driver makes its tasks, as that release's
// reviewers would; releases before the check had none.
const driver = (code) => path.join(code, "scripts", "qa_upgrade.py");
const phases = [
  ["game", root, driver(root)],
  [
    "old",
    release,
    fs.existsSync(driver(release)) ? driver(release) : driver(root),
  ],
  ["new", root, driver(root)],
];
const environment = Object.fromEntries(
  Object.entries(process.env).filter(([key]) =>
    [
      "PATH",
      "USERPROFILE",
      "SYSTEMROOT",
      "WINDIR",
      "TEMP",
      "TMP",
      "TMPDIR",
      "LANG",
      "LC_ALL",
    ].includes(key),
  ),
);
console.log(`Text QA tasks of ${tag}, continued by this checkout, in ${work}`);
for (const [phase, code, script] of phases) {
  const result = spawnSync(
    python,
    ["-I", "-X", "utf8", "-B", script, phase, code, work],
    {
      cwd: work,
      stdio: "inherit",
      windowsHide: true,
      env: {
        ...environment,
        // Offline, without the user's engine checkout or settings.
        PYTHON_DOTENV_DISABLED: "1",
        API_KEY_OPTIONAL: "true",
        DAZEDTL_TEST_OFFLINE: "1",
        DAZEDTL_LEGACY_ROOT: path.join(work, "missing-engine"),
        DAZEDTL_ENGINE_SOURCE: path.join(work, "missing-engine"),
      },
    },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    console.error(`The ${phase} phase failed; its files are in ${work}.`);
    process.exit(1);
  }
}
if (!option("--work")) fs.rmSync(path.dirname(work), { recursive: true });
