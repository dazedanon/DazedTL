// Finds, downloads and installs signed DazedTL releases. A release is a `v`
// tag on every mirror in release/mirrors.json whose archive carries
// release/manifest.json, the hash of every file, signed by a key in
// release/keys. The app stages a verified release in .runtime/update/next; the
// launcher swaps it in before anything runs from the files it replaces.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import http from "node:http";
import https from "node:https";
import { root as checkout } from "./dependencies.mjs";
import { entries, relative } from "./tar.mjs";
import { CHANGELOG, NOTES, parseChangelog, parseNotes } from "./changelog.mjs";

const MANIFEST = "release/manifest.json";
const SIGNATURE = "release/manifest.sig";
const pattern = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/;
// Folders setup owns; no release may write into them.
const reserved = /^(\.git|\.runtime|\.venv|app\/node_modules|app\/dist)(\/|$)/;

/** @typedef {{ format: 1, version: string, files: Record<string, string>, executables: string[] }} Manifest */
/** @typedef {{ name: string, type: "github" | "gitlab" | "forgejo", url: string }} Mirror */

/** Orders release versions, with a prerelease before its release. */
export function compare(left, right) {
  const a = pattern.exec(left);
  const b = pattern.exec(right);
  if (!a || !b) throw new Error("Unreadable release version.");
  for (let index = 1; index <= 3; index++)
    if (Number(a[index]) !== Number(b[index]))
      return Number(a[index]) - Number(b[index]);
  if (!a[4] || !b[4]) return a[4] ? -1 : b[4] ? 1 : 0;
  const x = a[4].split(".");
  const y = b[4].split(".");
  for (let index = 0; index < Math.max(x.length, y.length); index++) {
    if (x[index] === undefined) return -1;
    if (y[index] === undefined) return 1;
    const numeric = /^\d+$/.test(x[index]);
    if (numeric !== /^\d+$/.test(y[index])) return numeric ? -1 : 1;
    if (numeric && Number(x[index]) !== Number(y[index]))
      return Number(x[index]) - Number(y[index]);
    if (!numeric && x[index] !== y[index]) return x[index] < y[index] ? -1 : 1;
  }
  return 0;
}

export const isVersion = (value) =>
  typeof value === "string" && pattern.test(value);

export function folders(root = checkout) {
  const updates = path.join(root, ".runtime", "update");
  return {
    updates,
    next: path.join(updates, "next"),
    previous: path.join(updates, "previous"),
    journal: path.join(updates, "applying.json"),
    revert: path.join(updates, "revert"),
    result: path.join(updates, "result.json"),
  };
}

const sha256 = (data) => crypto.createHash("sha256").update(data).digest("hex");

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/** @returns {Manifest} */
export function parseManifest(bytes) {
  const manifest = JSON.parse(bytes.toString("utf8"));
  const files = manifest?.files;
  if (
    manifest?.format !== 1 ||
    !isVersion(manifest.version) ||
    !files ||
    typeof files !== "object" ||
    !Array.isArray(manifest.executables)
  )
    throw new Error("The release manifest is unreadable.");
  for (const [name, hash] of Object.entries(files))
    if (
      relative(name, 0) !== name ||
      reserved.test(name) ||
      name === MANIFEST ||
      name === SIGNATURE ||
      !/^[0-9a-f]{64}$/.test(String(hash))
    )
      throw new Error(`The release manifest lists an invalid file: ${name}`);
  if (manifest.executables.some((name) => !Object.hasOwn(files, name)))
    throw new Error("The release manifest is unreadable.");
  return manifest;
}

/** The release keys this install trusts; a release can add the next key. */
export function trustedKeys(root = checkout) {
  const folder = path.join(root, "release", "keys");
  if (!fs.existsSync(folder)) return [];
  return fs
    .readdirSync(folder)
    .filter((name) => name.endsWith(".pem"))
    .map((name) =>
      crypto.createPublicKey(fs.readFileSync(path.join(folder, name))),
    );
}

