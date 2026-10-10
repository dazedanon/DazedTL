const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const path = require("node:path");
const fs = require("node:fs");

/**
 * @typedef {{
 *   git: boolean,
 *   version: string,
 *   channel: "stable" | "beta",
 *   status: "idle" | "checking" | "downloading" | "ready" | "error",
 *   progress: number,
 *   latest: string,
 *   staged: string,
 *   revert: boolean,
 *   previous: string,
 *   skipped: string,
 *   checkedAt: string,
 *   error: string,
 *   outcome: { ok: boolean, version: string, from: string, message: string } | null,
 *   notes: { staged: Release[], installed: Release[] },
 * }} UpdateState
 * @typedef {{ version: string, date: string, sections: { kind: string, items: string[] }[] }} Release
 */

const day = 24 * 60 * 60 * 1000;
/** @param {unknown} error */
const messageOf = (error) =>
  error instanceof Error ? error.message : String(error);

/**
 * Checks the release mirrors, downloads updates and asks the launcher to swap
 * them in on restart. The work runs in scripts/update.mjs under Electron's
 * Node, so hashing an archive never blocks the window.
 */
class Updates {
  /**
   * @param {string} root
   * @param {string} profile
   * @param {(state: UpdateState) => void} changed
   */
  constructor(root, profile, changed) {
    this.root = root;
    this.file = path.join(profile, "updates.json");
    this.changed = changed;
    let saved = {};
    try {
      saved = JSON.parse(fs.readFileSync(this.file, "utf8"));
    } catch {
      // A missing or damaged file starts from the defaults.
    }
    /** @type {UpdateState} */
    this.state = {
      git: false,
      version: "",
      channel: saved.channel === "beta" ? "beta" : "stable",
      status: "idle",
      progress: -1,
      latest: "",
      staged: "",
      revert: false,
      previous: "",
      skipped: typeof saved.skipped === "string" ? saved.skipped : "",
      checkedAt: typeof saved.checkedAt === "string" ? saved.checkedAt : "",
      error: "",
      outcome: null,
      notes: { staged: [], installed: [] },
    };
    this.busy = false;
  }

  /** @param {Partial<UpdateState>} change */
  set(change) {
    this.state = { ...this.state, ...change };
    this.changed(this.state);
  }

  save() {
    try {
      fs.writeFileSync(
        this.file,
        JSON.stringify({
          channel: this.state.channel,
          skipped: this.state.skipped,
          checkedAt: this.state.checkedAt,
        }),
      );
    } catch {
      // The choice still applies for this session.
    }
  }

  /**
   * Runs one updater command and resolves with its last JSON line.
   * @param {string[]} args
   * @param {(event: any) => void} [onEvent]
   */
  run(args, onEvent) {
    return new Promise((resolve, reject) => {
      const child = spawn(
        process.execPath,
        [path.join(this.root, "scripts/update.mjs"), ...args],
        {
          cwd: this.root,
          env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
          stdio: ["ignore", "pipe", "ignore"],
          windowsHide: true,
        },
      );
      /** @type {any} */
      let last = null;
      createInterface({ input: child.stdout }).on("line", (line) => {
        try {
          last = JSON.parse(line);
          onEvent?.(last);
        } catch {
          // Only the updater's JSON lines matter.
        }
      });
      child.on("error", reject);
      child.on("close", () =>
        last?.error || !last
          ? reject(
              new Error(last?.error || "The updater stopped unexpectedly."),
            )
          : resolve(last),
      );
    });
  }

  async refresh() {
    const { outcome } = this.state;
    const status = await this.run(["status", outcome?.ok ? outcome.from : ""]);
    this.set({
      git: status.git,
      version: status.version,
      staged: status.staged || "",
      revert: status.revert,
      previous: status.previous || "",
      status: status.staged || status.revert ? "ready" : this.state.status,
      notes: status.notes,
    });
    if (status.result) {
      const outcome = { message: "", ...status.result };
      // Going back starts from the skipped version; any other install
      // supersedes it.
      const skipped =
        outcome.ok && outcome.from !== this.state.skipped
          ? ""
          : this.state.skipped;
      this.set({ outcome, skipped });
      this.save();
      await this.run(["seen"]);
    }
  }

