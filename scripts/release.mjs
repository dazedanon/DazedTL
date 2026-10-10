// Publishes a DazedTL release from the dev branch: runs the checks, signs a
// manifest of every file, tags it and pushes it to every mirror. A stable
// release fast-forwards main to dev and commits there, once CI has passed for
// that commit on GitHub, and files release/notes.md under its version in
// CHANGELOG.md; a prerelease such as 2.1.0-beta.1 is tagged on dev for the
// beta channel and leaves the notes pending.
//
//   node scripts/release.mjs key               create the signing key, once
//   node scripts/release.mjs 2.0.0 [--local]   release; --local skips pushing
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync, spawnSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { root } from "./dependencies.mjs";
import {
  CHANGELOG,
  NOTES,
  addRelease,
  formatSections,
  notesTemplate,
  parseNotes,
} from "./changelog.mjs";
import {
  compare,
  isVersion,
  mirrors,
  trustedKeys,
  verifyArchive,
} from "./update.mjs";

const keyFile =
  process.env.DAZEDTL_RELEASE_KEY ||
  path.join(
    process.platform === "win32"
      ? process.env.APPDATA || os.homedir()
      : process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config"),
    "dazedtl-release",
    "signing-key.pem",
  );
const remote = "all";

const git = (...args) =>
  execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
function step(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit" });
  if (result.status !== 0)
    throw new Error(`${[path.basename(command), ...args].join(" ")} failed.`);
}
/** The public key's bytes, from a public key or the private key it pairs with. */
const der = (key) =>
  (key instanceof crypto.KeyObject && key.type === "public"
    ? key
    : crypto.createPublicKey(key)
  ).export({ type: "spki", format: "der" });

function createKey() {
  if (fs.existsSync(keyFile))
    throw new Error(`A signing key already exists at ${keyFile}.`);
  const { privateKey, publicKey } = crypto.generateKeyPairSync("ed25519");
  const name = crypto
    .createHash("sha256")
    .update(der(publicKey))
    .digest("hex")
    .slice(0, 16);
  const file = path.join("release", "keys", `${name}.pem`);
  fs.mkdirSync(path.join(root, "release", "keys"), { recursive: true });
  fs.writeFileSync(
    path.join(root, file),
    publicKey.export({ type: "spki", format: "pem" }),
  );
  fs.mkdirSync(path.dirname(keyFile), { recursive: true, mode: 0o700 });
  fs.writeFileSync(
    keyFile,
    privateKey.export({ type: "pkcs8", format: "pem" }),
    { mode: 0o600, flag: "wx" },
  );
  console.log(
    [
      `Created the signing key at ${keyFile}.`,
      "Back it up somewhere safe: installs only accept releases signed by a key they trust.",
      `Commit ${file} so installs trust it.`,
    ].join("\n"),
  );
}

/** The signing key, after checking that committed installs trust it. */
function signingKey() {
  if (!fs.existsSync(keyFile))
    throw new Error(
      `No signing key at ${keyFile}. Run: node scripts/release.mjs key`,
    );
  const key = crypto.createPrivateKey(fs.readFileSync(keyFile));
  const committed = new Set(git("ls-files", "release/keys").split("\n"));
  const trusted = fs
    .readdirSync(path.join(root, "release", "keys"))
    .some(
      (name) =>
        committed.has(`release/keys/${name}`) &&
        der(fs.readFileSync(path.join(root, "release", "keys", name))).equals(
          der(key),
        ),
    );
  if (!trusted)
    throw new Error(
      "Commit the signing key's public half in release/keys first.",
    );
  return key;
}

/**
 * Names a repository by its site and path, so the SSH and HTTPS addresses of
 * one mirror match: git@ssh.gitgud.io:DazedAnon/DazedTL.git and
 * https://gitgud.io/DazedAnon/DazedTL both give gitgud.io/dazedanon/dazedtl.
 */
