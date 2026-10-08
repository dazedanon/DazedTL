// Installs this checkout the way a user does and drives the running app
// through a Guided journey, so a fresh Windows or Linux machine shows what
// breaks before users do. CI runs it on both systems; see the live test in
// docs/development.md.
//
//   node scripts/e2e.mjs [--work <folder>]
//
// The install, profile and game sit in folders with spaces and Japanese
// names, START runs with the PATH of a machine without Node, Python or (on
// Windows) Git, and translation uses a local stand-in for an OpenAI-compatible
// provider. Logs, screenshots and diagnostics land in <work>/logs.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import net from "node:net";
import crypto from "node:crypto";
import { spawn, spawnSync, execFileSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { root } from "./dependencies.mjs";
import { entries } from "./zip.mjs";

const windows = process.platform === "win32";
const option = (name) => {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
};
const work = path.resolve(
  option("--work") || fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-e2e-")),
);
fs.mkdirSync(work, { recursive: true });
if (fs.readdirSync(work).length)
  throw new Error(`Choose an empty work folder; ${work} has files.`);
// Explorer unpacks a GitHub ZIP into a doubled, numbered folder.
const install = path.join(work, "DazedTL-main (1)", "DazedTL-main");
const profile = path.join(work, "プロファイル (テスト)");
const game = path.join(work, "ゲーム", "魔法少女の冒険 体験版 (1.0)");
const logs = path.join(work, "logs");
const shots = path.join(logs, "screenshots");
fs.mkdirSync(shots, { recursive: true });

// ---------------------------------------------------------------- reporting

const steps = [];
let current;
async function step(name, run) {
  const started = Date.now();
  current = name;
  console.log(`\n▶ ${name}`);
  try {
    const value = await run();
    steps.push({ name, ok: true, seconds: (Date.now() - started) / 1000 });
    return value;
  } catch (error) {
    steps.push({ name, ok: false, seconds: (Date.now() - started) / 1000 });
    throw error;
  }
}

const message = (error) =>
  error instanceof Error ? error.message : String(error);

/** Polls `check` until it returns a truthy value. */
async function until(description, check, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  let last;
  for (;;) {
    try {
      const value = await check();
      if (value) return value;
    } catch (error) {
      last = error;
    }
    if (Date.now() > deadline)
      throw new Error(
        `Timed out after ${timeout / 1000}s waiting for ${description}.` +
          (last ? ` Last error: ${message(last)}` : ""),
      );
    await delay(250);
  }
}

// ------------------------------------------------------------------ install

/** Copies the files Git would commit, as a downloaded ZIP holds them. */
function copyCheckout() {
  const files = execFileSync(
    "git",
    ["ls-files", "-z", "--cached", "--others", "--exclude-standard"],
    { cwd: root, encoding: "utf8" },
  )
    .split("\0")
    .filter(Boolean);
  for (const file of new Set(files)) {
    const from = path.join(root, file);
    if (!fs.existsSync(from)) continue;
    const to = path.join(install, file);
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(from, to);
    fs.chmodSync(to, fs.statSync(from).mode);
    // Explorer marks every file it unpacks from a downloaded ZIP.
    if (windows)
      fs.writeFileSync(
        `${to}:Zone.Identifier`,
        "[ZoneTransfer]\r\nZoneId=3\r\n",
      );
  }
  return files.length;
}

/** Copies the MZ fixture game into a folder named like a Japanese release. */
function makeGame() {
  fs.cpSync(path.join(root, "tests/fixtures/mz-game"), game, {
    recursive: true,
  });
  // A Japanese file name, which Git, applying and ZIPs must keep intact.
  fs.renameSync(
    path.join(game, "img/pictures/sign.png"),
    path.join(game, "img/pictures/看板.png"),
  );
}

// ----------------------------------------------------------------- provider

/** The balanced JSON objects in `text`, outermost first. */
function* objects(text) {
  for (
    let start = text.indexOf("{");
    start >= 0;
    start = text.indexOf("{", start + 1)
  ) {
    let depth = 0;
    let quoted = false;
    for (let i = start; i < text.length; i++) {
      const character = text[i];
      if (quoted) {
        if (character === "\\") i++;
        else if (character === '"') quoted = false;
      } else if (character === '"') quoted = true;
      else if (character === "{") depth++;
      else if (character === "}" && --depth === 0) {
        try {
          yield JSON.parse(text.slice(start, i + 1));
        } catch {
          // Not JSON; keep scanning.
        }
        break;
      }
    }
  }
}

const japanese = /[\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uff00-\uffef]/g;
/**
 * Answers like a model that translates every line: Japanese becomes a marker
 * unique to the line, while speaker prefixes, placeholders and numbers stay.
 */
function translate(value) {
  const text = String(value);
  const speaker = /^(\[[^\n]*?\]:\s*)([\s\S]*)$/.exec(text);
  const [prefix, body] = speaker ? [speaker[1], speaker[2]] : ["", text];
  const kept = body.replace(japanese, " ").replace(/\s+/g, " ").trim();
  const marker = crypto
    .createHash("sha256")
    .update(text)
    .digest("hex")
    .slice(0, 8)
    .replace(/\d/g, (digit) => "ghijklmnop"[Number(digit)]);
  return `${prefix}Tested ${marker}${kept ? ` ${kept}` : ""}`;
}

/** A local OpenAI-compatible chat completions server. */
async function provider() {
  const record = fs.createWriteStream(path.join(logs, "provider.jsonl"));
  const server = http.createServer((request, response) => {
    let body = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => (body += chunk));
    request.on("end", () => {
      const reply = (status, value) => {
        record.write(
          JSON.stringify({
            time: new Date().toISOString(),
            method: request.method,
            url: request.url,
            status,
          }) + "\n",
        );
        response.writeHead(status, { "Content-Type": "application/json" });
        response.end(JSON.stringify(value));
      };
      if (request.method === "GET" && request.url?.endsWith("/models"))
        return reply(200, {
          object: "list",
          data: [{ id: "e2e-model", object: "model" }],
        });
      if (
        request.method !== "POST" ||
        !request.url?.endsWith("/chat/completions")
      )
        return reply(404, { error: { message: "Not found" } });
      let lines;
      try {
        const params = JSON.parse(body);
        const last = params.messages.at(-1).content;
        const text = Array.isArray(last)
          ? last.map((part) => part.text || "").join("\n")
          : String(last);
        lines = [...objects(text)].find(
          (value) =>
            value &&
            typeof value === "object" &&
            Object.keys(value).length &&
            Object.keys(value).every((key) => /^Line\d+$/.test(key)),
        );
      } catch {
        lines = undefined;
      }
      if (!lines)
        return reply(400, {
          error: { message: "The request carried no LineN payload." },
        });
      const content = JSON.stringify({
        translations: Object.values(lines).map(translate),
      });
      reply(200, {
        id: `chatcmpl-${crypto.randomUUID()}`,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: "e2e-model",
        choices: [
          {
            index: 0,
            message: { role: "assistant", content },
            finish_reason: "stop",
          },
        ],
        usage: {
          prompt_tokens: body.length,
          completion_tokens: content.length,
          total_tokens: body.length + content.length,
        },
      });
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = /** @type {net.AddressInfo} */ (server.address());
  return { server, record, url: `http://127.0.0.1:${port}/v1` };
}

// ------------------------------------------------------------------- launch

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = /** @type {net.AddressInfo} */ (server.address());
  await new Promise((resolve) => server.close(resolve));
  return port;
}

/**
 * The environment START sees on a machine that has none of the developer
 * tools: no Node or Python, and on Windows no Git either.
 */
function userEnvironment() {
  const env = { ...process.env, DAZEDTL_PROFILE: profile };
  for (const name of Object.keys(env))
    if (
      /^(npm_|NODE_|PYTHON|VIRTUAL_ENV|CONDA|ELECTRON_)/i.test(name) ||
      name.toUpperCase() === "PATH"
    )
      delete env[name];
  if (windows) {
    // PSModulePath stays: under CI it is PowerShell 7's, as when a user starts
    // START from a PowerShell 7 terminal.
    const system = process.env.SystemRoot || "C:\\Windows";
    env.Path = [
      `${system}\\system32`,
      system,
      `${system}\\System32\\Wbem`,
      `${system}\\System32\\WindowsPowerShell\\v1.0\\`,
      `${system}\\System32\\OpenSSH\\`,
      // Holds the Microsoft Store's python.exe stand-in on a fresh Windows.
      path.join(process.env.LOCALAPPDATA || "", "Microsoft\\WindowsApps"),
    ].join(";");
  } else {
    // A folder of links to the system's tools minus Node and Python, since
    // dropping whole folders would take Git and the shell with them.
    const tools = path.join(work, "tools");
    if (!fs.existsSync(tools)) {
      fs.mkdirSync(tools);
      for (const folder of (process.env.PATH || "/usr/bin:/bin").split(":"))
        for (const name of fs.existsSync(folder) ? fs.readdirSync(folder) : [])
          if (
            !/^(node|npm|npx|corepack|python[\d.]*|pip[\d.]*)$/.test(name) &&
            !fs.lstatSync(path.join(tools, name), { throwIfNoEntry: false })
          )
            fs.symlinkSync(path.join(folder, name), path.join(tools, name));
    }
    env.PATH = tools;
    // Shortcuts and caches stay inside the work folder.
    env.HOME = path.join(work, "home");
    for (const name of [
      "XDG_CONFIG_HOME",
      "XDG_DATA_HOME",
      "XDG_CACHE_HOME",
      "XDG_STATE_HOME",
    ])
      delete env[name];
    fs.mkdirSync(env.HOME, { recursive: true });
  }
  return env;
}

const startFailed = ({ code, output }) =>
  new Error(
    `START exited with ${code}:\n${output.trim().split(/\r?\n/).slice(-20).join("\n")}`,
  );

/** Runs START as a user's double-click does and waits for it to finish. */
async function runStart(label, args, timeout) {
  const log = fs.createWriteStream(path.join(logs, `${label}.log`));
  const child = windows
    ? spawn(
        process.env.ComSpec || "cmd.exe",
        [
          "/d",
          "/s",
          "/c",
          `""${path.join(install, "START.bat")}" ${args.join(" ")}"`,
        ],
        {
          cwd: path.dirname(install),
          env: userEnvironment(),
          windowsVerbatimArguments: true,
          stdio: ["ignore", "pipe", "pipe"],
        },
      )
    : spawn("bash", [path.join(install, "START.sh"), ...args], {
        cwd: path.dirname(install),
        env: userEnvironment(),
        stdio: ["ignore", "pipe", "pipe"],
      });
  let output = "";
  for (const stream of [child.stdout, child.stderr])
    stream.on("data", (chunk) => {
      output += chunk;
      log.write(chunk);
      process.stdout.write(chunk);
    });
  const started = Date.now();
  const code = await new Promise((resolve) => {
    const timer = setTimeout(() => {
      killTree(child.pid);
      resolve("timeout");
    }, timeout);
    child.on("error", (error) => {
      clearTimeout(timer);
      output += String(error);
      resolve("error");
    });
    child.on("exit", (value) => {
      clearTimeout(timer);
      resolve(value);
    });
  });
  log.end();
  return { code, output, seconds: (Date.now() - started) / 1000 };
}

function killTree(pid) {
  if (!pid) return;
  if (windows)
    spawnSync("taskkill", ["/F", "/T", "/PID", String(pid)], {
      stdio: "ignore",
    });
  else
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // Already gone.
    }
}

/**
 * Runs Windows PowerShell for the test itself. A PowerShell 7 parent's module
 * path stops it from loading modules such as CimCmdlets, so it gets its own.
 */
function powershell(command) {
  const env = { ...process.env };
  delete env.PSModulePath;
  return execFileSync(
    "powershell.exe",
    ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
    { encoding: "utf8", env, windowsHide: true },
  );
}

/** Processes whose executable lives in the install, such as Electron and Python. */
function appProcesses() {
  const inside = (file) =>
    !!file &&
    (windows ? file.toLowerCase() : file).startsWith(
      (windows ? install.toLowerCase() : install) + path.sep,
    );
  if (windows) {
    const output = powershell(
      "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-CimInstance Win32_Process | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress",
    );
    return JSON.parse(output || "[]")
      .filter((item) => inside(item.ExecutablePath))
      .map((item) => ({
        pid: item.ProcessId,
        file: item.ExecutablePath,
        command: item.CommandLine || "",
      }));
  }
  const found = [];
  for (const name of fs.readdirSync("/proc")) {
    if (!/^\d+$/.test(name)) continue;
    try {
      const file = fs.readlinkSync(`/proc/${name}/exe`);
      if (inside(file))
        found.push({
          pid: Number(name),
          file,
          command: fs
            .readFileSync(`/proc/${name}/cmdline`, "utf8")
            .replaceAll("\0", " "),
        });
    } catch {
      // Exited, or another user's process.
    }
  }
  return found;
}

const isMain = (item) =>
  /^electron(\.exe)?$/i.test(path.basename(item.file)) &&
  !item.command.includes("--type=");

/** Closes the window the way its close button does and waits for every process to end. */
async function closeApp() {
  const main = appProcesses().find(isMain);
  if (!main) throw new Error("The app is not running.");
  if (windows) {
    const closed = powershell(
      `(Get-Process -Id ${main.pid}).CloseMainWindow()`,
    );
    if (closed.trim() !== "True")
      throw new Error("The window did not accept the close request.");
  } else process.kill(main.pid, "SIGTERM");
  try {
    await until(
      "every app process to exit",
      () => appProcesses().length === 0,
      45_000,
    );
  } catch (error) {
    const left = appProcesses();
    for (const item of left) killTree(item.pid);
    throw new Error(
      `${message(error)}\nStill running:\n${left.map((item) => `  ${item.pid} ${item.command}`).join("\n")}`,
    );
  }
}

// ---------------------------------------------------------------------- CDP

class Page {
  /** Connects to the window, or with `node`, to Electron's main process. */
  static async connect(port, node = false) {
    const target = await until(
      "DazedTL to accept DevTools connections",
      async () => {
        const targets = await (
          await fetch(`http://127.0.0.1:${port}/json/list`)
        ).json();
        return targets.find((item) =>
          node
            ? item.type === "node"
            : item.type === "page" && item.url.endsWith("/app/dist/index.html"),
        );
      },
      60_000,
    );
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener(
        "error",
        () => reject(new Error("DevTools connection failed.")),
        { once: true },
      );
    });
    return new Page(socket);
  }

  constructor(socket) {
    this.socket = socket;
    this.serial = 0;
    this.pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      const task = this.pending.get(message.id);
      if (!task) return;
      this.pending.delete(message.id);
      if (message.error)
        task.reject(new Error(`${task.method}: ${message.error.message}`));
      else task.resolve(message.result);
    });
    socket.addEventListener("close", () => {
      for (const task of this.pending.values())
        task.reject(new Error("The window closed."));
      this.pending.clear();
    });
  }

  send(method, params = {}) {
    const id = ++this.serial;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { method, resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const { result, exceptionDetails } = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (exceptionDetails)
      throw new Error(
        exceptionDetails.exception?.description || exceptionDetails.text,
      );
    return result.value;
  }

  async shot(name) {
    const { data } = await this.send("Page.captureScreenshot", {
      format: "png",
    });
    fs.writeFileSync(
      path.join(shots, `${String(steps.length).padStart(2, "0")}-${name}.png`),
      Buffer.from(data, "base64"),
    );
  }

  /** Calls the backend through the window, as the interface does. */
  async call(method, params = {}) {
    const reply = await this.evaluate(
      `window.dazedtl.call(${JSON.stringify(protocol)}, ${JSON.stringify(method)}, ${JSON.stringify(params)})`,
    );
    if (!reply.ok) throw new Error(`${method}: ${reply.error.message}`);
    return reply.value;
  }

  text() {
    return this.evaluate("document.body.innerText");
  }

  waitText(text, timeout = 60_000) {
    return until(
      `"${text}" to show`,
      async () => (await this.text()).includes(text),
      timeout,
    );
  }

  /**
   * Clicks the enabled control whose accessible name matches, with mouse input
   * at its center, so a covered or disabled control fails as it would for a user.
   * @param {string | RegExp} name
   */
  async click(name, timeout = 60_000) {
    const pattern =
      typeof name === "string"
        ? `^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`
        : name.source;
    const at = await until(
      `an enabled "${name}" control`,
      () =>
        this.evaluate(`(() => {
          const pattern = new RegExp(${JSON.stringify(pattern)});
          const label = (element) =>
            (element.getAttribute("aria-label") || element.textContent).replace(/\\s+/g, " ").trim();
          const found = [
            ...document.querySelectorAll("button, a, label, [role=button], [role=tab], [role=radio], [role=option]"),
          ].find(
            (element) =>
              element.getClientRects().length &&
              pattern.test(label(element)) &&
              !element.disabled &&
              element.getAttribute("aria-disabled") !== "true",
          );
          if (!found) return null;
          found.scrollIntoView({ block: "center" });
          const box = found.getBoundingClientRect();
          const x = box.x + box.width / 2;
          const y = box.y + box.height / 2;
          const top = document.elementFromPoint(x, y);
          return top && (top === found || found.contains(top)) ? { x, y } : null;
        })()`),
      timeout,
    );
    for (const type of ["mousePressed", "mouseReleased"])
      await this.send("Input.dispatchMouseEvent", {
        type,
        x: at.x,
        y: at.y,
        button: "left",
        clickCount: 1,
      });
  }

  /** Types into a field as keyboard input. */
  async type(selector, text) {
    await until(`${selector} to show`, () =>
      this.evaluate(
        `!!document.querySelector(${JSON.stringify(selector)})?.getClientRects().length`,
      ),
    );
    await this.evaluate(
      `document.querySelector(${JSON.stringify(selector)}).focus()`,
    );
    await this.send("Input.insertText", { text });
  }

  close() {
    this.socket.close();
  }
}

