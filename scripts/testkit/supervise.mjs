// The supervisor `spawnGroup` (group.mjs) makes the first process of each
// test process group on Linux:
//   node supervise.mjs <starter PID, or "" for a group that outlives it> <command> [<arg>...]
// It runs the command, and whatever ends the group's life ends the whole
// group the same way: the command exiting, as dbus-run-session does at
// SIGTERM or after a bus error and leaves its KWin running, or SIGTERM to
// this process, from `stopGroup` or from the kernel as a bound group's
// starter dies, or another signal asking it to end. It is the group's last
// process too, so the group runs exactly as long as it does.
import { spawn } from "node:child_process";
import os from "node:os";
import { setTimeout as delay } from "node:timers/promises";
import { grace, members } from "./group.mjs";

const [starter, command, ...args] = process.argv.slice(2);
/** A shell's exit status for a process ended by `signal`. */
const signalled = (signal) => 128 + os.constants.signals[signal];

let ending = false;
/**
 * Sends every member SIGTERM and exits with `status` once the others have
 * gone; those still running after the grace, such as a hung KWin, get
 * SIGKILL, this process with them. It runs once: SIGTERM to the group comes
 * back to this process, and the kernel signals it again for each of a dying
 * starter's threads that ends first.
 */
async function end(status) {
  if (ending) return;
  ending = true;
  process.kill(-process.pid, "SIGTERM");
  const deadline = Date.now() + grace;
  while (members(process.pid).some((pid) => pid !== process.pid)) {
    if (Date.now() > deadline) process.kill(-process.pid, "SIGKILL");
    await delay(100);
  }
  process.exit(status);
}

for (const signal of ["SIGTERM", "SIGINT", "SIGHUP"])
  process.on(signal, () => void end(signalled(signal)));
// A bound group's starter that died before the kernel was asked to signal it
// never will.
if (starter && process.ppid !== Number(starter)) process.exit(1);
spawn(command, args, { stdio: "inherit" })
  .on("error", () => void end(127))
  .on("exit", (code, signal) => void end(code ?? signalled(signal)));
