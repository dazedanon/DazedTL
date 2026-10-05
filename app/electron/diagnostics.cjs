const fs = require("node:fs");
const path = require("node:path");
const { fileURLToPath } = require("node:url");
const protocol = require("../../backend/dazedtl/api/protocol.json");

const LIMIT = 65536;
const OPERATIONS = new Set([
  ...Object.keys(protocol.methods),
  "startup",
  "shutdown",
  "native",
]);
const EVENTS = new Set([
  "desktop.started",
  "desktop.error",
  "renderer.gone",
  "renderer.error",
  "renderer.unresponsive",
  "renderer.reload",
  "renderer.load-failed",
  "backend.started",
  "backend.error",
  "backend.spawn-failed",
  "backend.exit",
  "backend.invalid-response",
  "workspace.ready",
]);
const identifier = (value) =>
  typeof value === "string" && /^[\w.<>-]{1,80}$/.test(value)
    ? value
    : undefined;

function safeRecord(record) {
  if (
    !record ||
    !EVENTS.has(record.event) ||
    typeof record.time !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T[\d:.+Z-]+$/.test(record.time)
  )
    return null;
  const safe = { time: record.time, event: record.event };
  if (OPERATIONS.has(record.operation)) safe.operation = record.operation;
  for (const name of [
    "requestId",
    "errno",
    "schema",
    "exitCode",
    "errorCode",
    "stderrBytes",
  ])
    if (Number.isSafeInteger(record[name])) safe[name] = record[name];
  for (const name of ["python", "code", "signal", "reason"])
    if (identifier(record[name])) safe[name] = record[name];
  if (Array.isArray(record.causes))
    safe.causes = record.causes.slice(0, 3).map((cause) => ({
      type: identifier(cause?.type) || "Error",
      frames: (Array.isArray(cause?.frames) ? cause.frames : [])
        .slice(-8)
        .map((frame) => ({
          file:
            typeof frame?.file === "string" &&
            /^(app|engine|python)\/[\w./-]{1,180}$/.test(frame.file) &&
            !frame.file.split("/").includes("..")
              ? frame.file
              : "external",
          line: Number.isSafeInteger(frame?.line) ? frame.line : 0,
          ...(Number.isSafeInteger(frame?.column)
            ? { column: frame.column }
            : {}),
          function: identifier(frame?.function) || "unknown",
        })),
    }));
  return safe;
}

class Diagnostics {
  constructor(directory, versions, root) {
    this.directory = directory;
    this.versions = versions;
    this.root = root;
    this.recent = [];
    this.available = true;
    try {
      fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    } catch {
      this.available = false;
    }
  }
  record(event, fields = {}) {
    const record = safeRecord({
      time: new Date().toISOString(),
      event,
      ...fields,
    });
    if (!record) return;
    this.recent.push(record);
    this.recent = this.recent.slice(-40);
    try {
      const file = path.join(this.directory, "desktop.jsonl");
      const line = JSON.stringify(record) + "\n";
      if (
        (fs.existsSync(file) ? fs.statSync(file).size : 0) +
          Buffer.byteLength(line) >
        LIMIT
      ) {
        fs.rmSync(file + ".2", { force: true });
        if (fs.existsSync(file + ".1")) fs.renameSync(file + ".1", file + ".2");
        if (fs.existsSync(file)) fs.renameSync(file, file + ".1");
      }
      fs.appendFileSync(file, line, { mode: 0o600 });
      this.available = true;
    } catch {
      this.available = false;
    }
  }
  failure(event, error, fields = {}) {
    const frames = [];
    const header = error?.message
      ? `${error.name}: ${error.message}`
      : error?.name;
    const stack =
      typeof error?.stack === "string" &&
      typeof header === "string" &&
      error.stack.startsWith(header)
        ? error.stack.slice(header.length)
        : "";
    for (const line of stack.split("\n")) {
      const match =
        /(?:\(|\s)(file:\/\/\/.*|[A-Za-z]:\\.*|\/.*):(\d+):\d+\)?$/.exec(line);
      if (!match) continue;
      try {
        const file = match[1].startsWith("file:")
          ? fileURLToPath(match[1])
          : match[1];
        const relative = path.relative(this.root, file);
        frames.push({
          file:
            relative &&
            !path.isAbsolute(relative) &&
            !relative.split(path.sep).includes("..")
              ? "app/" + relative.split(path.sep).join("/")
              : "external",
          line: Number(match[2]),
          function: "native",
        });
      } catch {
        /* Ignore non-file stack locations. */
      }
    }
    this.record(event, {
      ...fields,
      code: identifier(error?.code) || "internal",
      causes: [
        { type: identifier(error?.name) || "Error", frames: frames.slice(-8) },
      ],
    });
  }
  report() {
    const records = [...this.recent];
    for (const name of [
      "desktop.jsonl.2",
      "desktop.jsonl.1",
      "desktop.jsonl",
      "backend.jsonl.2",
      "backend.jsonl.1",
      "backend.jsonl",
    ]) {
      let file;
      try {
        file = fs.openSync(path.join(this.directory, name), "r");
        const size = fs.fstatSync(file).size;
        const content = Buffer.alloc(Math.min(size, LIMIT));
        fs.readSync(
          file,
          content,
          0,
          content.length,
          Math.max(0, size - LIMIT),
        );
        for (const line of content.toString("utf8").split("\n")) {
          try {
            const record = safeRecord(JSON.parse(line));
            if (record) records.push(record);
          } catch {
            /* Ignore partial or invalid records. */
          }
        }
      } catch {
        /* Diagnostics must remain available after backend startup fails. */
      } finally {
        if (file !== undefined) fs.closeSync(file);
      }
    }
    const lines = [
      ...new Set(
        records
          .sort((a, b) => a.time.localeCompare(b.time))
          .map((record) => JSON.stringify(record)),
      ),
    ].slice(-80);
    while (Buffer.byteLength(lines.join("\n")) > LIMIT) lines.shift();
    return [
      "DazedTL diagnostics",
      JSON.stringify(
        { ...this.versions, desktopLogAvailable: this.available },
        null,
        2,
      ),
      ...lines,
    ].join("\n");
  }
}

module.exports = { Diagnostics };