// ------------------------------------------------------------------- checks

const readJson = (file) =>
  JSON.parse(fs.readFileSync(path.join(game, file), "utf8"));
const translated = (value) =>
  typeof value === "string" && value.startsWith("Tested ");

/** Failures the app recorded for Copy diagnostics; a clean run records none. */
function diagnostics() {
  const folder = path.join(profile, "diagnostics");
  const records = [];
  for (const name of fs.existsSync(folder) ? fs.readdirSync(folder) : [])
    if (name.endsWith(".jsonl"))
      for (const line of fs
        .readFileSync(path.join(folder, name), "utf8")
        .split("\n"))
        if (line.trim()) records.push(`${name}: ${line}`);
  if (records.length)
    throw new Error(`The app recorded failures:\n${records.join("\n")}`);
}

/** The menu shortcut setup adds for a downloaded install. */
const shortcut = windows
  ? path.join(
      process.env.APPDATA || "",
      "Microsoft/Windows/Start Menu/Programs/DazedTL.lnk",
    )
  : path.join(work, "home/.local/share/applications/dazedtl.desktop");

/** Runs one Guided translation task: estimate, approve, wait for the run, apply. */
async function translateTask(page, task, check) {
  await page.click(task);
  await page.click("Live");
  await page.click("Translate");
  await page.click("Start Live translation", 5 * 60_000);
  await page.waitText("Run finished.", 5 * 60_000);
  await page.shot(`${task.toLowerCase().replace(/\W+/g, "-")}-translated`);
  // Another task's apply must not confirm this one's.
  if ((await page.text()).includes("Saved translations applied."))
    throw new Error(`${task} reports applied translations before applying.`);
  await page.click(/^Apply \(\d+\)$/);
  await page.click("Apply reviewed files");
  await page.waitText("Saved translations applied.");
  await until(`${task} to reach the game files`, check);
}