  /** Reads the install and checks for updates now and then every day. */
  async start() {
    try {
      await this.refresh();
    } catch (error) {
      this.set({ status: "error", error: messageOf(error) });
      return;
    }
    if (this.state.git) return;
    const due = () =>
      Date.now() - (Date.parse(this.state.checkedAt) || 0) >= day;
    setTimeout(() => due() && void this.check(false), 10_000).unref();
    setInterval(() => due() && void this.check(false), 60 * 60 * 1000).unref();
  }

  /**
   * Finds the newest release and downloads it. Automatic checks leave a
   * version the user went back from alone; checking by hand fetches it.
   * @param {boolean} manual
   */
  async check(manual) {
    if (this.state.git || this.busy) return this.state;
    this.busy = true;
    this.set({ status: "checking", error: "", progress: -1 });
    try {
      const { latest } = await this.run(["check", this.state.channel]);
      this.set({
        checkedAt: new Date().toISOString(),
        latest: latest?.version || "",
      });
      this.save();
      const settled = !latest || latest.version === this.state.staged;
      if (settled || (!manual && latest.version === this.state.skipped)) {
        this.set({
          status: this.state.staged || this.state.revert ? "ready" : "idle",
        });
        return this.state;
      }
      this.set({ status: "downloading" });
      await this.run(["stage", JSON.stringify(latest)], (event) => {
        if (typeof event.progress === "number")
          this.set({ progress: event.progress });
      });
      if (manual && this.state.skipped === latest.version) {
        this.set({ skipped: "" });
        this.save();
      }
      this.set({ status: "ready", revert: false });
      await this.refresh();
    } catch (error) {
      this.set({ status: "error", error: messageOf(error) });
    } finally {
      this.busy = false;
    }
    return this.state;
  }

  /** @param {unknown} channel */
  async channel(channel) {
    if (channel !== "stable" && channel !== "beta")
      throw new Error("Choose the stable or beta channel.");
    this.set({ channel });
    this.save();
    return this.check(true);
  }

  /** Puts back the version before the last update, skipping the newer one. */
  async revert() {
    if (this.busy) throw new Error("Wait for the update check to finish.");
    await this.run(["revert"]);
    this.set({
      skipped: this.state.version,
      staged: "",
      revert: true,
      status: "ready",
    });
    this.save();
    await this.refresh();
    return this.state;
  }

  /** Withdraws a "Go back" request, keeping the installed version. */
  async keep() {
    await this.run(["keep"]);
    this.set({
      revert: false,
      skipped: "",
      status: this.state.staged ? "ready" : "idle",
    });
    this.save();
    await this.refresh();
    return this.state;
  }

  /**
   * Starts the launcher to swap the update in once this app has exited. It
   * opens its own console on Windows to show progress.
   */
  relaunch() {
    // Keep the switches DazedTL was started with, such as --offline. The
    // Windows command line takes only those that need no quoting.
    const args = process.argv
      .slice(2)
      .filter(
        (arg) => process.platform !== "win32" || /^[\w=:.,/-]+$/.test(arg),
      );
    const options = {
      cwd: this.root,
      detached: true,
      stdio: /** @type {const} */ ("ignore"),
    };
    const child =
      process.platform === "win32"
        ? spawn(
            process.env.ComSpec || "cmd.exe",
            [
              "/d",
              "/s",
              "/c",
              // start opens a batch file with cmd /K, which leaves the
              // console open after START exits; cmd /c closes it.
              `"start "DazedTL" /d "${this.root}" "${process.env.ComSpec || "cmd.exe"}" /d /c START.bat --after ${process.pid} ${args.join(" ")}"`,
            ],
            { ...options, windowsVerbatimArguments: true, windowsHide: true },
          )
        : spawn(
            "bash",
            [
              path.join(this.root, "START.sh"),
              "--after",
              String(process.pid),
              ...args,
            ],
            options,
          );
    child.unref();
  }
}

module.exports = { Updates };
