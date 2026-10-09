import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { root, requireNode } from "../scripts/dependencies.mjs";
import { windowSize } from "../app/electron/window-size.cjs";
import { EventEmitter } from "node:events";
import os from "node:os";
import { rendererRecovery } from "../app/electron/renderer-recovery.cjs";
import { Diagnostics } from "../app/electron/diagnostics.cjs";
import { rendererFailure } from "../app/src/app/rendererErrors.ts";
import { homeRelative } from "../app/src/ui/displayPath.ts";

const turn = () => new Promise<void>((resolve) => setImmediate(resolve));

function recoveryFixture() {
  const contents = new EventEmitter(),
    window = new EventEmitter();
  const prompts: {
    options: any;
    answer: (value: { response: number }) => void;
  }[] = [];
  const events: string[] = [];
  let crashed = false,
    closing = false;
  Object.assign(contents, {
    isDestroyed: () => false,
    isCrashed: () => crashed,
    forcefullyCrashRenderer: () => {
      events.push("kill");
      crashed = true;
      contents.emit(
        "render-process-gone",
        {},
        { reason: "killed", exitCode: 0 },
      );
    },
    reload: () => events.push("reload"),
  });
  Object.assign(window, { webContents: contents, isDestroyed: () => false });
  const recovery = rendererRecovery(window, {
    diagnostics: {
      record: (event: string) => events.push(event),
      failure: () => events.push("failure"),
      report: () => "safe diagnostics",
    },
    clipboard: { writeText: (text: string) => events.push(text) },
    beforeReload: () => events.push("reset-ready"),
    closing: () => closing,
    dialog: {
      showMessageBox: (_window: unknown, options: unknown) =>
        new Promise((resolve) => prompts.push({ options, answer: resolve })),
    },
  });
  return {
    window,
    contents,
    prompts,
    events,
    recovery,
    close: () => {
      closing = true;
    },
    crash: () => {
      crashed = true;
      contents.emit(
        "render-process-gone",
        {},
        { reason: "crashed", exitCode: 1 },
      );
    },
  };
}

test("renderer recovery offers one native prompt and replaces a hung interface only on explicit reload", async () => {
  const f = recoveryFixture();
  f.window.emit("unresponsive");
  f.window.emit("unresponsive");
  assert.equal(f.prompts.length, 1);
  assert.equal(f.events.includes("reload"), false);
  f.prompts[0].answer({ response: 1 });
  await turn();
  assert.deepEqual(f.events.slice(-5), [
    "reset-ready",
    "renderer.reload",
    "kill",
    "renderer.gone",
    "reload",
  ]);
  assert.equal(f.prompts.length, 1); // The intentional process replacement cannot open a second prompt.
  f.recovery.reload();
  assert.equal(f.events.filter((event) => event === "reload").length, 1);
  f.contents.emit("did-finish-load");
  assert.equal(f.recovery.failed(), false);
});

test("crash recovery can copy diagnostics, and stale dialog responses cannot reload a recovered or closing window", async () => {
  const crashed = recoveryFixture();
  crashed.crash();
  crashed.prompts[0].answer({ response: 2 });
  await turn();
  assert.ok(crashed.events.includes("safe diagnostics"));
  assert.equal(crashed.prompts.length, 2);
  crashed.prompts[1].answer({ response: 1 });
  await turn();
  assert.ok(crashed.events.includes("reload"));
  assert.equal(crashed.events.includes("kill"), false);
  for (const finish of [
    (f: ReturnType<typeof recoveryFixture>) => f.window.emit("responsive"),
    (f: ReturnType<typeof recoveryFixture>) => f.close(),
  ]) {
    const f = recoveryFixture();
    f.window.emit("unresponsive");
    finish(f);
    f.prompts[0].answer({ response: 1 });
    await turn();
    assert.equal(f.events.includes("reload"), false);
  }
});