// --------------------------------------------------------------------- main

const failures = [];
const stand_in = await provider();
const port = await freePort();
const inspect = await freePort();
const debug = [`--remote-debugging-port=${port}`, `--inspect=${inspect}`];
let protocol = "";
let page;

try {
  await step("Copy the checkout into a downloaded-ZIP folder", () => {
    const count = copyCheckout();
    makeGame();
    protocol = JSON.parse(
      fs.readFileSync(
        path.join(install, "backend/dazedtl/api/protocol.json"),
        "utf8",
      ),
    ).version;
    console.log(`${count} files in ${install}`);
  });

  await step("First START installs and opens the app", async () => {
    let result = await runStart("start-1", debug, 15 * 60_000);
    const fix = /^\s*(sudo install .+apparmor_parser .+)$/m.exec(
      result.output,
    )?.[1];
    if (result.code !== 0 && fix && process.env.CI) {
      // Ubuntu runners restrict the browser sandbox; apply the printed fix
      // the way a user would, then start again.
      console.log(`Applying the AppArmor fix START printed:\n${fix}`);
      execFileSync("sh", ["-c", fix], { stdio: "inherit" });
      result = await runStart("start-1b", debug, 10 * 60_000);
    }
    if (result.code !== 0) throw startFailed(result);
    if (!fs.existsSync(shortcut))
      throw new Error(`Setup added no shortcut at ${shortcut}.`);
    if (
      windows &&
      fs.existsSync(`${path.join(install, "START.bat")}:Zone.Identifier`)
    )
      throw new Error("START.bat still carries its downloaded-file mark.");
  });

  page = await step("The window shows the interface", async () => {
    const connected = await Page.connect(port);
    await connected.waitText("App ready");
    await connected.shot("ready");
    return connected;
  });

  await step("Open a game and choose Guided steps", async () => {
    // The folder dialog is native, so it answers with the game folder the way
    // a user's choice would.
    const main = await Page.connect(inspect, true);
    await main.evaluate(
      `process.mainModule.require("electron").dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [${JSON.stringify(game)}] })`,
    );
    main.close();
    await page.click("Open a game");
    await page.click("Start with Guided steps");
    await page.waitText("Set up this game");
  });

  await step("Set up backs up the game and saves its version", async () => {
    await page.type("#guided-version", "1.0");
    await page.click("This game is untranslated");
    await page.click("Set up this game");
    await page.waitText("Setup complete.", 5 * 60_000);
    await page.shot("set-up");
  });

  await step("Connect the stand-in provider", async () => {
    let settings = await page.call("connection_save", {
      revision: (await page.call("settings_get")).revision,
      provider: "custom",
      name: "Stand-in",
      secret: "e2e-test-key",
      endpoint: stand_in.url,
      protocol: "openai",
    });
    const connection = settings.activeConnectionId;
    settings = await page.call("settings_save", {
      revision: settings.revision,
      connection_id: connection,
      values: { language: "English", model: "e2e-model" },
      model_options: {
        "e2e-model": {
          entriesPerRequest: null,
          pricing: "custom",
          inputRate: 0,
          outputRate: 0,
        },
      },
    });
    settings = await page.call("connection_check", {
      revision: settings.revision,
      connection_id: connection,
    });
    const check = settings.connections.find(
      (item) => item.id === connection,
    ).check;
    if (check.status !== "reachable")
      throw new Error(`Connection check: ${check.message}`);
  });

  await step("Translate and apply the database", async () => {
    await page.click("3Translate");
    await translateTask(page, "Database files", () => {
      const [, mika] = readJson("data/Actors.json");
      return (
        translated(mika.name) &&
        translated(readJson("data/System.json").gameTitle)
      );
    });
  });

  await step("Translate and apply maps and events", () =>
    translateTask(page, "Maps & events", () =>
      readJson("data/Map001.json")
        .events[1].pages[0].list.filter((command) => command.code === 401)
        .every((command) => translated(command.parameters[0])),
    ),
  );

  await step("Build a patch ZIP", async () => {
    const archive = path.join(
      path.dirname(game),
      `${path.basename(game)}-patch.zip`,
    );
    await page.click("5Release");
    await page.click(/^Patch ZIP/);
    await page.click("Review & build patch ZIP");
    await page.click("Build patch ZIP");
    await until(
      "the build to finish",
      async () => !(await page.call("workspace_snapshot")).application.running,
      5 * 60_000,
    );
    const actors = [...entries(fs.readFileSync(archive))].find(
      (entry) => entry.path === "data/Actors.json",
    );
    if (
      !actors ||
      !translated(JSON.parse(actors.data.toString("utf8"))[1].name)
    )
      throw new Error("The patch ZIP lacks the translated database.");
    await page.shot("released");
    for (const file of fs.readdirSync(path.join(game, "data")))
      if (fs.readFileSync(path.join(game, "data", file)).includes("\r"))
        throw new Error(`data/${file} gained Windows line endings.`);
  });

  await step(
    "Closing ends every app process without recorded failures",
    async () => {
      page.close();
      page = undefined;
      await closeApp();
      diagnostics();
      const requests = fs
        .readFileSync(path.join(logs, "provider.jsonl"), "utf8")
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line));
      const refused = requests.filter((item) => item.status !== 200);
      if (refused.length)
        throw new Error(
          `The stand-in provider refused ${refused.length} requests.`,
        );
    },
  );

  await step("Second START opens the same project without setup", async () => {
    const result = await runStart("start-2", debug, 5 * 60_000);
    if (result.code !== 0) throw startFailed(result);
    const repeated = /^(Downloading|Installing|Creating|Building).*$/m.exec(
      result.output,
    );
    if (repeated) throw new Error(`START repeated setup: ${repeated[0]}`);
    page = await Page.connect(port);
    await page.waitText(path.basename(game));
    await page.shot("restarted");
    page.close();
    page = undefined;
    await closeApp();
    diagnostics();
  });
} catch (error) {
  failures.push(`${current}: ${message(error)}`);
  // Annotations show on the run page without signing in, unlike logs.
  if (process.env.GITHUB_ACTIONS) {
    const escape = (value) =>
      value.replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
    const title = escape(current).replace(/:/g, "%3A").replace(/,/g, "%2C");
    console.log(`::error title=${title}::${escape(message(error))}`);
  }
  console.error(
    `\n✖ ${current}\n${(error instanceof Error && error.stack) || message(error)}`,
  );
  try {
    await page?.shot("failure");
    fs.writeFileSync(path.join(logs, "window.txt"), await page.text());
  } catch {
    // The window may already be gone.
  }
} finally {
  page?.close();
  for (const item of appProcesses()) killTree(item.pid);
  stand_in.server.close();
  stand_in.record.end();
  // Electron's output from the detached launch, and the app's own records.
  const hash = crypto
    .createHash("sha256")
    .update(install)
    .digest("hex")
    .slice(0, 12);
  const electronLog = path.join(os.tmpdir(), `dazedtl-${hash}.log`);
  if (fs.existsSync(electronLog))
    fs.copyFileSync(electronLog, path.join(logs, "electron.log"));
  const records = path.join(profile, "diagnostics");
  if (fs.existsSync(records))
    fs.cpSync(records, path.join(logs, "diagnostics"), { recursive: true });
  const summary = steps
    .map(
      (item) =>
        `${item.ok ? "✔" : "✖"} ${item.name} (${item.seconds.toFixed(1)}s)`,
    )
    .join("\n");
  console.log(`\n${summary}\nLogs: ${logs}`);
  if (process.env.GITHUB_STEP_SUMMARY)
    fs.appendFileSync(
      process.env.GITHUB_STEP_SUMMARY,
      `### Live test on ${process.platform}\n\n| Step | Result | Time |\n| --- | --- | --- |\n` +
        steps
          .map(
            (item) =>
              `| ${item.name} | ${item.ok ? "passed" : "**failed**"} | ${item.seconds.toFixed(1)}s |`,
          )
          .join("\n") +
        (failures.length
          ? `\n\n\`\`\`\n${failures.join("\n\n")}\n\`\`\`\n`
          : "\n"),
    );
  process.exitCode = failures.length ? 1 : 0;
}
