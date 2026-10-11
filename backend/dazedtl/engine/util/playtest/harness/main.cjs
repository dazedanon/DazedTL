// Plays an RPG Maker MV/MZ game in a hidden window for the release playtest.
// It serves the game folder read-only on 127.0.0.1, runs the tour page.js
// defines, and writes runtime.json and its captures to the output folder.
// Progress goes to stdout as one JSON object a line.
//
//   electron main.cjs --game <folder with index.html> --out <folder>
//                     --plan <stops.json> [--width W] [--height H]
//                     [--minutes M]
"use strict";
const { app, BrowserWindow } = require("electron");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const SCHEMA = "rpgmaker-playtest-runtime-v1";
const POLL_MS = 250;
// A page that answers nothing for this long has hung.
const HUNG_MS = 20_000;
// Crashes the tour survives by reloading before it gives up.
const CRASH_LIMIT = 4;
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".ogg": "audio/ogg",
  ".m4a": "audio/mp4",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".webm": "video/webm",
  ".mp4": "video/mp4",
  ".wasm": "application/wasm",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".txt": "text/plain; charset=utf-8",
};

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index > 0 ? process.argv[index + 1] : fallback;
}

const game = path.resolve(option("--game"));
const out = path.resolve(option("--out"));
const plan = JSON.parse(fs.readFileSync(option("--plan"), "utf8"));
const width = Number(option("--width", 816));
const height = Number(option("--height", 624));
const deadline = Date.now() + Number(option("--minutes", 15)) * 60_000;
// Writes the page's console and state to stdout, for working on the tour.
const debug = process.argv.includes("--trace");
const captures = path.join(out, "captures");
const profile = path.join(out, ".profile");
fs.mkdirSync(captures, { recursive: true });

const say = (value) => process.stdout.write(JSON.stringify(value) + "\n");

app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
// Software WebGL where the system has no GPU, as on a build machine.
app.commandLine.appendSwitch("enable-unsafe-swiftshader");
app.commandLine.appendSwitch("disable-renderer-backgrounding");
app.commandLine.appendSwitch("disable-background-timer-throttling");
// Saves, options and caches stay in this run's folder, never the game's.
app.setPath("userData", profile);
app.on("window-all-closed", () => {});

// ------------------------------------------------------------------ server

const token = crypto.randomBytes(12).toString("hex");

function serve(request, response) {
  const url = new URL(request.url, "http://127.0.0.1");
  const prefix = `/${token}/`;
  if (
    !["GET", "HEAD"].includes(request.method) ||
    !url.pathname.startsWith(prefix)
  ) {
    response.writeHead(404).end();
    return;
  }
  let relative;
  try {
    relative = decodeURIComponent(url.pathname.slice(prefix.length));
  } catch {
    response.writeHead(400).end();
    return;
  }
  const file = path.resolve(game, relative);
  if (file !== game && !file.startsWith(game + path.sep)) {
    response.writeHead(403).end();
    return;
  }
  fs.stat(file, (problem, stat) => {
    if (problem || !stat.isFile()) {
      response.writeHead(404).end();
      return;
    }
    const headers = {
      "Content-Type":
        TYPES[path.extname(file).toLowerCase()] || "application/octet-stream",
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store",
    };
    let start = 0;
    let end = stat.size - 1;
    const range = /^bytes=(\d*)-(\d*)$/.exec(request.headers.range || "");
    if (range && stat.size) {
      start = range[1]
        ? Number(range[1])
        : Math.max(0, stat.size - Number(range[2]));
      end = range[1] && range[2] ? Math.min(Number(range[2]), end) : end;
      if (start > end) {
        response
          .writeHead(416, { "Content-Range": `bytes */${stat.size}` })
          .end();
        return;
      }
      headers["Content-Range"] = `bytes ${start}-${end}/${stat.size}`;
    }
    headers["Content-Length"] = stat.size ? end - start + 1 : 0;
    response.writeHead(range ? 206 : 200, headers);
    if (request.method === "HEAD" || !stat.size) response.end();
    else fs.createReadStream(file, { start, end }).pipe(response);
  });
}

