const { execFile } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const { SourceMap } = require("node:module");
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
  "desktop.error",
  "renderer.gone",
  "renderer.error",
  "renderer.unresponsive",
  "renderer.reload",
  "renderer.load-failed",
  "backend.error",
  "backend.spawn-failed",
  "backend.exit",
  "backend.invalid-response",
  "backend.stalled",
  "backend.resumed",
  "operation.stalled",
  "operation.resumed",
  "worker.error",
]);
const LOGS = ["desktop-failures.jsonl", "backend-failures.jsonl"];
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
    "seconds",
  ])
    if (Number.isSafeInteger(record[name])) safe[name] = record[name];
  for (const name of ["python", "code", "signal", "reason", "action"])
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

/** A downloaded install names its signed release and whether files differ. */
async function release(root) {
  try {
    const manifest = JSON.parse(
      await fs.promises.readFile(
        path.join(root, "release/manifest.json"),
        "utf8",
      ),
    );
    let modified = false;
    for (const [name, hash] of Object.entries(manifest.files)) {
      const data = await fs.promises
        .readFile(path.join(root, name))
        .catch(() => null);
      if (
        !data ||
        crypto.createHash("sha256").update(data).digest("hex") !== hash
      ) {
        modified = true;
        break;
      }
    }
    return { revision: `release ${manifest.version}`, modified };
  } catch {
    return { revision: "unknown" };
  }
}

/** Code locations are only meaningful against the checkout's exact revision. */
function revision(root) {
  if (!fs.existsSync(path.join(root, ".git"))) return release(root);
  return new Promise((resolve) =>
    execFile(
      "git",
      ["status", "--porcelain=v2", "--branch", "--untracked-files=no"],
      {
        cwd: root,
        timeout: 3000,
        windowsHide: true,
        // Reading status must not lock the index against the user's own Git use.
        env: { ...process.env, GIT_OPTIONAL_LOCKS: "0" },
      },
      (error, stdout) => {
        const commit = /^# branch\.oid ([0-9a-f]{40})$/m.exec(stdout)?.[1];
        resolve(
          error || !commit
            ? { revision: "unknown" }
            : {
                revision: commit.slice(0, 12),
                modified: stdout
                  .split("\n")
                  .some((line) => line && !line.startsWith("#")),
              },
        );
      },
    ),
  );
}

// A Discord message holds 2,000 characters; the errors leave room for the
// reporter's own words.
const ERRORS_SHOWN = 8;
const ERRORS_LENGTH = 800;

/** One failure as "worker.error fit_text KeyError backend/worker.py:4". */
function summary(record) {
  const cause = record.causes?.[0];
  const frame = cause?.frames?.findLast((frame) => frame.file !== "external");
  return [
    record.event,
    record.operation ?? record.action,
    record.code && record.code !== "internal" ? record.code : undefined,
    record.reason,
    record.exitCode !== undefined ? `exit ${record.exitCode}` : undefined,
    record.signal,
    record.seconds ? `${record.seconds}s` : undefined,
    cause && cause.type !== "Error" ? cause.type : undefined,
    // "app/" only says the file is DazedTL's own.
    frame ? `${frame.file.replace(/^app\//, "")}:${frame.line}` : undefined,
  ]
    .filter(Boolean)
    .join(" ");
}

/** Summary lines, a repeated failure counted on its latest line. */
function summaryGroups(records) {
  const groups = [];
  for (const record of records) {
    const text = summary(record);
    const last = groups.at(-1);
    if (last?.text === text)
      Object.assign(last, { time: record.time, count: last.count + 1 });
    else groups.push({ text, time: record.time, count: 1 });
  }
  return groups.map(({ text, time, count }) => ({
    line: `${time.slice(5, 10)} ${time.slice(11, 16)}Z ${text}${count > 1 ? ` (${count} times)` : ""}`,
    count,
  }));
}

/** "Windows 11 (build 22631, x64)" or the Linux distribution's own name. */
function system() {
  const architecture = process.arch;
  if (process.platform === "win32") {
    const build = Number(os.release().split(".")[2]) || 0;
    return `Windows ${build >= 22000 ? 11 : 10} (build ${build}, ${architecture})`;
  }
  if (process.platform === "linux") {
    let name = "Linux";
    try {
      name =
        /^PRETTY_NAME="?([\w .()/+-]{1,60})"?$/m.exec(
          fs.readFileSync("/etc/os-release", "utf8"),
        )?.[1] || name;
    } catch {
      /* Without os-release the kernel family is still useful. */
    }
    return `${name} (${architecture})`;
  }
  return `${process.platform} (${architecture})`;
}