export function signedBy(manifest, signature, keys) {
  const bytes = Buffer.from(signature.toString("utf8").trim(), "base64");
  return keys.some((key) => crypto.verify(null, manifest, key, bytes));
}

/** The installed release, or the package version of a copy without one. */
export function installed(root = checkout) {
  let manifest = null;
  try {
    manifest = parseManifest(fs.readFileSync(path.join(root, MANIFEST)));
  } catch {
    // Copies made between releases carry no manifest.
  }
  const version =
    manifest?.version ??
    readJson(path.join(root, "app", "package.json"))?.version ??
    "0.0.0";
  return { git: fs.existsSync(path.join(root, ".git")), manifest, version };
}

/** @returns {Mirror[]} */
export function mirrors(root = checkout) {
  return JSON.parse(
    fs.readFileSync(path.join(root, "release", "mirrors.json"), "utf8"),
  );
}

/**
 * Downloads a URL into memory, following redirects. Node's fetch always sends
 * the browser header "Sec-Fetch-Mode: cors", which GitLab answers with 406 for
 * archives, so this uses the plain HTTP client instead.
 * @param {string} url
 * @param {{ limit: number, timeout: number, progress?: (received: number, total: number) => void }} options
 * @returns {Promise<Buffer>}
 */
function get(url, options, redirects = 0) {
  const { limit, timeout, progress } = options;
  const { host, protocol } = new URL(url);
  return new Promise((resolve, reject) => {
    const client = protocol === "http:" ? http : https;
    const request = client.get(
      url,
      { headers: { "User-Agent": "DazedTL", Accept: "*/*" }, timeout: 60_000 },
      (response) => {
        const status = response.statusCode ?? 0;
        const location = response.headers.location;
        if (status >= 300 && status < 400 && location) {
          response.resume();
          clearTimeout(deadline);
          if (redirects >= 5)
            reject(new Error(`${host} redirected too often.`));
          else
            resolve(get(new URL(location, url).href, options, redirects + 1));
          return;
        }
        if (status !== 200) {
          response.resume();
          clearTimeout(deadline);
          reject(new Error(`${host} answered ${status}.`));
          return;
        }
        const total = Number(response.headers["content-length"]) || 0;
        const chunks = [];
        let received = 0;
        response.on("data", (chunk) => {
          received += chunk.length;
          if (Math.max(total, received) > limit)
            request.destroy(new Error("The download is larger than expected."));
          chunks.push(chunk);
          progress?.(received, total);
        });
        response.on("end", () => {
          clearTimeout(deadline);
          if (total && received !== total)
            reject(new Error(`The download from ${host} was cut off.`));
          else resolve(Buffer.concat(chunks));
        });
        response.on("error", reject);
      },
    );
    const deadline = setTimeout(
      () => request.destroy(new Error(`${host} took too long to answer.`)),
      timeout,
    );
    request.on("timeout", () =>
      request.destroy(new Error(`${host} stopped answering.`)),
    );
    request.on("error", (error) => {
      clearTimeout(deadline);
      reject(error);
    });
  });
}

/** Reads the release versions from a Git smart HTTP ref advertisement. */
export function tags(advertisement) {
  const versions = new Set();
  let offset = 0;
  while (offset + 4 <= advertisement.length) {
    const size = parseInt(
      advertisement.toString("latin1", offset, offset + 4),
      16,
    );
    if (!Number.isInteger(size) || (size > 0 && size < 4))
      throw new Error("The mirror sent an unreadable tag list.");
    if (size === 0) {
      offset += 4;
      continue;
    }
    const line = advertisement
      .toString("utf8", offset + 4, offset + size)
      .split("\0")[0]
      .trim();
    offset += size;
    const match = /^[0-9a-f]{40,64} refs\/tags\/v(\S+)$/.exec(line);
    if (match && isVersion(match[1])) versions.add(match[1]);
  }
  return [...versions];
}

