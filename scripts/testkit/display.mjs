// A private virtual display on Linux, so a test app's windows stay off the
// developer's desktop: a virtual KWin with Xwayland in its own session bus.
// Several sessions may start one at a time, so the display is the one whose
// Xwayland belongs to this KWin's process group, never just a new socket.
import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { until } from "./cdp.mjs";

const sockets = "/tmp/.X11-unix";
const displays = () =>
  new Set(
    fs.existsSync(sockets)
      ? fs
          .readdirSync(sockets)
          .filter((name) => /^X\d+$/.test(name))
          .map((name) => name.slice(1))
      : [],
  );

/** Process groups of every X server run by `program`, by display number. */
function servers(program) {
  const found = new Map();
  for (const pid of fs.readdirSync("/proc")) {
    if (!/^\d+$/.test(pid)) continue;
    try {
      const args = fs.readFileSync(`/proc/${pid}/cmdline`, "utf8").split("\0");
      if (path.basename(args[0] || "") !== program) continue;
      const group = Number(
        fs
          .readFileSync(`/proc/${pid}/stat`, "utf8")
          .split(") ")[1]
          .split(" ")[2],
      );
      const display = args.find((arg) => /^:\d+$/.test(arg));
      if (display) found.set(display.slice(1), group);
    } catch {
      // Exited, or another user's process.
    }
  }
  return found;
}

/**
 * The display `DISPLAY` names when an Xvfb serves it, as under xvfb-run on
 * CI; never a desktop's own display, which a test window would draw on.
 */
export function virtualDisplay() {
  const number = /^:(\d+)(\.\d+)?$/.exec(process.env.DISPLAY || "")?.[1];
  return number && servers("Xvfb").has(number)
    ? { env: { DISPLAY: `:${number}` } }
    : null;
}

/**
 * Starts a virtual KWin named `name` and returns its display. Its log goes to
 * `log`.
 * @param {{ name: string, log: string, width?: number, height?: number }} options
 */
export async function startDisplay({ name, log, width = 1400, height = 1000 }) {
  if (process.platform !== "linux")
    throw new Error("A private display needs Linux with KWin.");
  if (spawnSync("which", ["kwin_wayland"]).status !== 0)
    throw new Error("A private display needs kwin_wayland.");
  // A sandbox such as Claude Code's bwrap leaves /tmp read-only, where the
  // bus and X sockets go, and hides /dev/dri, without which KWin crashes.
  const sandboxed = (() => {
    if (!fs.existsSync("/dev/dri")) return "/dev/dri is missing";
    try {
      fs.accessSync("/tmp", fs.constants.W_OK);
      return null;
    } catch {
      return "/tmp is read-only";
    }
  })();
  if (sandboxed)
    throw new Error(
      `A private display cannot start here: ${sandboxed}. Run scenarios outside the sandbox.`,
    );
  const before = displays();
  const output = fs.openSync(log, "a");
  const child = spawn(
    "dbus-run-session",
    [
      "--",
      "kwin_wayland",
      "--virtual",
      "--xwayland",
      // A lock screen would stop the window from drawing frames.
      "--no-lockscreen",
      "--socket",
      name,
      "--width",
      String(width),
      "--height",
      String(height),
    ],
    { detached: true, stdio: ["ignore", output, output] },
  );
  fs.closeSync(output);
  let exited = false;
  child.on("exit", () => (exited = true));
  child.unref();
  const group = child.pid;
  try {
    // KWin listens on new X sockets before Xwayland runs; Xwayland starts on
    // the first client, so each candidate is tried until it is this KWin's.
    const number = await until(
      `the private display ${name}`,
      () => {
        if (exited) return "exited";
        for (const candidate of displays()) {
          if (before.has(candidate)) continue;
          spawnSync("xdpyinfo", ["-display", `:${candidate}`], {
            stdio: "ignore",
            timeout: 5000,
          });
          if (servers("Xwayland").get(candidate) === group) return candidate;
        }
        return null;
      },
      30_000,
    );
    if (number === "exited")
      throw new Error(
        `KWin for the private display ${name} exited: ${fs.readFileSync(log, "utf8").trim().split("\n").slice(-3).join(" ")}`,
      );
    return {
      display: `:${number}`,
      wayland: name,
      group,
      env: {
        DISPLAY: `:${number}`,
        // Unset, Chromium would fall back to the desktop's wayland-0.
        WAYLAND_DISPLAY: name,
        GDK_BACKEND: "x11",
      },
    };
  } catch (error) {
    await stopGroup(group);
    throw error;
  }
}

/**
 * Ends a process group, such as a display or an app started detached, and
 * waits until it has, so a display started next can take its socket name.
 */
export async function stopGroup(group, timeout = 10_000) {
  if (!group) return;
  const signal = (name) => {
    try {
      process.kill(-group, name);
      return true;
    } catch {
      return false; // Already gone.
    }
  };
  if (!signal("SIGTERM")) return;
  try {
    await until("the process group to end", () => !signal(0), timeout);
  } catch {
    signal("SIGKILL");
  }
}

/** Saves the whole private display as a PNG, windows other than the app included. */
export function screenshotDisplay(display, file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const result = spawnSync("magick", ["x:root", file], {
    env: { ...process.env, DISPLAY: display },
    stdio: "ignore",
  });
  if (result.status !== 0)
    throw new Error("magick could not capture the display.");
}
