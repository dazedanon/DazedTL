// Reads the gzip tar archives that setup and updates download. Node has no tar
// reader, and the system tar differs between Windows, Linux and macOS.
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const block = 512;

function text(header, start, length) {
  const field = header.subarray(start, start + length);
  const end = field.indexOf(0);
  return field.subarray(0, end < 0 ? length : end).toString("utf8");
}

function octal(header, start, length) {
  const value = text(header, start, length).trim();
  if (!/^[0-7]*$/.test(value)) throw new Error("The archive is damaged.");
  return value ? parseInt(value, 8) : 0;
}

// Pax records are "<length> <key>=<value>\n", where length counts the record.
function pax(data) {
  const records = {};
  let offset = 0;
  while (offset < data.length) {
    const space = data.indexOf(32, offset);
    const length = Number(data.subarray(offset, space).toString("utf8"));
    if (space < 0 || !Number.isSafeInteger(length) || length <= 0)
      throw new Error("The archive is damaged.");
    const record = data.subarray(space + 1, offset + length - 1).toString();
    const equals = record.indexOf("=");
    records[record.slice(0, equals)] = record.slice(equals + 1);
    offset += length;
  }
  return records;
}

/**
 * Lists the files, folders and links of a gzip tar archive in order.
 * @param {Buffer} archive
 * @returns {Generator<{ path: string, type: "file" | "directory" | "symlink", mode: number, link: string, data: Buffer }>}
 */
export function* entries(archive) {
  const tar = zlib.gunzipSync(archive);
  let offset = 0;
  /** @type {Record<string, string>} */
  let extended = {};
  let longName = "";
  let longLink = "";
  while (offset + block <= tar.length) {
    const header = tar.subarray(offset, offset + block);
    if (header.every((byte) => byte === 0)) return;
    const size = Number(extended.size ?? octal(header, 124, 12));
    const type = String.fromCharCode(header[156] || 48);
    const start = offset + block;
    const data = tar.subarray(start, start + size);
    if (data.length !== size) throw new Error("The archive is truncated.");
    offset = start + Math.ceil(size / block) * block;
    if (type === "x") {
      extended = pax(data);
      continue;
    }
    if (type === "g") continue;
    if (type === "L" || type === "K") {
      const value = data.toString("utf8").replace(/\0+$/, "");
      if (type === "L") longName = value;
      else longLink = value;
      continue;
    }
    const prefix = text(header, 345, 155);
    const name =
      extended.path ||
      longName ||
      (prefix ? `${prefix}/` : "") + text(header, 0, 100);
    const link = extended.linkpath || longLink || text(header, 157, 100);
    extended = {};
    longName = "";
    longLink = "";
    const mode = octal(header, 100, 8);
    if (type === "0" || type === "7")
      yield { path: name, type: "file", mode, link: "", data };
    else if (type === "5")
      yield { path: name, type: "directory", mode, link: "", data };
    else if (type === "2")
      yield { path: name, type: "symlink", mode, link, data };
    else throw new Error(`The archive holds an unsupported entry: ${name}`);
  }
  throw new Error("The archive is truncated.");
}

/**
 * Splits an archive path into safe relative parts, dropping `strip` leading
 * folders. Returns null for the stripped folders themselves.
 * @param {string} name
 * @param {number} strip
 */
export function relative(name, strip) {
  const parts = name.split("/").filter((part) => part && part !== ".");
  if (parts.some((part) => part === ".." || part.includes("\\")))
    throw new Error(`The archive holds an unsafe path: ${name}`);
  if (name.startsWith("/") || /^[a-z]:/i.test(name))
    throw new Error(`The archive holds an unsafe path: ${name}`);
  return parts.length > strip ? parts.slice(strip).join("/") : null;
}

/**
 * Unpacks a gzip tar archive into a new folder, keeping file modes and links
 * that stay inside it.
 * @param {Buffer} archive
 * @param {string} destination
 * @param {{ strip?: number }} [options]
 */
export function extract(archive, destination, { strip = 0 } = {}) {
  fs.mkdirSync(destination, { recursive: true });
  const base = path.resolve(destination);
  const links = [];
  for (const entry of entries(archive)) {
    const name = relative(entry.path, strip);
    if (!name) continue;
    const target = path.join(base, ...name.split("/"));
    if (entry.type === "directory") fs.mkdirSync(target, { recursive: true });
    else if (entry.type === "symlink") links.push({ entry, target });
    else {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, entry.data, {
        mode: entry.mode & 0o777 || 0o644,
      });
    }
  }
  // Links come last, so no file is ever written through one.
  for (const { entry, target } of links) {
    const resolved = path.resolve(path.dirname(target), entry.link);
    if (
      process.platform === "win32" ||
      path.isAbsolute(entry.link) ||
      !resolved.startsWith(base + path.sep)
    )
      throw new Error(`The archive holds an unsupported link: ${entry.path}`);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.symlinkSync(entry.link, target);
  }
}
