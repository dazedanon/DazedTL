const { execFile, spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const path = require("node:path");
const fs = require("node:fs");
const { setTimeout: delay } = require("node:timers/promises");
const protocol = require("../../backend/dazedtl/api/protocol.json");

class Backend {
  constructor(root, profile, onStopped, diagnostics) {
    const python =
      process.env.DAZEDTL_PYTHON ||
      path.join(
        root,
        ".venv",
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      );
    this.workspace = path.resolve(
      process.env.DAZEDTL_WORKSPACE || path.join(profile, "workspace"),
    );
    fs.mkdirSync(this.workspace, { recursive: true });
    this.pending = new Map();
    this.serial = 0;
    this.stopping = false;
    this.forced = false;
    this.diagnostics = diagnostics;
    /** @type {NodeJS.ProcessEnv} */
    const env = {
      ...process.env,
      PYTHON_DOTENV_DISABLED: "1",
      PYTHONNOUSERSITE: "1",
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      DAZEDTL_DESKTOP_WORKSPACE: path.join(this.workspace, "engine"),
    };
    delete env.PYTHONPATH;
    delete env.PYTHONHOME;
    const args = [
      "-I",
      "-X",
      "utf8",
      "-B",
      "-u",
      path.join(root, "backend/dazedtl/api/server.py"),
      "--workspace",
      this.workspace,
      "--diagnostics-directory",
      diagnostics.directory,
    ];
    if (
      process.argv.includes("--offline") ||
      process.env.DAZEDTL_DESKTOP_PROVIDERS === "0"
    )
      args.push("--offline");
    this.process = spawn(python, args, {
      cwd: this.workspace,
      env,
      windowsHide: true,
      // Its own process group, which a forced stop ends; Windows follows
      // parent links instead.
      detached: process.platform !== "win32",
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stderrBytes = 0;
    let stderrTail = "";
    let startupCode = "";
    const startupMessages = {
      runtime_version:
        "Python does not match the pinned runtime. Run the application setup again.",
      workspace_newer: "This workspace requires a newer application version.",
      workspace_locked:
        "This workspace is already open in another application instance.",
      workspace_invalid:
        "Saved workspace data is invalid. It was left unchanged.",
      workspace_upgrade:
        "The workspace upgrade could not finish. Saved workspace data was left unchanged.",
      workspace_backup:
        "The workspace upgrade could not be saved safely. Check available space and folder permissions.",
    };
    this.process.stderr.on("data", (chunk) => {
      stderrBytes += chunk.length;
      // Raw stderr can contain provider payloads; only retain a bounded parser
      // buffer and recognize our fixed startup error codes, never log the text.
      stderrTail = (stderrTail + chunk).slice(-512);
      const code = /(?:^|\n)DAZEDTL_ERROR ([a-z_]+)\r?\n/.exec(stderrTail)?.[1];
      if (code && Object.hasOwn(startupMessages, code)) startupCode = code;
    });
    this.process.stdin.on("error", () =>
      this.fail("The translation service disconnected."),
    );
    createInterface({ input: this.process.stdout }).on("line", (line) => {
      let response;
      try {
        response = JSON.parse(line);
      } catch {
        return;
      }
      if (!response || typeof response !== "object") return;
      const task = this.pending.get(response.id);
      if (!task) return;
      this.pending.delete(response.id);
      if (response.version !== protocol.version)
        return task.reject(
          Object.assign(
            new Error(
              "The application and backend versions do not match. Restart after updating.",
            ),
            { code: "protocol" },
          ),
        );
      if (
        (response.error && typeof response.error.message !== "string") ||
        (!response.error && !("result" in response))
      ) {
        diagnostics.record("backend.invalid-response", {
          requestId: response.id,
        });
        return task.reject(
          Object.assign(
            new Error("The backend returned an invalid response."),
            { code: "protocol" },
          ),
        );
      }
      if (response.error)
        task.reject(
          Object.assign(new Error(response.error.message), {
            code: response.error.code,
            details: response.error.details,
          }),
        );
      else task.resolve(response.result);
    });
    this.process.on("error", (error) => {
      diagnostics.failure("backend.spawn-failed", error, {
        operation: "startup",
      });
      this.fail(
        "Python could not start. Run node scripts/setup.mjs to prepare the runtime.",
      );
    });
    this.process.on("exit", (exitCode, signal) => {
      // Requests are answered in turn, so the oldest unanswered one is
      // usually what the backend was busy with.
      const waiting = this.pending.values().next().value;
      if (!this.stopping || exitCode !== 0 || stderrBytes || startupCode)
        diagnostics.record("backend.exit", {
          exitCode,
          signal,
          stderrBytes,
          code: startupCode || undefined,
          reason: this.forced ? "forced-stop" : undefined,
          operation: waiting?.method,
          seconds: waiting
            ? Math.round((Date.now() - waiting.started) / 1000)
            : undefined,
        });
      const message =
        startupMessages[startupCode] ||
        "The translation service stopped. Restart to recover saved work.";
      this.fail(message);
      if (!this.stopping) onStopped(message);
    });
  }
  fail(message) {
    for (const task of this.pending.values())
      task.reject(Object.assign(new Error(message), { code: "unavailable" }));
    this.pending.clear();
  }
  request(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (
        !this.process?.pid ||
        this.process.exitCode !== null ||
        this.process.signalCode !== null
      )
        return reject(
          Object.assign(new Error("The translation service is unavailable."), {
            code: "unavailable",
          }),
        );
      const id = ++this.serial;
      this.pending.set(id, { resolve, reject, method, started: Date.now() });
      this.process.stdin.write(
        JSON.stringify({ id, version: protocol.version, method, params }) +
          "\n",
      );
    });
  }
  async close() {
    this.stopping = true;
    if (
      !this.process.pid ||
      this.process.exitCode !== null ||
      this.process.signalCode !== null
    )
      return;
    const exited = new Promise((resolve) =>
      this.process.once("exit", () => resolve(true)),
    );
    const within = (milliseconds) =>
      Promise.race([exited, delay(milliseconds, false)]);
    this.process.stdin.end();
    if (await within(12000)) return;
    // A backend still busy at the limit is stopped together with everything
    // it started, such as the Git command it waits on and workers; closing
    // then waits briefly for its exit, which records the stop and the request
    // it was busy with before the app exits.
    this.forced = true;
    await stopTree(this.process.pid);
    await within(2000);
  }
}

/**
 * Ends a process and every process it started. Workers lead sessions of their
 * own, so their groups are found through their parents while the tree is
 * still whole.
 */
async function stopTree(pid) {
  if (process.platform === "win32") {
    await new Promise((resolve) =>
      execFile(
        path.join(
          process.env.SystemRoot || "C:\\Windows",
          "System32",
          "taskkill.exe",
        ),
        ["/PID", String(pid), "/T", "/F"],
        { windowsHide: true, timeout: 10000 },
        () => resolve(undefined),
      ),
    );
    return;
  }
  const groups = await processGroups(pid);
  const signal = (name) => {
    for (const group of groups)
      try {
        process.kill(-group, name);
      } catch {
        groups.delete(group);
      }
  };
  // Git removes its lock files when asked to stop; whatever still runs
  // shortly after is killed.
  signal("SIGTERM");
  for (let waited = 0; groups.size && waited < 2000; waited += 100) {
    await delay(100);
    signal(0);
  }
  signal("SIGKILL");
}

/** The process groups of a process and of everything it started. */
async function processGroups(root) {
  const groups = new Set([root]);
  const listing = await new Promise((resolve) =>
    execFile(
      "ps",
      ["-A", "-o", "pid=,ppid=,pgid="],
      { timeout: 5000 },
      // Without a listing, the process's own group still ends.
      (error, stdout) => resolve(error ? "" : stdout),
    ),
  );
  const children = new Map();
  for (const line of listing.split("\n")) {
    const [pid, parent, group] = line.trim().split(/\s+/).map(Number);
    if (!pid) continue;
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push([pid, group]);
  }
  const pending = [root];
  for (const parent of pending)
    for (const [pid, group] of children.get(parent) || []) {
      groups.add(group);
      pending.push(pid);
    }
  return groups;
}
module.exports = { Backend, stopTree };
