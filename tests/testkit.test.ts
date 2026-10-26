import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import test from "node:test";
import { appEnvironment, stopApp } from "../scripts/testkit/app.mjs";
import { displayName } from "../scripts/testkit/display.mjs";
import { withRetry } from "../scripts/testkit/retry.mjs";

test("a check that fails once and then passes is a flake, and two failures still fail", async () => {
  const runs: number[] = [];
  const attempts =
    (...results: boolean[]) =>
    async (number: 1 | 2) => {
      runs.push(number);
      return results[number - 1];
    };
  assert.deepEqual(await withRetry(attempts(true, false)), {
    passed: true,
    flaky: false,
  });
  assert.deepEqual(runs, [1]);
  let cleared = 0;
  assert.deepEqual(await withRetry(attempts(false, true), () => cleared++), {
    passed: true,
    flaky: true,
  });
  assert.deepEqual(await withRetry(attempts(false, false)), {
    passed: false,
    flaky: false,
  });
  assert.equal(cleared, 1);
});

test("two runs whose work folders share a last part get different displays", () => {
  const names = ["/tmp/a/w", "/tmp/b/w"].map(displayName);
  assert.notEqual(names[0], names[1]);
  assert.match(names[0], /^dazedtl-w-[0-9a-f]{6}$/);
});

test(
  "stopApp returns only once the app's child processes have exited too",
  {
    skip: process.platform === "win32",
  },
  async () => {
    // The leader ends at SIGTERM and leaves a child behind, as Electron's main
    // process does with Chromium's, none of which carry the scenario's marker.
    const leader = spawn("sh", ["-c", "sleep 0.1 & trap 'exit 0' TERM; wait"], {
      detached: true,
      stdio: "ignore",
    });
    const group = leader.pid as number;
    await stopApp("no-such-tag", group, 5_000);
    assert.throws(() => process.kill(-group, 0), { code: "ESRCH" });
  },
);

test("a scenario app under a test display gets none of the desktop session", () => {
  const desktop = {
    DBUS_SESSION_BUS_ADDRESS: "unix:path=/run/user/1000/bus",
    XDG_RUNTIME_DIR: "/run/user/1000",
    WAYLAND_DISPLAY: "wayland-1",
    PULSE_SERVER: "unix:/run/user/1000/pulse/native",
    HOME: "/home/user",
  };
  const display = { DISPLAY: ":7", WAYLAND_DISPLAY: "private" };
  assert.deepEqual(appEnvironment(desktop, display, "linux"), {
    HOME: "/home/user",
    ...display,
  });
  assert.equal(
    appEnvironment(desktop, {}, "linux").DBUS_SESSION_BUS_ADDRESS,
    desktop.DBUS_SESSION_BUS_ADDRESS,
  );
});
