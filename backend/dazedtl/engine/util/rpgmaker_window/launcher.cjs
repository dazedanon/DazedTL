// Runs an RPG Maker MV/MZ game in hidden Electron windows for a harness that
// plays it, such as Text QA's screen capture or the release playtest.
//
// The game folder is served read-only through a private game:// protocol,
// finding files whatever their case as Windows would, to offscreen, muted
// windows in an in-memory session with no network, pop-ups, downloads or
// permissions: saves and settings never reach the game folder, and the game
// reaches nothing outside it. The harness's page script runs before the
// game's own and talks to its main script through bridge.cjs. A window whose
// game crashes, hangs or stops drawing is replaced by a new one, where the
// page carries on from the plan the harness gives it.
//
// A harness main script calls `launch` and is run as
// `electron <harness main script> <plan.json>` by __init__.py; `--trace`
// after the plan writes the page's console to stdout. Each stdout line is
// one JSON object: the launcher's own name `launcher`.
"use strict";

const { app, BrowserWindow, ipcMain, protocol, session } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { Readable } = require("node:stream");

const ORIGIN = "game://game/";
const POLL_MS = 250;
// A page that answers nothing, or draws nothing, for this long has hung.
const HUNG_MS = 20_000;
// How long a game may take to show its first scene.
const BOOT_MS = 60_000;
// How long the game's error screen shows before the window is replaced,
// which leaves the page time to say why in its own words.
const ERROR_MS = 3_000;
// Crashes a run survives, each with a new window, before it gives up.
const CRASH_LIMIT = 4;
const TYPES = {
  ".css": "text/css; charset=utf-8",
  ".gif": "image/gif",
  ".html": "text/html; charset=utf-8",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".m4a": "audio/mp4",
  ".mp3": "audio/mpeg",
  ".mp4": "video/mp4",
  ".ogg": "audio/ogg",
  ".otf": "font/otf",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ttf": "font/ttf",
  ".txt": "text/plain; charset=utf-8",
  ".wasm": "application/wasm",
  ".wav": "audio/wav",
  ".webm": "video/webm",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};
// What the launcher reads from the game each poll: whether it still draws,
// its screen size, whether it got past booting, and an error it shows.
const PROBE = `(() => {
  const scene = window.SceneManager && SceneManager._scene;
  const printer = window.Graphics && Graphics._errorPrinter;
  return {
    frame: window.Graphics ? Graphics.frameCount || 0 : 0,
    size: window.Graphics && Graphics.width ? [Graphics.width, Graphics.height] : null,
    booted: !!scene && !(window.Scene_Boot && scene instanceof Scene_Boot),
    error: printer ? String(printer.innerText || printer.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 400) : "",
  };
})()`;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Whether a process is running. */
function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (problem) {
    return problem.code === "EPERM";
  }
}

/** Runs code in a window's page, or gives up when it does not answer. */
function evaluate(window_, code, ms = 5000) {
  return Promise.race([
    // A window that went away rejects instead of throwing.
    Promise.resolve().then(() =>
      window_.webContents.executeJavaScript(code, true),
    ),
    delay(ms).then(() => {
      throw new Error("timeout");
    }),
  ]);
}

/** A value with the game's address taken out of its text, as in the stacks
 * of the page's errors; data: URLs, such as captures, stay as they are. */
function clean(value) {
  if (typeof value === "string")
    return value.startsWith("data:") ? value : value.split(ORIGIN).join("");
  if (Array.isArray(value)) return value.map(clean);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, clean(item)]),
    );
  return value;
}

/** A capture's file name, kept inside the output folder. */
function fileName(name) {
  return String(name).replace(/[^\w.-]+/g, "_").replace(/^\.+/, "_");
}