/**
 * Asks every mirror for its releases and returns the newest one past the
 * installed version, with the mirrors that have it.
 * @param {{ root?: string, channel: "stable" | "beta" }} options
 */
export async function latest({ root = checkout, channel }) {
  const current = installed(root).version;
  const answers = await Promise.allSettled(
    mirrors(root).map(async (mirror) => ({
      mirror,
      versions: tags(
        await get(`${mirror.url}.git/info/refs?service=git-upload-pack`, {
          limit: 4_000_000,
          timeout: 20_000,
        }),
      ),
    })),
  );
  const reached = answers.flatMap((answer) =>
    answer.status === "fulfilled" ? [answer.value] : [],
  );
  if (!reached.length)
    throw new Error(
      "No release mirror could be reached. Check the connection.",
    );
  return choose(reached, channel, current);
}

/**
 * The newest release on any mirror past `current`, with every mirror that has
 * it; the stable channel skips prereleases.
 * @param {{ mirror: Mirror, versions: string[] }[]} found
 * @param {"stable" | "beta"} channel
 * @param {string} current
 */
export function choose(found, channel, current) {
  /** @type {{ version: string, mirrors: Mirror[] } | null} */
  let best = null;
  for (const { mirror, versions } of found)
    for (const version of versions) {
      if (channel === "stable" && version.includes("-")) continue;
      const order = best ? compare(version, best.version) : 1;
      if (order > 0) best = { version, mirrors: [mirror] };
      else if (order === 0 && best) best.mirrors.push(mirror);
    }
  return best && compare(best.version, current) > 0 ? best : null;
}

/** @param {Mirror} mirror */
export function archiveUrl(mirror, version) {
  const tag = `v${version}`;
  if (mirror.type === "github")
    return `${mirror.url}/archive/refs/tags/${tag}.tar.gz`;
  if (mirror.type === "gitlab")
    return `${mirror.url}/-/archive/${tag}/${mirror.url.split("/").pop()}-${tag}.tar.gz`;
  return `${mirror.url}/archive/${tag}.tar.gz`;
}

/**
 * Checks a release archive against its signed manifest: every file it holds
 * must be listed with its hash, and every listed file must be there.
 */
export function verifyArchive(archive, version, keys) {
  /** @type {Map<string, Buffer>} */
  const files = new Map();
  let top = null;
  for (const entry of entries(archive)) {
    const first = entry.path.split("/").find(Boolean);
    top ??= first;
    if (first !== top) throw new Error("The release archive is malformed.");
    const name = relative(entry.path, 1);
    if (!name || entry.type === "directory") continue;
    if (entry.type !== "file")
      throw new Error(
        "The release archive holds a link, which releases never do.",
      );
    if (files.has(name)) throw new Error("The release archive is malformed.");
    files.set(name, entry.data);
  }
  const manifestBytes = files.get(MANIFEST);
  const signature = files.get(SIGNATURE);
  if (!manifestBytes || !signature)
    throw new Error(`Version ${version} is not a signed DazedTL release.`);
  if (!signedBy(manifestBytes, signature, keys))
    throw new Error(
      `Version ${version} is not signed by a trusted DazedTL key.`,
    );
  const manifest = parseManifest(manifestBytes);
  if (manifest.version !== version)
    throw new Error(
      `The release tagged ${version} names itself ${manifest.version}.`,
    );
  for (const [name, data] of files)
    if (
      name !== MANIFEST &&
      name !== SIGNATURE &&
      manifest.files[name] !== sha256(data)
    )
      throw new Error(
        `The release file ${name} does not match its signed hash.`,
      );
  for (const name of Object.keys(manifest.files))
    if (!files.has(name)) throw new Error(`The release is missing ${name}.`);
  return { manifest, files };
}

