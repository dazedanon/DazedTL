// Captures an RPG Maker MV/MZ game's interface screens without changing it.
//
// Run with Electron: `electron capture.cjs <plan.json>`. The game loads
// read-only through a private protocol in an in-memory session, so saves and
// settings never reach the game folder; corrected data files can be served
// in place of the game's own. The harness opens each screen, and every
// capture is written to the plan's output folder with the text the game drew
// on it, listed in screens.json.
"use strict";

const { app, BrowserWindow, ipcMain, protocol, session } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const plan = JSON.parse(fs.readFileSync(process.argv[process.argv.length - 1], "utf8"));
const web = path.resolve(plan.web);
const out = path.resolve(plan.out);
const overlay = plan.overlay || {};
const result = { game: null, screens: [], skipped: [], errors: [] };
let finished = false;

const TYPES = {
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".json": "application/json",
  ".m4a": "audio/mp4",
  ".ogg": "audio/ogg",
  ".otf": "font/otf",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ttf": "font/ttf",
  ".wasm": "application/wasm",
  ".webm": "video/webm",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
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
// Electron's own caches go with the plan, never into the user's profile.
if (plan.profile) app.setPath("userData", path.resolve(plan.profile));

function finish(code) {
  if (finished) return;
  finished = true;
  fs.writeFileSync(path.join(out, "screens.json"), JSON.stringify(result, null, 1));
  app.exit(code);
}

/** A file under the game's web folder, matching its case as Windows would. */
function gameFile(relative) {
  let current = web;
  for (const part of relative.split("/").filter(Boolean)) {
    if (part === "." || part === "..") return null;
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
    const match = names.find((name) => name.toLowerCase() === part.toLowerCase());
    if (!match) return null;
    current = path.join(current, match);
  }
  return current;
}

async function serve(request) {
  const relative = decodeURIComponent(new URL(request.url).pathname).replace(/^\/+/, "") || "index.html";
  if (relative === "dazedtl-harness.js")
    return new Response(fs.readFileSync(path.join(__dirname, "harness.js")), {
      headers: { "content-type": "text/javascript" },
    });
  const file = overlay[relative] ? path.resolve(overlay[relative]) : gameFile(relative);
  if (!file) return new Response("", { status: 404 });
  try {
    let body = await fs.promises.readFile(file);
    if (relative === "index.html")
      body = Buffer.from(
        body
          .toString("utf8")
          .replace(/<\/body>/i, '<script src="dazedtl-harness.js"></script></body>'),
      );
    const type = TYPES[path.extname(file).toLowerCase()] || "application/octet-stream";
    return new Response(body, { headers: { "content-type": type } });
  } catch {
    return new Response("", { status: 404 });
  }
}

app.whenReady().then(() => {
  fs.mkdirSync(out, { recursive: true });
  // Not "persist:", so the session lives in memory and keeps nothing.
  const ses = session.fromPartition(`dazedtl-capture-${process.pid}`);
  ses.protocol.handle("game", serve);
  const window = new BrowserWindow({
    show: false,
    useContentSize: true,
    width: plan.width || 816,
    height: plan.height || 624,
    webPreferences: {
      session: ses,
      preload: path.join(__dirname, "preload.cjs"),
      offscreen: true,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  window.webContents.setAudioMuted(true);
  window.webContents.setFrameRate(60);
  ipcMain.on("plan", (event) => {
    event.returnValue = {
      choices: plan.choices || [],
      allChoices: !!plan.allChoices,
      screens: plan.screens || null,
    };
  });
  ipcMain.handle("size", (_event, width, height) => {
    window.setContentSize(Math.round(width), Math.round(height));
    return true;
  });
  ipcMain.handle("capture", async (_event, name, meta) => {
    const image = await window.webContents.capturePage();
    const file = `${name}.png`;
    fs.writeFileSync(path.join(out, file), image.toPNG());
    result.screens.push({ name, file, ...meta });
    // Each capture is progress for whoever runs the capture.
    process.stdout.write(JSON.stringify({ captured: name, title: meta.title }) + "\n");
    return true;
  });
  ipcMain.on("skip", (_event, screen, reason) => result.skipped.push({ screen, reason }));
  ipcMain.on("error", (_event, message) => {
    if (result.errors.length < 50) result.errors.push(String(message).slice(0, 2000));
  });
  ipcMain.on("done", (_event, game) => {
    result.game = game;
    finish(0);
  });
  window.webContents.on("console-message", (event) => {
    if (event.level === "error" && result.errors.length < 50)
      result.errors.push(`console: ${String(event.message).slice(0, 2000)}`);
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    result.errors.push(`The game stopped: ${details.reason}`);
    finish(1);
  });
  window.webContents.on("did-fail-load", (_event, code, description) => {
    result.errors.push(`The game did not load: ${description} (${code})`);
    finish(1);
  });
  setTimeout(() => {
    result.errors.push(`Capturing took longer than ${plan.timeout || 300} seconds.`);
    finish(1);
  }, (plan.timeout || 300) * 1000);
  window.loadURL("game://game/index.html");
});
