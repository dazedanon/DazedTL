import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import zlib from "node:zlib";
import {
  applyPending,
  choose,
  installed,
  requestRevert,
  tags,
  verifyArchive,
  writeStaged,
} from "../scripts/update.mjs";

const keys = crypto.generateKeyPairSync("ed25519");
const sha256 = (data: Buffer) =>
  crypto.createHash("sha256").update(data).digest("hex");

/** A gzip tar holding `entries` under one top folder, as a mirror serves it. */
function tarball(entries: { name: string; data?: Buffer; link?: string }[]) {
  const blocks: Buffer[] = [];
  for (const entry of entries) {
    const header = Buffer.alloc(512);
    const data = entry.data ?? Buffer.alloc(0);
    header.write(`DazedTL-2.0.0/${entry.name}`, 0);
    header.write("0000644\0", 100);
    header.write(`${data.length.toString(8).padStart(11, "0")}\0`, 124);
    header.write(entry.link ? "2" : "0", 156);
    if (entry.link) header.write(entry.link, 157);
    header.write("ustar\0", 257);
    blocks.push(header, data, Buffer.alloc((512 - (data.length % 512)) % 512));
  }
  return zlib.gzipSync(Buffer.concat([...blocks, Buffer.alloc(1024)]));
}

/** A signed release's files, as the release script writes them. */
function release(
  version: string,
  files: Record<string, string>,
  signer = keys.privateKey,
) {
  const data = new Map(
    Object.entries(files).map(([name, text]) => [name, Buffer.from(text)]),
  );
  const manifest = Buffer.from(
    JSON.stringify({
      format: 1,
      version,
      files: Object.fromEntries(
        [...data].map(([name, content]) => [name, sha256(content)]),
      ),
      executables: Object.hasOwn(files, "START.sh") ? ["START.sh"] : [],
    }),
  );
  data.set("release/manifest.json", manifest);
  data.set(
    "release/manifest.sig",
    Buffer.from(crypto.sign(null, manifest, signer).toString("base64")),
  );
  return data;
}

const archive = (
  files: Map<string, Buffer>,
  extra: { name: string; data?: Buffer; link?: string }[] = [],
) => tarball([...[...files].map(([name, data]) => ({ name, data })), ...extra]);

test("only an archive matching a trusted signed manifest is accepted", () => {
  const files = release("2.0.0", { "a.txt": "two", "START.sh": "run" });
  const trusted = [keys.publicKey];
  assert.equal(
    verifyArchive(archive(files), "2.0.0", trusted).manifest.version,
    "2.0.0",
  );
  const changed = new Map(files).set("a.txt", Buffer.from("tampered"));
  assert.throws(
    () => verifyArchive(archive(changed), "2.0.0", trusted),
    /signed hash/,
  );
  const extra = [{ name: "extra.txt", data: Buffer.from("x") }];
  assert.throws(
    () => verifyArchive(archive(files, extra), "2.0.0", trusted),
    /signed hash/,
  );
  const missing = new Map(files);
  missing.delete("a.txt");
  assert.throws(
    () => verifyArchive(archive(missing), "2.0.0", trusted),
    /missing a\.txt/,
  );
  const link = [{ name: "link", link: "a.txt" }];
  assert.throws(
    () => verifyArchive(archive(files, link), "2.0.0", trusted),
    /link/,
  );
  assert.throws(
    () => verifyArchive(archive(files), "2.0.1", trusted),
    /names itself/,
  );
  const stranger = crypto.generateKeyPairSync("ed25519").privateKey;
  const forged = release("2.0.0", { "a.txt": "two" }, stranger);
  assert.throws(
    () => verifyArchive(archive(forged), "2.0.0", trusted),
    /trusted/,
  );
});

