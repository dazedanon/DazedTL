// Reads the zip archives Electron ships in. Node has no zip reader, and
// Electron's own extractor is a native module that needs the Visual C++
// runtime, which a fresh Windows does not have.
import zlib from "node:zlib";
import { unpack } from "./tar.mjs";

const signatures = {
  directory: 0x02014b50,
  end: 0x06054b50,
  local: 0x04034b50,
};

/**
 * Lists the files, folders and links of a zip archive from its central
 * directory, which holds the sizes that a streamed local header may omit.
 * @param {Buffer} archive
 * @returns {Generator<{ path: string, type: "file" | "directory" | "symlink", mode: number, link: string, data: Buffer }>}
 */
export function* entries(archive) {
  // The end record is the last 22 bytes unless a comment of up to 64 KiB follows.
  let end = -1;
  for (
    let i = archive.length - 22;
    i >= Math.max(0, archive.length - 65557);
    i--
  )
    if (archive.readUInt32LE(i) === signatures.end) {
      end = i;
      break;
    }
  if (end < 0) throw new Error("The archive is damaged.");
  const count = archive.readUInt16LE(end + 10);
  let offset = archive.readUInt32LE(end + 16);
  if (count === 0xffff || offset === 0xffffffff)
    throw new Error("The archive is larger than zip supports without zip64.");
  for (let i = 0; i < count; i++) {
    if (archive.readUInt32LE(offset) !== signatures.directory)
      throw new Error("The archive is damaged.");
    const system = archive.readUInt16LE(offset + 4) >> 8;
    const flags = archive.readUInt16LE(offset + 8);
    const method = archive.readUInt16LE(offset + 10);
    const crc = archive.readUInt32LE(offset + 16);
    const compressed = archive.readUInt32LE(offset + 20);
    const size = archive.readUInt32LE(offset + 24);
    const nameLength = archive.readUInt16LE(offset + 28);
    const name = archive
      .subarray(offset + 46, offset + 46 + nameLength)
      .toString("utf8");
    const attributes = archive.readUInt32LE(offset + 38);
    const local = archive.readUInt32LE(offset + 42);
    offset +=
      46 +
      nameLength +
      archive.readUInt16LE(offset + 30) +
      archive.readUInt16LE(offset + 32);
    if (flags & 1) throw new Error("The archive is encrypted.");
    if (archive.readUInt32LE(local) !== signatures.local)
      throw new Error("The archive is damaged.");
    const start =
      local +
      30 +
      archive.readUInt16LE(local + 26) +
      archive.readUInt16LE(local + 28);
    const raw = archive.subarray(start, start + compressed);
    if (raw.length !== compressed) throw new Error("The archive is truncated.");
    let data;
    if (method === 0) data = raw;
    else if (method === 8) data = zlib.inflateRawSync(raw);
    else throw new Error(`The archive holds an unsupported entry: ${name}`);
    if (data.length !== size || zlib.crc32(data) !== crc)
      throw new Error("The archive is damaged.");
    // Only archives made on Unix carry file modes, in the high attribute bits.
    const mode = system === 3 ? attributes >>> 16 : 0;
    const type = name.endsWith("/")
      ? "directory"
      : (mode & 0o170000) === 0o120000
        ? "symlink"
        : "file";
    yield {
      path: name,
      type,
      mode,
      link: type === "symlink" ? data.toString("utf8") : "",
      data,
    };
  }
}

/**
 * Unpacks a zip archive into a new folder, keeping file modes and links that
 * stay inside it.
 * @param {Buffer} archive
 * @param {string} destination
 * @param {{ strip?: number }} [options]
 */
export function extract(archive, destination, options) {
  unpack(entries(archive), destination, options);
}
