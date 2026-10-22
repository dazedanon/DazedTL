// Another version of DazedTL beside this checkout, for scenarios built by an
// earlier release or by the commit before a fix: a detached Git worktree in
// .runtime/checkouts that shares this checkout's installed packages when its
// locks match, so it starts in seconds, and installs its own Node packages
// when they differ.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import { bundledGit, root, runtime } from "../dependencies.mjs";
import { installElectron, installPackages } from "../setup.mjs";

const gitBin = bundledGit()?.bin;
/** Runs Git: on Windows the one setup installs, when it has. */
const git = (args, cwd = root) =>
  execFileSync(
    gitBin && fs.existsSync(gitBin) ? path.join(gitBin, "git.exe") : "git",
    args,
    { cwd, encoding: "utf8" },
  ).trim();

/** The newest stable release tag before this checkout's own version. */
export function previousRelease() {
  const head = git(["rev-parse", "HEAD"]);
  for (const tag of git([
    "tag",
    "--list",
    "v*",
    "--sort=-v:refname",
    "--merged",
    "HEAD",
  ]).split("\n"))
    if (
      /^v\d+\.\d+\.\d+$/.test(tag) &&
      git(["rev-parse", `${tag}^{commit}`]) !== head
    )
      return tag;
  throw new Error(
    "No earlier release tag is reachable from this checkout; fetch the tags with git fetch --tags.",
  );
}

/** What the package installs depend on, without the app's own version. */
function locks(folder) {
  const read = (file) => fs.readFileSync(path.join(folder, file), "utf8");
  const packages = JSON.parse(read("app/package-lock.json"));
  delete packages.version;
  delete packages.packages?.[""]?.version;
  return {
    python: crypto
      .createHash("sha256")
      .update(read("backend/requirements.lock"))
      .digest("hex"),
    node: crypto
      .createHash("sha256")
      .update(JSON.stringify(packages))
      .digest("hex"),
  };
}

/**
 * The folder of a checkout at `ref`, made on first use. Its app runs with
 * this checkout's Python environment, which `env` names.
 * @returns {Promise<{ root: string, commit: string, env: Record<string, string> }>}
 */
export async function checkout(ref) {
  const commit = git(["rev-parse", "--verify", `${ref}^{commit}`]);
  const folder = path.join(runtime, "checkouts", commit.slice(0, 12));
  if (!fs.existsSync(path.join(folder, "scripts"))) {
    fs.rmSync(folder, { recursive: true, force: true });
    git(["worktree", "prune"]);
    git(["worktree", "add", "--detach", folder, commit]);
  }
  const ours = locks(root);
  const theirs = locks(folder);
  if (ours.python !== theirs.python)
    throw new Error(
      `${ref} locks other Python packages; run node scripts/setup.mjs in ${folder} first.`,
    );
  const modules = path.join(folder, "app/node_modules");
  if (!fs.existsSync(path.join(modules, ".package-lock.json"))) {
    if (ours.node === theirs.node)
      // A copy, since setup refuses linked packages; on Btrfs or APFS it
      // shares the files' blocks.
      fs.cpSync(path.join(root, "app/node_modules"), modules, {
        recursive: true,
        verbatimSymlinks: true,
        mode: fs.constants.COPYFILE_FICLONE,
      });
    // A version before or after a package change brings its own, as its
    // setup would.
    else await installPackages(path.join(folder, "app"), "dev");
  }
  // Electron's download is cached, so each checkout unpacks it quickly.
  const electron = path.join(modules, "electron");
  if (!fs.existsSync(path.join(electron, "path.txt")))
    await installElectron(electron);
  return {
    root: folder,
    commit,
    env: {
      DAZEDTL_PYTHON: path.join(
        root,
        ".venv",
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      ),
    },
  };
}
