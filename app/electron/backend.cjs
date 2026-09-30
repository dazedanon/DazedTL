const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const path = require("node:path");
const fs = require("node:fs");
const protocol = require("../../backend/dazedtl/api/protocol.json");

class Backend {
  constructor(root, profile, onStopped) {
    const legacy =
      process.env.DAZEDTL_LEGACY_ROOT || path.resolve(root, "../DazedMTLTool");
    const python =
      process.env.DAZEDTL_PYTHON ||
      path.join(
        legacy,
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
    let errorText = "";
    this.process.stderr.on("data", (chunk) => {
      errorText = (errorText + chunk).slice(-2000);
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
      response.error
        ? task.reject(
            Object.assign(new Error(response.error.message), {
              code: response.error.code,
            }),
          )
        : task.resolve(response.result);
    });
    this.process.on("error", () =>
      this.fail("Python could not start. Check the development runtime paths."),
    );
    this.process.on("exit", () => {
      this.fail(
        errorText
          ? "The translation service stopped. Check the backend runtime configuration."
          : "The translation service stopped.",
      );
      if (!this.stopping)
        onStopped(
          "The translation service stopped. Restart to recover saved work.",
        );
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
