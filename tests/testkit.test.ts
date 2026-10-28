import assert from "node:assert/strict";
import { execFile, spawn } from "node:child_process";
import fs from "node:fs";
import { once } from "node:events";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { appEnvironment, stopApp } from "../scripts/testkit/app.mjs";
import { until } from "../scripts/testkit/cdp.mjs";
import { ciScenarios } from "../scripts/testkit/ci.mjs";
import { displayName } from "../scripts/testkit/display.mjs";
import { startProvider } from "../scripts/testkit/provider.mjs";
import { testsWithRetry, withRetry } from "../scripts/testkit/retry.mjs";

test("CI runs every test scenario, so a new one cannot land unchecked", () => {
  assert.ok(ciScenarios().some(([name]) => name === "fresh"));
  assert.throws(
    () => ciScenarios("jobs:\n  matrix:\n    scenarios:\n      - fresh\n"),
    /CI runs no opened, .* scenario/,
  );
});

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

test("a test run that fails on a busy machine runs again once the load falls, waiting at most five minutes", async () => {
  const suite =
    (...statuses: number[]) =>
    async () => {
      const status = statuses.shift() ?? 1;
      return { status, output: `run ${status}` };
    };
  let waited = 0;
  const logged: string[] = [];
  const deps = (...loads: number[]) => ({
    wait: async (ms: number) => (waited += ms),
    log: (line: string) => logged.push(line),
    load: () => loads.shift() ?? loads.at(-1) ?? 3,
  });
  // A passing run waits for nothing.
  assert.deepEqual(await testsWithRetry(suite(0), deps(3)), {
    passed: true,
    flaky: false,
    outputs: ["run 0"],
  });
  assert.equal(waited, 0);
  // A failed run waits while the machine is busy, then passes as a flake.
  const flaky = await testsWithRetry(suite(1, 0), deps(2, 2, 0.5));
  assert.deepEqual(flaky, {
    passed: true,
    flaky: true,
    outputs: ["run 1", "run 0"],
  });
  assert.equal(waited, 20_000);
  assert.equal(logged.length, 1);
  // A machine that stays busy delays the second run five minutes at most.
  waited = 0;
  assert.equal((await testsWithRetry(suite(1, 1), deps(4))).passed, false);
  assert.equal(waited, 300_000);
});