function repository(url) {
  const scp = /^[^@/]+@([^:/]+):(.+)$/.exec(url);
  let host = scp?.[1];
  let pathname = scp?.[2];
  if (!scp)
    try {
      ({ hostname: host, pathname } = new URL(url));
    } catch {
      return "";
    }
  const site = String(host).split(".").slice(-2).join(".");
  const name = String(pathname)
    .replace(/\.git$/, "")
    .split("/")
    .filter(Boolean)
    .slice(-2)
    .join("/");
  return `${site}/${name}`.toLowerCase();
}

/** Every mirror must be a push URL of the "all" remote. */
function checkRemote() {
  let urls = [];
  try {
    urls = git("remote", "get-url", "--push", "--all", remote).split("\n");
  } catch {
    // Reported below with the commands that fix it.
  }
  const missing = mirrors(root).filter(
    (mirror) => !urls.some((url) => repository(url) === repository(mirror.url)),
  );
  if (missing.length)
    throw new Error(
      [
        `Add every mirror as a push URL of the "${remote}" remote, for example:`,
        "",
        `  git remote add ${remote} git@github.com:dazedanon/DazedTL.git`,
        `  git remote set-url --add --push ${remote} git@github.com:dazedanon/DazedTL.git`,
        `  git remote set-url --add --push ${remote} git@ssh.gitgud.io:DazedAnon/DazedTL.git`,
        `  git remote set-url --add --push ${remote} git@git-ssh.dazedtl.dev:dazed/DazedTL.git`,
        "",
        `Missing: ${missing.map((mirror) => mirror.url).join(", ")}`,
      ].join("\n"),
    );
}

/** A GitHub API read, or null when GitHub has no such object. */
async function github(route) {
  const response = await fetch(`https://api.github.com/${route}`, {
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": "DazedTL release",
    },
    signal: AbortSignal.timeout(30_000),
  });
  if (response.status === 404 || response.status === 422) return null;
  if (!response.ok)
    throw new Error(
      `GitHub answered ${response.status} while checking CI. Try again later.`,
    );
  return response.json();
}

/**
 * Requires the CI workflow to have passed on GitHub for `commit`, pushing
 * dev there first when GitHub does not have it, so main only moves to commits
 * whose checks and live tests passed on Windows and Linux. A run still going
 * is waited for; a failed or cancelled one stops the release.
 * @param {string} commit
 * @param {boolean} push
 */
export async function requireCI(commit, push) {
  const site = mirrors(root).find((mirror) => mirror.type === "github");
  if (!site) throw new Error("release/mirrors.json names no GitHub mirror.");
  const repository = new URL(site.url).pathname.replace(/^\/|\.git$/g, "");
  const short = commit.slice(0, 7);
  if (!(await github(`repos/${repository}/commits/${commit}`))) {
    if (!push)
      throw new Error(`Push dev to GitHub so CI can test ${short} first.`);
    step("git", ["push", remote, "dev"]);
  }
  const started = Date.now();
  let shown = "";
  for (;;) {
    const found = await github(
      `repos/${repository}/actions/runs?head_sha=${commit}&per_page=50`,
    );
    const run = (found?.workflow_runs || [])
      .filter((item) => item.path === ".github/workflows/ci.yml")
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
    if (run?.status === "completed") {
      if (run.conclusion === "success") {
        console.log(`CI passed for ${short}.`);
        return;
      }
      const jobs = await github(
        `repos/${repository}/actions/runs/${run.id}/jobs`,
      );
      const failed = (jobs?.jobs || [])
        .filter((job) => job.conclusion !== "success")
        .map((job) => job.name);
      throw new Error(
        [
          `CI ${run.conclusion === "failure" ? "failed" : `ended as ${run.conclusion}`} for ${short}${failed.length ? `: ${failed.join(", ")}` : ""}.`,
          run.html_url,
          "Fix it on dev, or rerun it there if it failed for an unrelated reason, then release again.",
        ].join("\n"),
      );
    }
    if (!run && Date.now() - started > 5 * 60_000)
      throw new Error(`CI did not start for ${short} on GitHub.`);
    if (Date.now() - started > 60 * 60_000)
      throw new Error(`CI for ${short} did not finish within an hour.`);
    const status = run
      ? `${run.status.replace("_", " ")}: ${run.html_url}`
      : "waiting to start";
    if (status !== shown) console.log(`CI for ${short} is ${status}`);
    shown = status;
    await delay(30_000);
  }
}