/** The staged release's manifest after checking its signature and files. */
function staged(next, keys) {
  const manifestBytes = fs.readFileSync(path.join(next, MANIFEST));
  if (
    !signedBy(manifestBytes, fs.readFileSync(path.join(next, SIGNATURE)), keys)
  )
    throw new Error("The downloaded update is not signed by a trusted key.");
  const manifest = parseManifest(manifestBytes);
  for (const [name, hash] of Object.entries(manifest.files))
    if (sha256(fs.readFileSync(path.join(next, name))) !== hash)
      throw new Error("The downloaded update is damaged.");
  return manifest;
}

export function stagedVersion(root = checkout) {
  return readJson(path.join(folders(root).next, MANIFEST))?.version ?? null;
}

/**
 * Downloads a release from the first mirror whose archive verifies and writes
 * it to .runtime/update/next for the launcher.
 * @param {{ root?: string, version: string, sources: Mirror[], progress?: (received: number, total: number) => void }} options
 */
export async function stage({ root = checkout, version, sources, progress }) {
  root = path.resolve(root);
  if (stagedVersion(root) === version) return;
  const keys = trustedKeys(root);
  let failure = new Error("No mirror has this release.");
  for (const mirror of sources) {
    try {
      const archive = await get(archiveUrl(mirror, version), {
        limit: 500_000_000,
        timeout: 30 * 60_000,
        progress,
      });
      writeStaged(root, verifyArchive(archive, version, keys).files);
      return;
    } catch (error) {
      failure = /** @type {Error} */ (error);
    }
  }
  throw failure;
}

/** Leaves a verified release's files for the launcher, replacing any other. */
export function writeStaged(root, files) {
  const { next, revert } = folders(root);
  const partial = `${next}.partial`;
  fs.rmSync(partial, { recursive: true, force: true });
  for (const [name, data] of files) {
    const target = path.join(partial, ...name.split("/"));
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, data);
  }
  fs.rmSync(next, { recursive: true, force: true });
  fs.renameSync(partial, next);
  fs.rmSync(revert, { force: true });
}

/** Asks the launcher to put back the version before the last update. */
export function requestRevert(root = checkout) {
  const { previous, next, revert } = folders(root);
  if (!fs.existsSync(path.join(previous, "meta.json")))
    throw new Error("The previous version is no longer kept.");
  fs.rmSync(next, { recursive: true, force: true });
  fs.writeFileSync(revert, "");
}

/** Withdraws a "Go back" request before the launcher acts on it. */
export function cancelRevert(root = checkout) {
  fs.rmSync(folders(root).revert, { force: true });
}

// Antivirus scanners briefly lock new files on Windows; retry before failing.
function settle(action) {
  for (let attempt = 0; ; attempt++)
    try {
      return action();
    } catch (error) {
      const code = /** @type {NodeJS.ErrnoException} */ (error).code;
      if (attempt >= 20 || !["EBUSY", "EPERM", "EACCES"].includes(code ?? ""))
        throw error;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
    }
}

function place(source, target, executable = false) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const partial = `${target}.dazedtl-new`;
  fs.copyFileSync(source, partial, fs.constants.COPYFILE_FICLONE);
  if (executable && process.platform !== "win32") fs.chmodSync(partial, 0o755);
  try {
    settle(() => fs.renameSync(partial, target));
  } catch (error) {
    fs.rmSync(partial, { force: true });
    throw error;
  }
}

function remove(root, name) {
  const target = path.join(root, ...name.split("/"));
  settle(() => fs.rmSync(target, { force: true }));
  // Drop folders the release emptied, never the install folder itself.
  for (
    let folder = path.dirname(target);
    folder.startsWith(root + path.sep);
    folder = path.dirname(folder)
  )
    try {
      fs.rmdirSync(folder);
    } catch {
      break;
    }
}

const hashOf = (file) => {
  try {
    return sha256(fs.readFileSync(file));
  } catch {
    return null;
  }
};

/**
 * Copies every file the swap touches into .runtime/update/previous, so a
 * failed swap or a later "Go back" restores the install exactly.
 */