test("the stand-in records each request's JSON body and never its credentials", async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-stand-in-"));
  const provider = await startProvider({ folder });
  try {
    const sent = {
      model: "stand-in",
      reasoning_effort: "high",
      messages: [{ role: "user", content: "Reply with OK." }],
    };
    const response = await fetch(`${provider.url}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer sk-test-secret",
      },
      body: JSON.stringify(sent),
    });
    assert.equal(response.status, 200);
    await fetch(`${provider.url}/models`, {
      headers: { Authorization: "Bearer sk-test-secret" },
    });
    await until(
      "both requests recorded",
      () => provider.requests().length === 2,
    );
    const [chat, models] = provider.requests();
    assert.deepEqual(chat.body, sent);
    assert.equal(models.route, "/models");
    assert.equal("body" in models, false);
    assert.doesNotMatch(
      fs.readFileSync(path.join(folder, "requests.jsonl"), "utf8"),
      /sk-test-secret/,
    );
  } finally {
    await provider.close();
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test("two runs whose work folders share a last part get different displays", () => {
  const names = ["/tmp/a/w", "/tmp/b/w"].map(displayName);
  assert.notEqual(names[0], names[1]);
  assert.match(names[0], /^dazedtl-w-[0-9a-f]{6}$/);
});

test(
  "stopApp closes the app's main process and returns only once its child processes have exited too",
  {
    skip: process.platform === "win32",
  },
  async () => {
    // The main process closes at SIGTERM and leaves a child behind, as
    // Electron's does with Chromium's and its session bus with desktop
    // portals, none of which carry the scenario's marker. What started it
    // ends at SIGTERM without passing it on, as dbus-run-session does.
    const main =
      "trap 'echo closed; exit 0' TERM; sleep 30 >/dev/null & echo $$; wait";
    const leader = spawn("sh", ["-c", 'sh -c "$0" & wait', main], {
      detached: true,
      stdio: ["ignore", "pipe", "ignore"],
    });
    leader.stdout.setEncoding("utf8");
    const [pid] = await once(leader.stdout, "data");
    let output = "";
    leader.stdout.on("data", (text) => (output += text));
    const ended = once(leader.stdout, "end");
    const group = leader.pid as number;
    await stopApp("no-such-tag", { pid: group, main: Number(pid) }, 5_000);
    assert.throws(() => process.kill(-group, 0), { code: "ESRCH" });
    await ended;
    assert.equal(output, "closed\n");
  },
);

test(
  "a display's process group ends with the process that started it, even at SIGKILL, unless it is to outlive it",
  { skip: process.platform !== "linux" },
  async () => {
    // Each group's first process exits at SIGTERM and leaves its child, as
    // dbus-run-session does with KWin.
    const owner = spawn(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        `const { spawnGroup } = await import(${JSON.stringify(new URL("../scripts/testkit/display.mjs", import.meta.url).href)});
        const group = (outlive) =>
          spawnGroup("sh", ["-c", "sleep 30 & wait"], { stdio: "ignore", outlive }).pid;
        console.log(JSON.stringify([group(false), group(true)]));
        setInterval(() => {}, 1000);`,
      ],
      { stdio: ["ignore", "pipe", "inherit"] },
    );
    let groups: number[] = [];
    // A live member of `group`; an exited one waits as a zombie to be reaped.
    const members = (group: number) =>
      fs.readdirSync("/proc").filter((pid) => {
        try {
          const [state, , , pgrp] = fs
            .readFileSync(`/proc/${pid}/stat`, "utf8")
            .split(") ")[1]
            .split(" ");
          return state !== "Z" && Number(pgrp) === group;
        } catch {
          return false; // Not a process, or exited.
        }
      }).length;
    try {
      const [line] = await once(readline.createInterface(owner.stdout), "line");
      groups = JSON.parse(line);
      const [bound, kept] = groups;
      await until(
        "both groups' children",
        () => groups.every((group) => members(group) >= 2),
        5_000,
      );
      owner.kill("SIGKILL");
      await until("the bound group to end", () => !members(bound), 5_000);
      assert.equal(members(kept), 2);
    } finally {
      owner.kill("SIGKILL");
      for (const group of groups)
        try {
          process.kill(-group, "SIGKILL");
        } catch {
          // Already gone.
        }
    }
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

test("the scripts that start apps, displays or long checks refuse an option they do not know before starting anything", async () => {
  // A work folder with files, which each script refuses too, so one that
  // read past the option would stop at that instead of starting.
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-options-"));
  fs.mkdirSync(path.join(work, "QA チェック (前版)"));
  fs.writeFileSync(path.join(work, "QA チェック (前版)", "kept"), "");
  const script = (name: string) =>
    fileURLToPath(new URL(`../scripts/${name}`, import.meta.url));
  const run = (args: string[]) =>
    new Promise<{ code: unknown; output: string }>((resolve) =>
      execFile(process.execPath, args, (error, stdout, stderr) =>
        resolve({ code: error ? error.code : 0, output: stdout + stderr }),
      ),
    );
  try {
    const [help, ...refused] = await Promise.all([
      run([script("release-check.mjs"), "--help", "--work", work]),
      ...[
        ["release-check.mjs"],
        ["e2e.mjs"],
        ["qa-upgrade.mjs"],
        ["scenario.mjs", "fresh"],
      ].map(([name, ...args]) =>
        run([script(name), ...args, "--bogus", "--work", work]),
      ),
    ]);
    assert.equal(help.code, 0, help.output);
    assert.match(help.output, /^Usage: node scripts\/release-check\.mjs/);
    for (const result of refused) {
      assert.equal(result.code, 2, result.output);
      assert.match(result.output, /^Unknown option --bogus\.\n\nUsage:/);
    }
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
});