/** Hashes the staged blobs, which are exactly what the mirrors archive. */
function manifestFor(version) {
  const rows = execFileSync("git", ["ls-files", "-s", "-z"], { cwd: root })
    .toString("utf8")
    .split("\0")
    .filter(Boolean)
    .map((row) => {
      const [meta, name] = row.split("\t");
      const [mode, blob] = meta.split(" ");
      return { mode, blob, name };
    })
    .filter((row) => !row.name.startsWith("release/manifest."));
  const link = rows.find((row) => row.mode === "120000");
  if (link) throw new Error(`Releases cannot hold links: ${link.name}`);
  const output = execFileSync("git", ["cat-file", "--batch"], {
    cwd: root,
    input: rows.map((row) => row.blob).join("\n") + "\n",
    maxBuffer: 1 << 30,
  });
  const files = {};
  let offset = 0;
  for (const row of rows) {
    const end = output.indexOf(10, offset);
    const size = Number(output.toString("utf8", offset, end).split(" ")[2]);
    const content = output.subarray(end + 1, end + 1 + size);
    files[row.name] = crypto.createHash("sha256").update(content).digest("hex");
    offset = end + 1 + size + 1;
  }
  return {
    format: 1,
    version,
    files,
    executables: rows
      .filter((row) => row.mode === "100755")
      .map((row) => row.name),
  };
}

/** Today's date where the release is made, as Keep a Changelog writes it. */
function today() {
  const now = new Date();
  return [now.getFullYear(), now.getMonth() + 1, now.getDate()]
    .map((part) => String(part).padStart(2, "0"))
    .join("-");
}

/** Where a changelog entry's version heading links: its changes on GitHub. */
function compareLink(version, previous) {
  const site = mirrors(root).find((mirror) => mirror.type === "github");
  if (!site) throw new Error("release/mirrors.json names no GitHub mirror.");
  const base = site.url.replace(/\/$/, "");
  return previous
    ? `${base}/compare/v${previous}...v${version}`
    : `${base}/releases/tag/v${version}`;
}

function setVersion(version) {
  for (const file of ["app/package.json", "app/package-lock.json"]) {
    const target = path.join(root, file);
    const data = JSON.parse(fs.readFileSync(target, "utf8"));
    data.version = version;
    if (data.packages?.[""]) data.packages[""].version = version;
    fs.writeFileSync(target, `${JSON.stringify(data, null, 2)}\n`);
  }
}