function backup(root, names, previous, version) {
  const partial = `${previous}.partial`;
  fs.rmSync(partial, { recursive: true, force: true });
  const missing = [];
  for (const name of names) {
    const source = path.join(root, ...name.split("/"));
    if (!fs.existsSync(source)) missing.push(name);
    else {
      const target = path.join(partial, "files", ...name.split("/"));
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(source, target, fs.constants.COPYFILE_FICLONE);
    }
  }
  fs.writeFileSync(
    path.join(partial, "meta.json"),
    JSON.stringify({ version, missing }),
  );
  fs.rmSync(previous, { recursive: true, force: true });
  fs.renameSync(partial, previous);
}

function restore(root, previous) {
  const meta = readJson(path.join(previous, "meta.json"));
  if (!meta) throw new Error("The previous version is no longer kept.");
  const files = path.join(previous, "files");
  if (fs.existsSync(files))
    for (const file of fs.readdirSync(files, {
      recursive: true,
      withFileTypes: true,
    }))
      if (file.isFile()) {
        const source = path.join(file.parentPath, file.name);
        place(source, path.join(root, path.relative(files, source)));
      }
  for (const name of meta.missing) remove(root, name);
  return meta.version;
}

function record(root, result) {
  const file = folders(root).result;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(
    file,
    JSON.stringify({ ...result, at: new Date().toISOString() }),
  );
  return result;
}

/**
 * Applies what the app left for the launcher: a "Go back" request or a staged
 * release. A swap that stopped midway finishes first. Returns what happened.
 * @returns {{ ok: boolean, version: string, from: string, message?: string } | null}
 */
export function applyPending(root = checkout) {
  root = path.resolve(root);
  const { next, previous, journal, revert, updates } = folders(root);
  const current = installed(root);
  if (current.git) {
    fs.rmSync(updates, { recursive: true, force: true });
    return null;
  }
  const started = readJson(journal);
  if (started?.kind === "revert" || (!started && fs.existsSync(revert))) {
    fs.writeFileSync(journal, JSON.stringify({ kind: "revert" }));
    const version = restore(root, previous);
    for (const target of [previous, next, revert, journal])
      fs.rmSync(target, { recursive: true, force: true });
    return record(root, { ok: true, version, from: current.version });
  }
  if (!started && !fs.existsSync(next)) return null;

  let manifest;
  try {
    manifest = staged(next, trustedKeys(root));
  } catch (error) {
    fs.rmSync(next, { recursive: true, force: true });
    fs.rmSync(journal, { force: true });
    return record(root, {
      ok: false,
      version: stagedVersion(root) ?? "",
      from: current.version,
      message: /** @type {Error} */ (error).message,
    });
  }
  const before = current.manifest?.files ?? {};
  const from = started?.from ?? current.version;
  let saved = !!started;
  try {
    if (!saved) {
      const names = new Set([
        ...Object.keys(before),
        ...Object.keys(manifest.files),
        MANIFEST,
        SIGNATURE,
      ]);
      backup(root, names, previous, current.version);
      fs.writeFileSync(journal, JSON.stringify({ kind: "update", from }));
      saved = true;
    }
    const executables = new Set(manifest.executables);
    for (const [name, hash] of Object.entries(manifest.files)) {
      const target = path.join(root, ...name.split("/"));
      if (hashOf(target) !== hash)
        place(
          path.join(next, ...name.split("/")),
          target,
          executables.has(name),
        );
      // Archives unpacked on Windows or from some ZIPs lose the executable bit.
      else if (executables.has(name) && process.platform !== "win32")
        fs.chmodSync(target, 0o755);
    }
    for (const name of Object.keys(before))
      if (!Object.hasOwn(manifest.files, name)) remove(root, name);
    // The manifest goes last: until it lands, the install still reads as the
    // old version and a restart finishes the swap.
    for (const name of [SIGNATURE, MANIFEST])
      place(path.join(next, name), path.join(root, ...name.split("/")));
  } catch (error) {
    let message = /** @type {Error} */ (error).message;
    // Before the backup completed, the install has not changed.
    if (saved)
      try {
        restore(root, previous);
        fs.rmSync(previous, { recursive: true, force: true });
      } catch {
        message +=
          " The previous version could not be restored either; download DazedTL again.";
      }
    fs.rmSync(next, { recursive: true, force: true });
    fs.rmSync(journal, { force: true });
    return record(root, {
      ok: false,
      version: manifest.version,
      from,
      message,
    });
  }
  fs.rmSync(next, { recursive: true, force: true });
  fs.rmSync(journal, { force: true });
  return record(root, { ok: true, version: manifest.version, from });
}