// ------------------------------------------------------------------ report

const report = {
  schema: SCHEMA,
  started_at: new Date().toISOString(),
  resolution: [width, height],
  stops: plan.stops.map((stop) => ({
    id: stop.id,
    ...(stop.title && { title: stop.title }),
    status: "not-reached",
  })),
  errors: [],
  japanese: [],
  overflow: [],
  scenes: [],
  captures: [],
  messages: { shown: 0, choices: 0, sources: {} },
  battle: 0,
  crashes: [],
};
let finished = false;
let current = -1;
// The crash a stop reported since the page last loaded.
let crash = "";
// Errors already recorded, across reloads of the page.
const recorded = new Set();

function take(event) {
  const { type, ...value } = event;
  if (["error", "japanese", "overflow"].includes(type)) {
    const key = JSON.stringify([
      type,
      value.message || value.text,
      value.window || "",
      value.source?.file || "",
      value.data?.pointer || "",
    ]);
    if (recorded.has(key)) return;
    recorded.add(key);
  }
  if (type === "start") {
    current = value.index;
    report.stops[value.index].status = "running";
    say({
      progress: "stop",
      index: value.index,
      id: value.id,
      total: plan.stops.length,
    });
  } else if (type === "stop") {
    const index = value.index ?? current;
    if (report.stops[index]) {
      delete value.index;
      Object.assign(report.stops[index], value);
    }
    if (value.crashed) {
      report.crashes.push({ stop: value.id, note: value.note });
      crash = value.note;
    }
  } else if (type === "done") {
    finished = true;
  } else if (type === "capture") {
    const file = `${value.name}.jpg`;
    const data = String(value.data || "").split(",", 2)[1];
    if (data) {
      fs.writeFileSync(path.join(captures, file), Buffer.from(data, "base64"));
      report.captures.push({
        name: value.name,
        file: `captures/${file}`,
        stop: value.stop,
        scene: value.scene,
      });
    }
  } else if (type === "error") report.errors.push(value);
  else if (type === "japanese") report.japanese.push(value);
  else if (type === "overflow") report.overflow.push(value);
  else if (type === "scene") report.scenes.push(value);
  else if (type === "message") {
    report.messages.shown++;
    if (value.data) {
      const key = `${value.data.file}#${value.data.pointer}`;
      report.messages.sources[key] = (report.messages.sources[key] || 0) + 1;
    }
  } else if (type === "choice") report.messages.choices++;
  else if (type === "battle") report.battle++;
}

function write() {
  report.finished_at = new Date().toISOString();
  report.complete = finished;
  fs.writeFileSync(
    path.join(out, "runtime.json"),
    JSON.stringify(report, null, 1),
  );
}

// ------------------------------------------------------------------ tour

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Runs code in the page, or gives up when it does not answer. */
function evaluate(window_, code, ms = 5000) {
  return Promise.race([
    window_.webContents.executeJavaScript(code, true),
    delay(ms).then(() => {
      throw new Error("timeout");
    }),
  ]);
}

