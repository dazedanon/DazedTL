const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const path = require("node:path");
const fs = require("node:fs");
const protocol = require("../../backend/dazedtl/api/protocol.json");
const { engineSource } = require("./engine-source.cjs");

class Backend {
  constructor(root, profile, onStopped, diagnostics) {
    const legacy = engineSource(root);
    const python =
      process.env.DAZEDTL_PYTHON ||
      path.join(
        root,
        ".venv",
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      );
    this.workspace = path.resolve(
      process.env.DAZEDTL_NEXT_WORKSPACE || path.join(profile, "workspace"),
    );
    fs.mkdirSync(this.workspace, { recursive: true });
    this.pending = new Map();
    this.serial = 0;
    this.stopping = false;
    this.diagnostics = diagnostics;
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
      "-B",
      "-u",
      path.join(root, "backend/dazedtl/api/server.py"),
      "--workspace",
      this.workspace,
      "--legacy-root",
      legacy,
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
      response.error
        ? task.reject(
            Object.assign(new Error(response.error.message), {
              code: response.error.code,
              details: response.error.details,
            }),
          )
        : task.resolve(response.result);
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
      diagnostics.record("backend.exit", {
        exitCode,
        signal,
        stderrBytes,
        code: startupCode || undefined,
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
      this.pending.set(id, { resolve, reject });
      this.process.stdin.write(
        JSON.stringify({ id, version: protocol.version, method, params }) +
          "\n",
      );
    });
  }
  close() {
    this.stopping = true;
    if (this.process.exitCode !== null || this.process.signalCode !== null)
      return Promise.resolve();
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        this.process.kill();
        resolve();
      }, 12000);
      this.process.once("exit", () => {
        clearTimeout(timeout);
        resolve();
      });
      this.process.stdin.end();
    });
  }
}
module.exports = { Backend };