class Diagnostics {
  constructor(directory, versions, root) {
    this.directory = directory;
    this.versions = versions;
    this.root = root;
    this.recent = [];
    this.maps = new Map();
    this.available = true;
    try {
      fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
      // Logs from before failure-only recording would bury new failures.
      for (const name of ["desktop", "backend"])
        for (const suffix of ["", ".1", ".2"])
          fs.rmSync(path.join(directory, `${name}.jsonl${suffix}`), {
            force: true,
          });
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
      const file = path.join(this.directory, LOGS[0]);
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
  location(file) {
    const relative = path.relative(this.root, file);
    return relative &&
      !path.isAbsolute(relative) &&
      !relative.split(path.sep).includes("..")
      ? "app/" + relative.split(path.sep).join("/")
      : "external";
  }
  /** Bundle coordinates resolve through the build's hidden source maps. */
  renderer(reason, causes) {
    this.record("renderer.error", {
      reason,
      causes: Array.isArray(causes)
        ? causes.map((cause) => ({
            ...cause,
            frames: Array.isArray(cause?.frames)
              ? cause.frames.map((frame) => this.source(frame))
              : [],
          }))
        : undefined,
    });
  }
  source(frame) {
    const bundle = /^app\/renderer\/(assets\/[\w.-]+\.js)$/.exec(
      frame?.file,
    )?.[1];
    if (
      !bundle ||
      !Number.isSafeInteger(frame.line) ||
      !Number.isSafeInteger(frame.column)
    )
      return frame;
    const file = path.join(this.root, "app/dist", bundle);
    if (!this.maps.has(bundle))
      try {
        this.maps.set(
          bundle,
          new SourceMap(JSON.parse(fs.readFileSync(file + ".map", "utf8"))),
        );
      } catch {
        this.maps.set(bundle, null); // Development and older builds have no map.
      }
    const origin = this.maps.get(bundle)?.findOrigin(frame.line, frame.column);
    return origin?.fileName
      ? {
          file: this.location(
            path.resolve(path.dirname(file), origin.fileName),
          ),
          line: origin.lineNumber,
          column: origin.columnNumber,
          function: frame.function,
        }
      : frame;
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
        frames.push({
          file: this.location(
            match[1].startsWith("file:") ? fileURLToPath(match[1]) : match[1],
          ),
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
  /** Safe records from this run and the logs, oldest first, without repeats. */
  async records() {
    const records = [...this.recent];
    for (const name of LOGS.flatMap((log) => [log + ".2", log + ".1", log])) {
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
    const unique = new Map();
    for (const record of records.sort((a, b) => a.time.localeCompare(b.time)))
      unique.set(JSON.stringify(record), record);
    return [...unique.values()];
  }
  async report() {
    const lines = (await this.records())
      .map((record) => JSON.stringify(record))
      .slice(-80);
    while (Buffer.byteLength(lines.join("\n")) > LIMIT) lines.shift();
    return [
      "DazedTL diagnostics",
      JSON.stringify(
        {
          ...this.versions,
          ...(await revision(this.root)),
          desktopLogAvailable: this.available,
        },
        null,
        2,
      ),
      ...lines,
    ].join("\n");
  }
  /**
   * The facts both shared reports open with, filled in by DazedTL: its
   * version, the system, and the open game with its engine and mode, which
   * the renderer passes in. A fact it can't name stays blank.
   */
  async facts(context = {}) {
    const field = (value) =>
      typeof value === "string" && value.trim()
        ? value
            .replace(/\s+/g, " ")
            .trim()
            .slice(0, 120)
            .replace(/[\\*_~`|]/g, "\\$&")
        : "";
    const { revision: name, modified } = await revision(this.root);
    const changed = modified ? ", modified" : "";
    const version = name.startsWith("release ")
      ? name.slice(8) + (modified ? ", files changed" : "")
      : name === "unknown"
        ? this.versions.app
        : `${this.versions.app} (dev ${name}${changed})`;
    const game = field(context.game);
    const engine = field(context.engine);
    return [
      `**DazedTL version:** ${version}`,
      `**System:** ${system()}`,
      `**Game:** ${game}${game && engine ? ` (${engine})` : engine}`,
      `**Mode:** ${field(context.mode)}`,
    ];
  }
  /**
   * A bug report to paste into Discord: the facts filled in, blanks for the
   * reporter, and the latest failures in one line each, so the whole paste
   * stays one editable message.
   */
  async problemReport(context = {}) {
    const groups = summaryGroups(await this.records());
    const shown = [];
    while (shown.length < ERRORS_SHOWN) {
      const group = groups.at(-1);
      if (!group || [group.line, ...shown].join("\n").length > ERRORS_LENGTH)
        break;
      shown.unshift(group.line);
      groups.pop();
    }
    const hidden = groups.reduce((total, group) => total + group.count, 0);
    return [
      ...(await this.facts(context)),
      "",
      "**What happened:**",
      "",
      "**What you expected:**",
      "",
      "**Steps to make it happen again:**",
      "1.",
      "",
      "**Recent errors:**",
      "```",
      ...(shown.length ? shown : ["None recorded"]),
      ...(hidden ? [`and ${hidden} earlier`] : []),
      "```",
    ].join("\n");
  }
  /**
   * The task Share a fix copies: the user's assistant writes up a fix it made
   * in the game for DazedTL's developers, opening with the same facts. The
   * task's text is the engine's assistant prompt in share_fix.md.
   */
  async fixTask(context = {}) {
    const task = fs.readFileSync(
      path.join(this.root, "backend/dazedtl/engine/data/skills/share_fix.md"),
      "utf8",
    );
    const facts = (await this.facts(context)).join("\n");
    return task.replace("{facts}", () => facts);
  }
  /**
   * The tool feedback the user shares, as Copy for Discord and Save file
   * give it: a title, the same facts, then what the assistant saved, which
   * tool_feedback keeps short enough for one Discord message with them.
   */
  async toolFeedback(context = {}, feedback = "") {
    return [
      "**DazedTL tool feedback**",
      ...(await this.facts(context)),
      "",
      String(feedback).trim(),
    ].join("\n");
  }
}

module.exports = { Diagnostics };