test("the newest tag on any mirror wins, and stable skips prereleases", () => {
  const line = (text: string) =>
    `${(text.length + 4).toString(16).padStart(4, "0")}${text}`;
  const sha = "a".repeat(40);
  const advertisement = Buffer.from(
    line("# service=git-upload-pack\n") +
      "0000" +
      line(`${sha} HEAD\0multi_ack symref=HEAD:refs/heads/main\n`) +
      line(`${sha} refs/tags/v2.0.0\n`) +
      line(`${sha} refs/tags/v2.0.0^{}\n`) +
      line(`${sha} refs/tags/v2.1.0-beta.2\n`) +
      line(`${sha} refs/tags/v2.1.0-beta.10\n`) +
      line(`${sha} refs/tags/latest\n`) +
      "0000",
  );
  const versions = tags(advertisement);
  assert.deepEqual(versions.sort(), ["2.0.0", "2.1.0-beta.10", "2.1.0-beta.2"]);
  const github = {
    name: "GitHub",
    type: "github" as const,
    url: "https://github",
  };
  const gitgud = {
    name: "GitGud",
    type: "gitlab" as const,
    url: "https://gitgud",
  };
  const found = [
    { mirror: github, versions },
    { mirror: gitgud, versions: ["2.0.0"] },
  ];
  assert.deepEqual(choose(found, "stable", "1.9.0"), {
    version: "2.0.0",
    mirrors: [github, gitgud],
  });
  assert.equal(choose(found, "beta", "2.0.0")?.version, "2.1.0-beta.10");
  assert.equal(choose(found, "stable", "2.0.0"), null);
});

test("an update swaps tracked files in place, and Go back or a failure restores them", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-update-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const write = (files: Map<string, Buffer>) => {
    for (const [name, data] of files) {
      fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
      fs.writeFileSync(path.join(root, name), data);
    }
  };
  const tree = () =>
    Object.fromEntries(
      fs
        .readdirSync(root, { recursive: true, withFileTypes: true })
        .filter(
          (entry) => entry.isFile() && !entry.parentPath.includes(".runtime"),
        )
        .map((entry) => {
          const file = path.join(entry.parentPath, entry.name);
          return [
            path.relative(root, file).split(path.sep).join("/"),
            fs.readFileSync(file, "utf8"),
          ];
        }),
    );
  write(
    release("1.0.0", {
      "a.txt": "one",
      "old/b.txt": "gone soon",
      "START.sh": "run",
    }),
  );
  fs.mkdirSync(path.join(root, "release/keys"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "release/keys/test.pem"),
    keys.publicKey.export({ type: "spki", format: "pem" }),
  );
  fs.writeFileSync(path.join(root, "notes.txt"), "untracked");
  const original = tree();
  const next = release("2.0.0", {
    "a.txt": "two",
    "new/c.txt": "added",
    "START.sh": "run",
  });

  writeStaged(root, next);
  assert.equal(applyPending(root)?.ok, true);
  assert.equal(installed(root).version, "2.0.0");
  const updated = tree();
  assert.equal(updated["a.txt"], "two");
  assert.equal(updated["new/c.txt"], "added");
  assert.equal(updated["notes.txt"], "untracked");
  assert.equal(fs.existsSync(path.join(root, "old")), false);
  if (process.platform !== "win32")
    assert.ok(fs.statSync(path.join(root, "START.sh")).mode & 0o100);

  requestRevert(root);
  assert.equal(applyPending(root)?.version, "1.0.0");
  assert.deepEqual(tree(), original);

  // A file that cannot be replaced puts every swapped file back.
  writeStaged(root, next);
  const rename = fs.renameSync;
  fs.renameSync = (from: fs.PathLike, to: fs.PathLike) => {
    if (String(to).endsWith("c.txt"))
      throw Object.assign(new Error("Disk failure."), { code: "EIO" });
    rename(from, to);
  };
  try {
    const result = applyPending(root);
    assert.equal(result?.ok, false);
    assert.match(result?.message ?? "", /Disk failure/);
  } finally {
    fs.renameSync = rename;
  }
  assert.deepEqual(tree(), original);
  assert.equal(applyPending(root), null);
});