/**
 * Plays the game for a harness; call it before Electron is ready.
 *
 * `setup(run)` gets the run: its `plan` (the harness's part of plan.json),
 * `out` folder, `size`, `seconds`, `say(value)` for stdout, `fileName(name)`
 * and `restart(note)`, which ends the window when the page finds the game
 * stopped. It returns the harness:
 *   page              the script the page runs before the game's own
 *   plan()            what the page does in its next window
 *   take(type, value) an event the page sent, with the game's address
 *                     taken out
 *   calls             {name: async (window, ...values) => result} the page
 *                     may call
 *   console(level, message), resized(size), trace               optional;
 *                     `trace` is code whose value --trace writes each poll
 *   recover(note, step) records a crash or hang during `step` and says
 *                     whether to go on in a new window
 *   finish({note, timedOut}) writes the results; `note` is why the game
 *                     wouldn't start or kept stopping
 */
function launch(setup) {
  const settings = JSON.parse(
    fs.readFileSync(process.argv[process.argv.length - 1], "utf8"),
  );
  const web = path.resolve(settings.web);
  const overlay = Object.fromEntries(
    Object.entries(settings.overlay || {}).map(([key, file]) => [
      key.toLowerCase(),
      path.resolve(file),
    ]),
  );
  const seconds = settings.seconds || 600;
  const deadline = Date.now() + seconds * 1000;
  const trace = process.argv.includes("--trace");
  let restarting = "";
  const run = {
    plan: settings.harness || {},
    out: path.resolve(settings.out),
    size: [settings.width || 816, settings.height || 624],
    seconds,
    say: (value) => process.stdout.write(JSON.stringify(value) + "\n"),
    fileName,
    restart(note) {
      restarting ||= note || "The game stopped.";
    },
  };

  protocol.registerSchemesAsPrivileged([
    {
      scheme: "game",
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        corsEnabled: true,
        stream: true,
      },
    },
  ]);
  app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
  // Software WebGL where the system has no GPU for it.
  app.commandLine.appendSwitch("enable-unsafe-swiftshader");
  app.commandLine.appendSwitch("disable-renderer-backgrounding");
  app.commandLine.appendSwitch("disable-background-timer-throttling");
  // Electron's own caches go to the run's profile, never the user's.
  app.setPath("userData", path.resolve(settings.profile));
  app.on("window-all-closed", () => {});
  // The run ends with the process that started it: its stdout breaks, or it
  // is gone. Windows never gives a process another parent, and Electron's
  // stdin there is not the pipe.
  const parent = process.ppid;
  setInterval(() => {
    if (process.ppid !== parent || !alive(parent)) app.exit(1);
  }, 2000).unref();
  process.stdout.on("error", () => app.exit(1));
  // A hidden run never waits at Electron's error dialog.
  process.on("uncaughtException", (problem) => {
    try {
      process.stderr.write(`${problem?.stack || problem}\n`);
    } finally {
      app.exit(1);
    }
  });

  const harness = setup(run);
  fs.mkdirSync(run.out, { recursive: true });

  // ---------------------------------------------------------------- serving

  /** A file under the game's web folder, matching its case as Windows
   * would, or null for one outside it. */
  function gameFile(relative) {
    let current = web;
    for (const part of relative.split("/").filter(Boolean)) {
      if (part === "." || part === ".." || /[\\:\0]/.test(part)) return null;
      const exact = path.join(current, part);
      if (fs.existsSync(exact)) {
        current = exact;
        continue;
      }
      let names = [];
      try {
        names = fs.readdirSync(current);
      } catch {
        return null;
      }
      const match = names.find(
        (name) => name.toLowerCase() === part.toLowerCase(),
      );
      if (!match) return null;
      current = path.join(current, match);
    }
    return current;
  }

  async function serve(request) {
    let relative;
    try {
      relative = decodeURIComponent(new URL(request.url).pathname).replace(
        /^\/+/,
        "",
      );
    } catch {
      return new Response("", { status: 400 });
    }
    if (!["GET", "HEAD"].includes(request.method))
      return new Response("", { status: 405 });
    const file = overlay[relative.toLowerCase()] || gameFile(relative);
    let stat;
    try {
      stat = file && (await fs.promises.stat(file));
    } catch {
      stat = null;
    }
    if (!stat || !stat.isFile()) return new Response("", { status: 404 });
    const headers = {
      "Content-Type":
        TYPES[path.extname(file).toLowerCase()] || "application/octet-stream",
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store",
    };
    // Media elements read audio and video in ranges.
    let start = 0;
    let end = stat.size - 1;
    const range = /^bytes=(\d*)-(\d*)$/.exec(request.headers.get("range") || "");
    if (range && stat.size) {
      start = range[1]
        ? Number(range[1])
        : Math.max(0, stat.size - Number(range[2]));
      end = range[1] && range[2] ? Math.min(Number(range[2]), end) : end;
      if (start > end)
        return new Response("", {
          status: 416,
          headers: { "Content-Range": `bytes */${stat.size}` },
        });
      headers["Content-Range"] = `bytes ${start}-${end}/${stat.size}`;
    }
    headers["Content-Length"] = String(stat.size ? end - start + 1 : 0);
    const body =
      request.method === "HEAD" || !stat.size
        ? null
        : Readable.toWeb(fs.createReadStream(file, { start, end }));
    return new Response(body, { status: range ? 206 : 200, headers });
  }

  /** The page the game starts from, as its package.json names it. */
  function entry() {
    try {
      const manifest = JSON.parse(
        fs.readFileSync(path.join(web, "package.json"), "utf8"),
      );
      if (/\.html?$/i.test(manifest.main || "") && gameFile(manifest.main))
        return manifest.main.replace(/^[./]+/, "");
    } catch {
      // MV keeps its package.json beside the www folder, if anywhere.
    }
    return "index.html";
  }

  // ---------------------------------------------------------------- windows

  let games;
  let current = null;
  // What the page last said it is doing.
  let step = "";
  let done = false;
  let started = false;

  function isolate() {
    // Not "persist:", so the session lives in memory and keeps nothing; its
    // windows share the saves the game made in an earlier one.
    games = session.fromPartition(`dazedtl-game-${process.pid}`);
    games.protocol.handle("game", serve);
    games.registerPreloadScript({
      type: "frame",
      filePath: path.join(__dirname, "bridge.cjs"),
    });
    games.setPermissionRequestHandler((_contents, _permission, answer) =>
      answer(false),
    );
    games.setPermissionCheckHandler(() => false);
    games.on("will-download", (event) => event.preventDefault());
    games.webRequest.onBeforeRequest((details, answer) =>
      answer({ cancel: !/^(?:game|data|blob|devtools):/.test(details.url) }),
    );
    const fromPage = (event) => current && event.sender === current.webContents;
    ipcMain.on("harness-plan", (event) => {
      event.returnValue = harness.plan();
    });
    ipcMain.on("harness-send", (event, type, value) => {
      // A window that went away has nothing more to say.
      if (!fromPage(event)) return;
      value = clean(value);
      if (type === "step") step = String(value);
      if (type === "done") done = true;
      harness.take(type, value);
    });
    ipcMain.handle("harness-call", (event, name, ...values) => {
      if (!fromPage(event)) throw new Error("This window has closed.");
      if (!Object.hasOwn(harness.calls || {}, name))
        throw new Error(`The harness has no call ${name}.`);
      return harness.calls[name](current, ...values);
    });
  }

  function open() {
    const window_ = new BrowserWindow({
      show: false,
      useContentSize: true,
      width: run.size[0],
      height: run.size[1],
      webPreferences: {
        session: games,
        preload: harness.page,
        offscreen: true,
        backgroundThrottling: false,
        // The page script runs in the game's own world, before its scripts.
        contextIsolation: false,
        nodeIntegration: false,
        sandbox: true,
        spellcheck: false,
      },
    });
    const contents = window_.webContents;
    contents.setAudioMuted(true);
    contents.setFrameRate(60);
    contents.setWindowOpenHandler(() => ({ action: "deny" }));
    // A game that quits stays open, as a browser tab it didn't open does.
    window_.on("close", (event) => event.preventDefault());
    contents.on("will-navigate", (event, url) => {
      if (!url.startsWith(ORIGIN)) event.preventDefault();
    });
    contents.on("console-message", (event) => {
      const message = clean(String(event.message)).slice(0, 2000);
      if (trace) run.say({ console: event.level, message: message.slice(0, 400) });
      harness.console?.(event.level, message);
    });
    return window_;
  }

  /** Watches one window until the page is done, the run's time is up, or
   * the game stops; why it stopped, and whether it got past booting. */
  async function watch(window_) {
    let gone = "";
    window_.webContents.on("render-process-gone", (_event, details) => {
      gone = `The game's page stopped (${details.reason}).`;
    });
    window_.webContents.on(
      "did-fail-load",
      (_event, code, description, _url, mainFrame) => {
        // -3 is a load another one replaced.
        if (mainFrame && code !== -3)
          gone = `The game's page did not load: ${description} (${code}).`;
      },
    );
    restarting = "";
    step = "";
    const loaded = Date.now();
    let answered = loaded;
    let drew = loaded;
    let frame = -1;
    let booted = false;
    let failing = 0;
    // A page that hangs while loading never finishes loading.
    window_.loadURL(ORIGIN + entry()).catch(() => {});
    while (!done && Date.now() < deadline) {
      await delay(POLL_MS);
      if (done) break;
      if (gone || restarting) return { note: gone || restarting, booted };
      let probe;
      try {
        probe = await evaluate(window_, PROBE);
      } catch {
        if (Date.now() - answered > HUNG_MS) {
          if (!window_.isDestroyed())
            window_.webContents.forcefullyCrashRenderer();
          return { note: "The game stopped responding.", booted };
        }
        continue;
      }
      answered = Date.now();
      if (trace && harness.trace)
        run.say({ trace: await evaluate(window_, harness.trace).catch(String) });
      if (
        probe.size &&
        (probe.size[0] !== run.size[0] || probe.size[1] !== run.size[1])
      ) {
        run.size = probe.size;
        window_.setContentSize(probe.size[0], probe.size[1]);
        harness.resized?.(probe.size);
      }
      const stopped = probe.error
        ? `The game stopped at its error screen: ${probe.error}`
        : "";
      if (!booted) {
        if (probe.booted) {
          booted = true;
          if (!started) run.say({ launcher: "started" });
          started = true;
        } else if (stopped) return { note: stopped, booted };
        else if (Date.now() - loaded > BOOT_MS)
          return { note: "The game did not finish starting.", booted };
        continue;
      }
      failing = stopped ? failing || Date.now() : 0;
      if (failing && Date.now() - failing > ERROR_MS)
        return { note: stopped, booted };
      if (probe.frame !== frame) {
        frame = probe.frame;
        drew = Date.now();
      } else if (Date.now() - drew > HUNG_MS)
        return { note: "The game stopped drawing.", booted };
    }
    return { note: "", booted };
  }

  /** Plays the game in a new window after each crash or hang, since a page
   * that crashed or hung may never load again in its own; why the run ended
   * before the page was done, unless the harness heard it already. */
  async function play() {
    let crashes = 0;
    while (!done && Date.now() < deadline) {
      current = open();
      const { note, booted } = await watch(current);
      const window_ = current;
      current = null;
      if (!window_.isDestroyed()) window_.destroy();
      if (done || Date.now() >= deadline) break;
      // A game that doesn't start, or start again, ends the run.
      if (!booted || ++crashes > CRASH_LIMIT) return note;
      if (!harness.recover(note, step)) break;
    }
    return "";
  }

  app.whenReady().then(async () => {
    let note = "";
    try {
      isolate();
      note = await play();
    } catch (problem) {
      note = `The game window failed: ${problem.message}`;
    }
    // The results go out whatever cleaning up does.
    try {
      harness.finish({ note, timedOut: !done && !note && Date.now() >= deadline });
      run.say({ launcher: "exit" });
      for (const window_ of BrowserWindow.getAllWindows())
        if (!window_.isDestroyed()) window_.destroy();
    } finally {
      app.exit(0);
    }
  });
}

module.exports = { launch };
