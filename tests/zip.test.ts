import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import zlib from "node:zlib";
import { entries, extract } from "../scripts/zip.mjs";

type Item = { name: string; data?: string; mode?: number; stored?: boolean };

/** Writes a zip the way Electron's build does: local headers, then the central directory. */
function archive(items: Item[], unix = true) {
  const locals: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const item of items) {
    const name = Buffer.from(item.name);
    const data = Buffer.from(item.data ?? "");
    const packed = item.stored ? data : zlib.deflateRawSync(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(item.stored ? 0 : 8, 8);
    local.writeUInt32LE(zlib.crc32(data), 14);
    local.writeUInt32LE(packed.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(name.length, 26);
    locals.push(local, name, packed);
    const header = Buffer.alloc(46);
    header.writeUInt32LE(0x02014b50, 0);
    header.writeUInt16LE(unix ? 0x031e : 0x0014, 4);
    header.writeUInt16LE(item.stored ? 0 : 8, 10);
    header.writeUInt32LE(zlib.crc32(data), 16);
    header.writeUInt32LE(packed.length, 20);
    header.writeUInt32LE(data.length, 24);
    header.writeUInt16LE(name.length, 28);
    header.writeUInt32LE(((item.mode ?? 0) << 16) >>> 0, 38);
    header.writeUInt32LE(offset, 42);
    central.push(header, name);
    offset += 30 + name.length + packed.length;
  }
  const directory = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(items.length, 8);
  end.writeUInt16LE(items.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

test("a zip unpacks with Unix modes, folders and links that stay inside it", () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-zip-"));
  try {
    extract(
      archive([
        { name: "dist/", mode: 0o40755 },
        { name: "dist/electron", data: "binary", mode: 0o100755 },
        { name: "dist/version", data: "v44.4.5", mode: 0o100644, stored: true },
        ...(process.platform === "win32"
          ? []
          : [{ name: "dist/current", data: "electron", mode: 0o120777 }]),
      ]),
      folder,
    );
    assert.equal(
      fs.readFileSync(path.join(folder, "dist/version"), "utf8"),
      "v44.4.5",
    );
    assert.equal(
      fs.readFileSync(path.join(folder, "dist/electron"), "utf8"),
      "binary",
    );
    if (process.platform !== "win32") {
      assert.equal(
        fs.statSync(path.join(folder, "dist/electron")).mode & 0o777,
        0o755,
      );
      assert.equal(
        fs.readlinkSync(path.join(folder, "dist/current")),
        "electron",
      );
    }
    // An archive made on Windows carries no modes; files still become readable.
    extract(archive([{ name: "app.exe", data: "exe" }], false), folder);
    assert.equal(fs.readFileSync(path.join(folder, "app.exe"), "utf8"), "exe");
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test("a damaged or unsafe zip is rejected instead of unpacked", () => {
  const good = archive([{ name: "a.txt", data: "content", stored: true }]);
  const damaged = Buffer.from(good);
  damaged[30 + "a.txt".length] ^= 0xff;
  assert.throws(() => [...entries(damaged)], /damaged/);
  assert.throws(() => [...entries(good.subarray(0, 40))], /damaged/);
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-zip-"));
  try {
    assert.throws(
      () => extract(archive([{ name: "../escape", data: "x" }]), folder),
      /unsafe/,
    );
    assert.equal(fs.readdirSync(folder).length, 0);
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
});
