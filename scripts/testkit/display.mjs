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

/** Process ids and groups of every Xwayland, by display number. */
function xwaylands() {
  const found = new Map();
  for (const pid of fs.readdirSync("/proc")) {
    if (!/^\d+$/.test(pid)) continue;
    try {
      const args = fs.readFileSync(`/proc/${pid}/cmdline`, "utf8").split("\0");
      if (!args[0]?.endsWith("Xwayland")) continue;
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
 * Starts a virtual KWin named `name` and returns its display. Its log goes to
 * `log`.
 * @param {{ name: string, log: string, width?: number, height?: number }} options
 */
export async function startDisplay({ name, log, width = 1400, height = 1000 }) {
  if (process.platform !== "linux")
    throw new Error("A private display needs Linux with KWin.");
  if (spawnSync("which", ["kwin_wayland"]).status !== 0)
    throw new Error("A private display needs kwin_wayland.");
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
  child.unref();
  const group = child.pid;
  try {
    // KWin listens on new X sockets before Xwayland runs; Xwayland starts on
    // the first client, so each candidate is tried until it is this KWin's.
    const number = await until(
      `the private display ${name}`,
      () => {
        for (const candidate of displays()) {
          if (before.has(candidate)) continue;
          spawnSync("xdpyinfo", ["-display", `:${candidate}`], {
            stdio: "ignore",
            timeout: 5000,
          });
          if (xwaylands().get(candidate) === group) return candidate;
        }
        return null;
      },
      30_000,
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
    stopGroup(group);
    throw error;
  }
}

/** Ends a process group, such as a display or an app started detached. */
export function stopGroup(group) {
  if (!group) return;
  try {
    process.kill(-group, "SIGTERM");
  } catch {
    // Already gone.
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
