// A test process group: a command and whatever it starts, such as a virtual
// KWin with its session bus and Xwayland, or the stand-in provider, which end
// together. On Linux its first process is a supervisor,
// [supervise.mjs](./supervise.mjs), which ends the whole group however the
// group's life ends.
import fs from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { until } from "./cdp.mjs";

/**
 * How long, in milliseconds, a group's members get to end at SIGTERM before
 * SIGKILL ends them.
 */
export const grace = 3_000;

/**
 * The state, parent and process group of process `pid`, and the rest of its
 * /proc stat fields; throws once it has exited.
 */
const stat = (pid) => {
  const line = fs.readFileSync(`/proc/${pid}/stat`, "utf8");
  // The name before them, in parentheses, may hold any character.
  return line.slice(line.lastIndexOf(") ") + 2).split(" ");
};

/** The process group of process `pid`; throws once it has exited. */
export const groupOf = (pid) => Number(stat(pid)[2]);

/**
 * The processes of process group `group` still running; one that has exited
 * waits as a zombie until it is reaped.
 * @param {number} group
 */
export function members(group) {
  return fs
    .readdirSync("/proc")
    .filter((pid) => {
      if (!/^\d+$/.test(pid)) return false;
      try {
        const [state, , pgrp] = stat(pid);
        return state !== "Z" && Number(pgrp) === group;
      } catch {
        return false; // Exited, or another user's process.
      }
    })
    .map(Number);
}

/**
 * Spawns `command` in a process group of its own. On Linux the whole group
 * ends as soon as the command exits or `stopGroup` ends it, and with this
 * process however it ends, a SIGKILL included, unless it is to `outlive` it,
 * such as the display a scenario leaves its app running in: the group's
 * supervisor ends every member, SIGKILLing those still running after the
 * grace, and the kernel sends it SIGTERM when this process dies (`setpriv
 * --pdeathsig`), so call this from the main thread, whose end the kernel
 * signals. Elsewhere the command runs on its own.
 * @param {string} command
 * @param {string[]} args
 * @param {{ stdio?: import("node:child_process").StdioOptions, outlive?: boolean }} [options]
 */
export function spawnGroup(command, args, { stdio, outlive = false } = {}) {
  if (process.platform !== "linux")
    return spawn(command, args, { detached: true, stdio });
  if (!outlive && spawnSync("which", ["setpriv"]).status !== 0)
    throw new Error(
      "A test process group needs setpriv, from util-linux, to end with what started it.",
    );
  const supervised = [
    process.execPath,
    fileURLToPath(new URL("supervise.mjs", import.meta.url)),
    outlive ? "" : String(process.pid),
    command,
    ...args,
  ];
  const [program, ...rest] = outlive
    ? supervised
    : ["setpriv", "--pdeathsig", "TERM", ...supervised];
  return spawn(program, rest, { detached: true, stdio });
}

/**
 * Sends signal `name` to the process group `spawnGroup` started as `group`,
 * its first process's pid, and says whether any of it was there to get it.
 * On Windows, which has no process groups, it is that process alone.
 * @param {number | undefined} group
 * @param {NodeJS.Signals | 0} name
 */
function signalGroup(group, name) {
  if (!group) return false;
  try {
    process.kill(process.platform === "win32" ? group : -group, name);
    return true;
  } catch {
    return false; // Already gone.
  }
}

/** Whether any process of the group `spawnGroup` started as `group` runs. */
export const groupRuns = (group) => signalGroup(group, 0);

/**
 * Ends a process group `spawnGroup` started, such as a display or the
 * stand-in provider, and waits until it has, so a display started next can
 * take its socket name, a stand-in its port, and its folder can be removed.
 * @param {number | undefined} group
 */
export async function stopGroup(group) {
  const signal = (name) => signalGroup(group, name);
  if (!signal("SIGTERM")) return;
  const ended = (timeout) =>
    until("the process group to end", () => !signal(0), timeout);
  try {
    // Its supervisor ends it, members that outlast the grace included.
    await ended(grace + 2_000);
  } catch {
    // A group whose supervisor is gone, such as one killed on its own.
    signal("SIGKILL");
    await ended(5_000);
  }
}