async function release(version, push) {
  if (!isVersion(version))
    throw new Error(
      `Give a version such as 2.0.0 or 2.1.0-beta.1, not "${version}".`,
    );
  if (git("branch", "--show-current") !== "dev")
    throw new Error("Release from the dev branch.");
  if (git("status", "--porcelain"))
    throw new Error("Commit or stash your changes first.");
  const released = git("tag", "--list", "v*")
    .split("\n")
    .map((tag) => tag.slice(1))
    .filter(isVersion);
  const newer = released.filter((tag) => compare(tag, version) >= 0);
  if (newer.length)
    throw new Error(
      `Version ${version} must be newer than ${newer.join(", ")}.`,
    );
  const stable = !version.includes("-");
  const notes = parseNotes(fs.readFileSync(path.join(root, NOTES), "utf8"));
  if (stable && !notes.length)
    throw new Error(
      `Write what changed for users in ${NOTES} first; see docs/development.md#release-notes.`,
    );
  const key = signingKey();
  if (push) checkRemote();
  step(process.execPath, ["scripts/test.mjs"]);
  step(process.execPath, ["scripts/build.mjs"]);

  if (stable) await requireCI(git("rev-parse", "HEAD"), push);
  const branch = stable ? "main" : "dev";
  const tag = `v${version}`;
  const touched = [
    "app/package.json",
    "app/package-lock.json",
    CHANGELOG,
    NOTES,
    "release/manifest.json",
    "release/manifest.sig",
  ];
  if (stable) {
    const exists =
      spawnSync(
        "git",
        ["rev-parse", "--verify", "--quiet", "refs/heads/main"],
        { cwd: root },
      ).status === 0;
    git("switch", ...(exists ? ["main"] : ["-c", "main"]));
  }
  try {
    if (stable) git("merge", "--ff-only", "dev");
    setVersion(version);
    git("add", "app/package.json", "app/package-lock.json");
    if (stable) {
      const changelog = path.join(root, CHANGELOG);
      const previous = released
        .filter((tag) => !tag.includes("-"))
        .sort(compare)
        .at(-1);
      fs.writeFileSync(
        changelog,
        addRelease(
          fs.existsSync(changelog) ? fs.readFileSync(changelog, "utf8") : "",
          {
            version,
            date: today(),
            sections: notes,
            link: compareLink(version, previous),
          },
        ),
      );
      fs.writeFileSync(path.join(root, NOTES), notesTemplate);
      git("add", CHANGELOG, NOTES);
    }
    const manifest = Buffer.from(
      `${JSON.stringify(manifestFor(version), null, 2)}\n`,
    );
    fs.writeFileSync(path.join(root, "release/manifest.json"), manifest);
    fs.writeFileSync(
      path.join(root, "release/manifest.sig"),
      `${crypto.sign(null, manifest, key).toString("base64")}\n`,
    );
    git("add", "release/manifest.json", "release/manifest.sig");
    git(
      "commit",
      "-m",
      [
        `chore(release): ${version}`,
        "",
        `- Set the version to ${version}`,
        ...(stable ? [`- File the release notes in ${CHANGELOG}`] : []),
        "- Sign the release manifest",
      ].join("\n"),
    );
    // Verbatim keeps the notes' "###" headings, which Git strips as comments.
    git(
      "tag",
      "-a",
      tag,
      "--cleanup=verbatim",
      "-m",
      [`DazedTL ${version}`, ...(notes.length ? [formatSections(notes)] : [])]
        .join("\n\n")
        .trimEnd(),
    );
  } catch (error) {
    spawnSync("git", ["restore", "--staged", "--worktree", "--", ...touched], {
      cwd: root,
    });
    for (const file of touched)
      if (!git("ls-files", file))
        fs.rmSync(path.join(root, file), { force: true });
    git("switch", "dev");
    throw error;
  }

  // Prove that an install accepts the tag exactly as a mirror will serve it.
  const archive = execFileSync(
    "git",
    [
      "-c",
      "core.autocrlf=false",
      "-c",
      "core.eol=lf",
      "archive",
      "--format=tar.gz",
      `--prefix=DazedTL-${version}/`,
      tag,
    ],
    { cwd: root, maxBuffer: 1 << 30 },
  );
  verifyArchive(archive, version, trustedKeys(root));

  let published = !push;
  if (push) {
    const pushed = spawnSync(
      "git",
      ["push", remote, ...(stable ? [branch] : []), tag],
      { cwd: root, stdio: "inherit" },
    );
    published = pushed.status === 0;
  }
  if (stable) {
    git("switch", "dev");
    git("merge", "--ff-only", "main");
  }
  const retry = `git push ${remote} ${stable ? `${branch} ` : ""}${tag}`;
  if (!push)
    console.log(`Tagged ${version} locally. Publish it with: ${retry}`);
  else if (published) console.log(`Released ${version}.`);
  else {
    console.error(
      `Tagged ${version}, but some mirrors did not accept it. Run "${retry}" again once they are reachable.`,
    );
    process.exitCode = 1;
  }
}

if (import.meta.main)
  try {
    const [command] = process.argv.slice(2);
    if (command === "key") createKey();
    else await release(command ?? "", !process.argv.includes("--local"));
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