async function play(window_, url) {
  let from = 0;
  let gone = "";
  let loads = 0;
  window_.webContents.on("render-process-gone", (_event, details) => {
    gone = `The game's page stopped (${details.reason}).`;
  });
  if (debug)
    window_.webContents.on("console-message", (event) =>
      say({
        console: event.level,
        message: String(event.message).slice(0, 400),
      }),
    );
  // Each crash costs a reload; a game that keeps crashing ends the tour.
  while (!finished && Date.now() < deadline && loads++ <= CRASH_LIMIT) {
    gone = "";
    crash = "";
    await window_.loadURL(url).catch(() => {});
    const started = await evaluate(
      window_,
      `window.__playtest ? window.__playtest.start(${JSON.stringify({ ...plan, from })}) : false`,
    ).catch(() => false);
    if (!started) {
      report.crashes.push({
        stop: plan.stops[from]?.id,
        note: "The game's page did not load.",
      });
      break;
    }
    let lastFrame = -1;
    let lastProgress = Date.now();
    let crashed = "";
    while (!finished && Date.now() < deadline) {
      await delay(POLL_MS);
      if (gone) {
        crashed = gone;
        break;
      }
      let state;
      try {
        state = await evaluate(window_, "window.__playtest.drain()");
      } catch {
        if (Date.now() - lastProgress > HUNG_MS) {
          crashed = "The game stopped responding.";
          window_.webContents.forcefullyCrashRenderer();
          break;
        }
        continue;
      }
      for (const event of state.events) take(event);
      if (debug)
        say({ debug: state.debug, scene: state.scene, frame: state.frame });
      if (
        state.size &&
        (state.size[0] !== report.resolution[0] ||
          state.size[1] !== report.resolution[1])
      ) {
        report.resolution = state.size;
        window_.setContentSize(state.size[0], state.size[1]);
      }
      if (state.frame !== lastFrame) {
        lastFrame = state.frame;
        lastProgress = Date.now();
      } else if (Date.now() - lastProgress > HUNG_MS && current >= 0) {
        crashed = "The game stopped drawing.";
        break;
      }
      if (crash) {
        crashed = crash;
        break;
      }
    }
    if (finished || Date.now() >= deadline) break;
    if (crashed) {
      const stop = report.stops[current];
      if (stop && stop.status === "running")
        Object.assign(stop, { status: "failed", note: crashed, crashed: true });
      if (
        !report.crashes.some(
          (row) => row.note === crashed && row.stop === stop?.id,
        )
      )
        report.crashes.push({ stop: stop?.id, note: crashed });
      say({ progress: "crash", index: current, note: crashed });
    }
    from = Math.max(from, current + 1);
    if (from >= plan.stops.length) {
      finished = true;
      break;
    }
  }
  if (!finished)
    for (const stop of report.stops)
      if (stop.status === "running")
        Object.assign(stop, {
          status: "failed",
          note: "The playtest ran out of time.",
        });
}

app.whenReady().then(async () => {
  const server = http.createServer(serve);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const entry = (() => {
    try {
      const manifest = JSON.parse(
        fs.readFileSync(path.join(game, "package.json"), "utf8"),
      );
      return /\.html?$/i.test(manifest.main || "")
        ? manifest.main
        : "index.html";
    } catch {
      return "index.html";
    }
  })();
  const window_ = new BrowserWindow({
    show: false,
    width,
    height,
    useContentSize: true,
    webPreferences: {
      offscreen: true,
      backgroundThrottling: false,
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
      preload: path.join(__dirname, "page.js"),
    },
  });
  const contents = window_.webContents;
  contents.setAudioMuted(true);
  contents.setFrameRate(60);
  // The game reaches nothing but its own folder: no links, no pop-ups, no
  // network and no permissions.
  contents.setWindowOpenHandler(() => ({ action: "deny" }));
  contents.on("will-navigate", (event, url) => {
    if (!url.startsWith(origin + "/")) event.preventDefault();
  });
  contents.session.setPermissionRequestHandler(
    (_contents, _permission, answer) => answer(false),
  );
  contents.session.webRequest.onBeforeRequest((details, answer) =>
    answer({
      cancel:
        !/^(?:data|blob|devtools|chrome-extension):/.test(details.url) &&
        !details.url.startsWith(origin + "/"),
    }),
  );
  try {
    await play(window_, `${origin}/${token}/${entry}`);
  } catch (problem) {
    report.crashes.push({
      stop: report.stops[current]?.id,
      note: `The playtest failed: ${problem.message}`,
    });
  }
  write();
  say({ progress: "done", complete: finished });
  server.close();
  window_.destroy();
  fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3 });
  app.exit(0);
});