/**
 * What changed after `after` up to `upTo`, newest first, as the changelog in
 * `dir` lists it; without `after`, `upTo`'s own entry. A prerelease's entry is
 * the pending notes it carries. Unreadable notes are left out, so they never
 * stand in the way of an update.
 * @param {string} dir
 * @param {string | null} after
 * @param {string} upTo
 * @returns {import("./changelog.mjs").Release[]}
 */
export function releaseNotes(dir, after, upTo) {
  if (!isVersion(upTo)) return [];
  if (!isVersion(after) || compare(after, upTo) >= 0) after = null;
  const read = (name) =>
    fs.readFileSync(path.join(dir, ...name.split("/")), "utf8");
  let releases = [];
  try {
    releases = parseChangelog(read(CHANGELOG));
    if (upTo.includes("-"))
      releases.unshift({
        version: upTo,
        date: "",
        sections: parseNotes(read(NOTES)),
      });
  } catch {
    // Keep what was readable.
  }
  return releases.filter(
    ({ version, sections }) =>
      sections.length &&
      isVersion(version) &&
      compare(version, upTo) <= 0 &&
      (after ? compare(version, after) > 0 : compare(version, upTo) === 0),
  );
}

/**
 * What the app shows: versions, a staged or requested swap, its outcome, and
 * the notes of the staged release and of the installed one. The installed
 * notes reach back to `since`, the version an update replaced, which the last
 * outcome names until the app has seen it.
 */
export function status(root = checkout, since = "") {
  const { next, previous, revert, result } = folders(root);
  const current = installed(root);
  const outcome = readJson(result);
  const staged = fs.existsSync(next) ? stagedVersion(root) : null;
  return {
    git: current.git,
    version: current.version,
    staged,
    previous: readJson(path.join(previous, "meta.json"))?.version ?? null,
    revert: fs.existsSync(revert),
    result: outcome,
    notes: {
      staged: staged ? releaseNotes(next, current.version, staged) : [],
      installed: releaseNotes(
        root,
        since || (outcome?.ok ? outcome.from : null),
        current.version,
      ),
    },
  };
}

// The app runs these through Electron's Node, one JSON line per event.
if (import.meta.main) {
  const [command, value] = process.argv.slice(2);
  const say = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);
  try {
    if (command === "status") say(status(checkout, value));
    else if (command === "seen") {
      fs.rmSync(folders().result, { force: true });
      say({ seen: true });
    } else if (command === "check") {
      const found = await latest({
        channel: value === "beta" ? "beta" : "stable",
      });
      say({ latest: found });
    } else if (command === "stage") {
      const found = JSON.parse(value);
      let shown = -1;
      await stage({
        version: found.version,
        sources: found.mirrors,
        progress: (received, total) => {
          const percent = total ? Math.floor((received / total) * 100) : -1;
          if (percent !== shown) say({ progress: (shown = percent) });
        },
      });
      say({ staged: found.version });
    } else if (command === "revert") {
      requestRevert();
      say(status());
    } else if (command === "keep") {
      cancelRevert();
      say(status());
    } else throw new Error(`Unknown update command: ${command}`);
  } catch (error) {
    say({ error: error instanceof Error ? error.message : String(error) });
    process.exitCode = 1;
  }
}