test("diagnostics map renderer frames to source and keep backend hang records, without messages, paths, or arbitrary rejection data", async (t) => {
  const checkout = fs.mkdtempSync(
    path.join(os.tmpdir(), "dazedtl-diagnostics-"),
  );
  t.after(() => fs.rmSync(checkout, { recursive: true, force: true }));
  const error = new TypeError(
    "private game text\n    at private (/assets/not-code.js:1:2)",
  );
  error.stack = `${error.name}: ${error.message}\n    at render (file:///private/home/app/dist/assets/index-abc.js:2:5)\n    at secret (file:///private/credentials.json:12:3)`;
  const fields = rendererFailure(error, "render");
  assert.deepEqual(fields.causes, [
    {
      type: "TypeError",
      frames: [
        {
          file: "app/renderer/assets/index-abc.js",
          line: 2,
          column: 5,
          function: "unknown",
        },
      ],
    },
  ]);
  const assets = path.join(checkout, "app/dist/assets");
  fs.mkdirSync(assets, { recursive: true });
  fs.writeFileSync(
    path.join(assets, "index-abc.js.map"),
    JSON.stringify({
      version: 3,
      sources: ["../../src/app/View.tsx"],
      names: [],
      mappings: ";AAEA", // Generated line 2 starts at source line 3.
    }),
  );
  const diagnostics = new Diagnostics(
    path.join(checkout, "diagnostics"),
    { app: "fixture" },
    checkout,
  );
  diagnostics.renderer(
    "render",
    fields.causes.map((cause) => ({ ...cause, message: error.message })),
  );
  // The backend's hang records reach the report with only their safe fields.
  fs.writeFileSync(
    path.join(checkout, "diagnostics/backend-failures.jsonl"),
    JSON.stringify({
      time: "2026-10-09T18:00:00.000Z",
      event: "operation.stalled",
      action: "git_setup",
      seconds: 60,
      message: "private game text",
      causes: [
        {
          type: "Stack",
          frames: [{ file: "python/subprocess.py", line: 9, function: "run" }],
        },
      ],
    }) + "\n",
  );
  const report = await diagnostics.report();
  assert.match(
    report,
    /"file":"app\/app\/src\/app\/View.tsx","line":3,"column":5/,
  );
  assert.match(
    report,
    /"event":"operation.stalled","seconds":60,"action":"git_setup","causes":\[\{"type":"Stack","frames":\[\{"file":"python\/subprocess.py","line":9,"function":"run"\}\]\}\]/,
  );
  assert.doesNotMatch(report, /private|credentials|not-code|index-abc/);
  assert.deepEqual(
    rendererFailure(
      { message: "secret", stack: "private" },
      "unhandledrejection",
    ).causes,
    [{ type: "Error", frames: [] }],
  );
});

test("desktop bounds fit scaled work areas without enlarging the default window on 4K displays", () => {
  for (const area of [
    { width: 3840, height: 2100 },
    { width: 1920, height: 1020 },
    { width: 1024, height: 540 },
    { width: 768, height: 460 },
  ]) {
    const bounds = windowSize(area);
    assert.ok(bounds.width <= area.width && bounds.height <= area.height);
    assert.ok(
      bounds.minWidth <= bounds.width && bounds.minHeight <= bounds.height,
    );
  }
  assert.deepEqual(
    windowSize({ width: 3840, height: 2100 }),
    windowSize({ width: 1920, height: 1020 }),
  );
});

test("Node updates can launch the app while setup retains its exact runtime pin", () => {
  const expected = fs
    .readFileSync(path.join(root, ".node-version"), "utf8")
    .trim();
  const [major, minor, patch] = expected.split(".").map(Number);
  const descriptor = Object.getOwnPropertyDescriptor(process.versions, "node")!;
  const cases = [
    { version: expected, supported: true, exact: true },
    {
      version: `${major}.${minor}.${patch + 1}`,
      supported: true,
      exact: false,
    },
    { version: `${major}.${minor + 1}.0`, supported: true, exact: false },
    { version: `${major}.${minor - 1}.0`, supported: false, exact: false },
    { version: `${major + 1}.0.0`, supported: false, exact: false },
    { version: `${major - 1}.99.0`, supported: false, exact: false },
    { version: `${major}.${minor + 1}.0-rc.1`, supported: false, exact: false },
  ];
  try {
    for (const { version, supported, exact } of cases) {
      Object.defineProperty(process.versions, "node", {
        ...descriptor,
        value: version,
      });
      if (supported) assert.doesNotThrow(() => requireNode(), version);
      else assert.throws(() => requireNode(), /Use Node/, version);
      if (exact)
        assert.doesNotThrow(() => requireNode({ exact: true }), version);
      else
        assert.throws(() => requireNode({ exact: true }), /for setup/, version);
    }
  } finally {
    Object.defineProperty(process.versions, "node", descriptor);
  }
});

test("paths inside the home folder read home-relative, and only there", () => {
  assert.equal(
    homeRelative("/home/ana/Downloads/Game", "/home/ana"),
    "~/Downloads/Game",
  );
  assert.equal(
    homeRelative("/home/anabel/Game", "/home/ana"),
    "/home/anabel/Game",
  );
  assert.equal(
    homeRelative("c:\\users\\Ana\\Games\\X", "C:\\Users\\Ana"),
    "~\\Games\\X",
  );
  assert.equal(homeRelative("/tmp/Game", ""), "/tmp/Game");
});
