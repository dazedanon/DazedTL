// Installs this checkout the way a user does and drives the running app
// through a Guided journey, so a fresh Windows or Linux machine shows what
// breaks before users do. CI runs it on both systems; see the live test in
// docs/development.md.
//
//   node scripts/e2e.mjs [--work <folder>] [--upgrade-from <tag>]
//
// With --upgrade-from, the release at that tag runs its own journey on the
// same game, then this checkout updates that install the way the app does and
// checks that the project reads right and translates what is left.
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
import { extract } from "./tar.mjs";
import { writeStaged } from "./update.mjs";
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
const upgradeFrom = option("--upgrade-from");
// The journey's install, profile and game: an upgrade's are the previous
// release's, which its own journey leaves in a folder of their own.
const journey = upgradeFrom ? path.join(work, "previous") : work;
// Explorer unpacks a GitHub ZIP into a doubled, numbered folder.
const install = path.join(journey, "DazedTL-main (1)", "DazedTL-main");
const profile = path.join(journey, "プロファイル (テスト)");
const game = path.join(journey, "ゲーム", "魔法少女の冒険 体験版 (1.0)");
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

/** The files Git would commit, which a downloaded ZIP holds. */
function checkoutFiles() {
  return [
    ...new Set(
      execFileSync(
        "git",
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        { cwd: root, encoding: "utf8" },
      )
        .split("\0")
        .filter(Boolean),
    ),
  ].filter((file) => fs.existsSync(path.join(root, file)));
}

/** Copies the files Git would commit, as a downloaded ZIP holds them. */
function copyCheckout() {
  const files = checkoutFiles();
  for (const file of files) {
    const from = path.join(root, file);
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

// A DTextPicture placeholder for the map's name, a HUD label, a CommonPopup
// popup, a MOG_EventIndicators label and a script notice no installed
// handler captures, for Other event text.
const placeholder = "D_TEXT [マップ表示名] 24";
const eventCommands = [
  [356, placeholder],
  [356, "D_TEXT 現在の時刻 24"],
  [356, "CommonPopup add text:共鳴度+3 count:60"],
  [108, "text_indicator : 世界地図の端"],
  [355, "Notice.show('宝箱を見つけた');"],
];

/**
 * Gives a game a menu whose choices show help from event comments, as
 * MPP_ChoiceEX does, which Maps & events translates with Comment text on.
 */
function addChoiceHelp(folder) {
  const file = path.join(folder, "data/Map001.json");
  const map = JSON.parse(fs.readFileSync(file, "utf8"));
  const command = (code, indent, ...parameters) => ({
    code,
    indent,
    parameters,
  });
  const help = (choice, text, help) => [
    command(402, 0, choice, text),
    command(108, 1, "選択肢ヘルプ"),
    command(408, 1, help),
    command(0, 1),
  ];
  map.events.push({
    ...map.events[1],
    id: map.events.length,
    name: "案内",
    x: 10,
    pages: [
      {
        ...map.events[1].pages[0],
        list: [
          command(101, 0, "", 0, 0, 2, ""),
          command(401, 0, "どちらへ行きますか？"),
          command(102, 0, ["森", "村"], -1, 0, 2, 0),
          ...help(0, "森", "魔法の杖を探しに森へ向かいます。"),
          ...help(1, "村", "村に残って準備をします。"),
          command(404, 0),
          command(0, 0),
        ],
      },
    ],
  });
  fs.writeFileSync(file, JSON.stringify(map));
  const plugins = path.join(folder, "js/plugins.js");
  fs.writeFileSync(
    plugins,
    fs
      .readFileSync(plugins, "utf8")
      .replace(
        /\n\];/,
        ',\n{"name":"MPP_ChoiceEX","status":true,"description":"選択肢の機能拡張","parameters":{"Choice Help Commands":"[\\"選択肢ヘルプ\\"]"}}\n];',
      ),
  );
  // The plugin itself only needs to be there, as players have it.
  fs.writeFileSync(
    path.join(folder, "js/plugins/MPP_ChoiceEX.js"),
    "/*:\n * @target MV MZ\n * @plugindesc 選択肢の機能拡張\n * @param Choice Help Commands\n * @type string[]\n */\n",
  );
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
  const file = path.join(game, "data/Map001.json");
  const map = JSON.parse(fs.readFileSync(file, "utf8"));
  const list = map.events[1].pages[0].list;
  list.splice(
    list.findIndex((command) => command.code === 0),
    0,
    ...eventCommands.map(([code, text]) => ({
      code,
      indent: 0,
      parameters: [text],
    })),
  );
  fs.writeFileSync(file, JSON.stringify(map));
  addChoiceHelp(game);
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
    const tools = path.join(journey, "tools");
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
    env.HOME = path.join(journey, "home");
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

  /** Sends a DevTools command; with `timeout`, fails with `late` when the
   * reply takes longer. */
  send(method, params = {}, { timeout = 0, late = "" } = {}) {
    const id = ++this.serial;
    return new Promise((resolve, reject) => {
      const timer =
        timeout &&
        setTimeout(() => {
          this.pending.delete(id);
          reject(new Error(late || `${method} got no reply in time.`));
        }, timeout);
      const settle = (done) => (value) => {
        clearTimeout(timer);
        done(value);
      };
      this.pending.set(id, {
        method,
        resolve: settle(resolve),
        reject: settle(reject),
      });
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
    // A screenshot waits for the window's next frame, which never comes
    // while the window can't paint, such as under a lock screen.
    const { data } = await this.send(
      "Page.captureScreenshot",
      { format: "png" },
      {
        timeout: 30_000,
        late: "The window drew no frame to capture within 30 s, as when a lock screen covers the display; start a virtual compositor with --no-lockscreen.",
      },
    );
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
/** The fixture chief's plugin command, comment and script texts, in order. */
const eventTexts = () =>
  readJson("data/Map001.json")
    .events[1].pages[0].list.filter((command) =>
      [356, 108, 355].includes(command.code),
    )
    .map((command) => command.parameters[0]);

/** Runs a project helper command the way an assistant's shell does. */
const helper = (command, timeout) =>
  windows
    ? execFileSync("powershell", ["-NoProfile", "-Command", command], {
        encoding: "utf8",
        timeout,
      })
    : execFileSync("sh", ["-c", command], { encoding: "utf8", timeout });

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
  : path.join(journey, "home/.local/share/applications/dazedtl.desktop");

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
  // Apply's own follow-up work runs on after the files change, and the app
  // refuses the next action until it ends.
  await until(
    `${task} to finish`,
    async () => !(await page.call("workspace_snapshot")).application.running,
    5 * 60_000,
  );
}

// --------------------------------------------------------------------- main

const failures = [];
const stand_in = await provider();
const port = await freePort();
const inspect = await freePort();
const debug = [`--remote-debugging-port=${port}`, `--inspect=${inspect}`];
let protocol = "";
let page;
// The project helper an assistant's copied task runs, without its command.
let projectHelper = "";

/** Saves and checks a connection to the stand-in provider. */
async function connectStandIn() {
  const saved = await page.call("settings_get");
  // An updated install keeps its earlier stand-in, at an address now gone.
  const earlier = saved.connections.find((item) => item.name === "Stand-in");
  let settings = await page.call("connection_save", {
    revision: saved.revision,
    ...(earlier && { connection_id: earlier.id }),
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
}

/** The journey a new user takes, from a downloaded ZIP to a patch. */
async function liveJourney() {
  await step("Copy the checkout into a downloaded-ZIP folder", () => {
    const count = copyCheckout();
    makeGame();
    // A check that just ran keeps the app from installing a newer public
    // release over the files under test.
    fs.mkdirSync(profile, { recursive: true });
    fs.writeFileSync(
      path.join(profile, "updates.json"),
      JSON.stringify({ checkedAt: new Date().toISOString() }),
    );
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

  await step("Connect the stand-in provider", connectStandIn);

  await step("Translate and apply the database", async () => {
    await page.click("3Translate");
    await translateTask(page, "Database files", () => {
      const [, mika] = readJson("data/Actors.json");
      // A skill's battle message goes out with a note on who learns it, and
      // states name Mika, the party's one actor, in grouped requests.
      const [, fire] = readJson("data/Skills.json");
      const [, sleep, poison] = readJson("data/States.json");
      return (
        translated(mika.name) &&
        translated(fire.message1) &&
        translated(sleep.message1) &&
        translated(poison.message4) &&
        translated(readJson("data/System.json").gameTitle)
      );
    });
  });

  await step("Translate and apply maps and events", () =>
    translateTask(page, "Maps & events", () => {
      const events = readJson("data/Map001.json").events;
      const all = (event, code) =>
        events[event].pages[0].list
          .filter((command) => command.code === code)
          .every((command) => translated(command.parameters[0]));
      // Comment text came on by itself for the menu's choice help.
      return all(1, 401) && all(2, 408);
    }),
  );

  await step("The assistant investigates event text sources", async () => {
    await page.click("2Context");
    await page.click(/^Event text sources/);
    // Copying the task records the same handoff, without the clipboard.
    const { text } = await page.call("guided_skill", {
      project_id: (await page.call("workspace_snapshot")).application.project
        .id,
      name: "advanced",
    });
    const command = /Read this request first: `([^`]+)`/.exec(text)[1];
    // PowerShell's form quotes each argument.
    projectHelper = command.replace(/ '?event-text'?$/, "");
    const { request } = JSON.parse(helper(command));
    const map = Object.keys(request.dependencies).find((name) =>
      name.endsWith("Map001.json"),
    );
    const evidence = [
      { file: map, sha256: request.dependencies[map], location: "event 1" },
    ];
    // The assistant read how each plugin parses its text: DTextPicture joins
    // the words back, CommonPopupCore keeps one argument per space and MOG
    // splits its comment on " : ". The placeholder is an internal value, and
    // the notice needs a pattern of the game's own.
    const findings = {
      CODE355655: {
        custom: [{ name: "notice", regex: String.raw`Notice\.show\('(.*)'\)` }],
      },
      CODE356: {
        spacing: { "D_TEXT ": "space", CommonPopup: "nbsp" },
        keep: [placeholder],
        custom: [],
      },
      CODE108: { spacing: { text_indicator: "space" }, keep: [], custom: [] },
    };
    const sources = Object.fromEntries(
      request.controls.map(({ key }) => [
        key,
        {
          decision: findings[key] ? "enable" : "skip",
          confidence: "high",
          coverage: findings[key] ? "safe" : "none",
          reason: findings[key] ? "Players see this text." : "No text here.",
          targets: key === "CODE122" ? "" : [],
          observations: [],
          exclusions: [],
          evidence,
          ...(key === "CODE357" ? { custom: [] } : {}),
          ...(key in findings ? findings[key] : {}),
        },
      ]),
    );
    fs.writeFileSync(
      path.join(game, ".dazedtl/guided/event-text-findings.json"),
      JSON.stringify({
        version: request.version,
        request_id: request.request_id,
        project_id: request.project_id,
        engine: request.engine,
        fingerprint: request.fingerprint,
        sources,
      }),
    );
    const { findings: applied } = JSON.parse(helper(`${command} --apply`));
    if (applied.enabled.join() !== "CODE355655,CODE356,CODE108")
      throw new Error(`The findings enabled ${applied.enabled.join()}.`);
    await page.click(/^Source choices/);
    await page.click(/^MV plugin commands/);
    const details = `document.querySelector(".translation-source-detail details").open = true`;
    await page.evaluate(details);
    await page.waitText(`Left untranslated: ${placeholder}`);
    await page.shot("event-text-sources");
    await page.click(/^Script text/);
    await page.waitText("1 pattern written for this game.");
    await page.evaluate(details);
    await page.waitText("Custom pattern notice:");
    await page.shot("event-text-custom");
  });

  await step("Translate and apply other event text", async () => {
    // A started stage also reads "In progress" to screen readers.
    await page.click(/^3Translate/);
    await translateTask(page, "Other event text", () => {
      const [kept, label, popup, comment, notice] = eventTexts();
      const nbsp = String.fromCharCode(0xa0);
      // Only the popup's plugin needs its words held together.
      return (
        kept === placeholder &&
        /^D_TEXT Tested \S+ 24$/.test(label) &&
        new RegExp(
          `^CommonPopup add text:Tested${nbsp}\\S+${nbsp}\\+3 count:60$`,
        ).test(popup) &&
        /^text_indicator : Tested \S+$/.test(comment) &&
        /^Notice\.show\('Tested [a-z]+'\);$/.test(notice)
      );
    });
  });

  await step(
    "The assistant's playtest checks the game and says why it can't play it",
    async () => {
      // Check's one task is Text QA, whose assistant plays an MV/MZ game.
      await page.click("4Check");
      await page.waitText(
        "Your assistant plays the game while QA reviews it, and fixes what it finds.",
      );
      // The copied task's first playtest step, as its assistant runs it.
      const status = JSON.parse(
        helper(`${projectHelper} playtest --run --wait 20`, 5 * 60_000),
      );
      if (status.operation?.status !== "complete")
        throw new Error(`The playtest ended ${status.operation?.status}.`);
      // The fixture game has no engine scripts, so the playtest checks its
      // files and reports that it could not play it.
      await page.waitText(
        "The playtest could not play the game. The game folder has no RPG Maker engine scripts to play.",
        2 * 60_000,
      );
      // Its operation ends after the result shows, and the app refuses the
      // next action until it does.
      await until(
        "the playtest to finish",
        async () =>
          !(await page.call("workspace_snapshot")).application.running,
        2 * 60_000,
      );
      await page.shot("playtest");
    },
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

  await step("Build a clean game ZIP of the game alone", async () => {
    const archive = path.join(
      path.dirname(game),
      `${path.basename(game)}-game.zip`,
    );
    // A translator's notes and a browser's spellcheck download sit beside the
    // game's files without being part of it.
    fs.writeFileSync(path.join(game, "notes.txt"), "Check the title screen.");
    fs.mkdirSync(path.join(game, "Dictionaries"));
    fs.writeFileSync(path.join(game, "Dictionaries/en-US-10-1.bdic"), "words");
    await page.click(/^Clean game ZIP/);
    await page.click("Build clean game ZIP");
    await until(
      "the build to finish",
      async () =>
        fs.existsSync(archive) &&
        !(await page.call("workspace_snapshot")).application.running,
      5 * 60_000,
    );
    // Its one top folder is named after the archive, as players unpack it.
    const prefix = `${path.basename(archive, ".zip")}/`;
    const unpacked = [...entries(fs.readFileSync(archive))];
    const outside = unpacked.find((entry) => !entry.path.startsWith(prefix));
    if (outside)
      throw new Error(`The game ZIP holds ${outside.path} outside ${prefix}.`);
    const files = new Map(
      unpacked.map((entry) => [entry.path.slice(prefix.length), entry]),
    );
    const actors = files.get("data/Actors.json");
    if (
      !actors ||
      !translated(JSON.parse(actors.data.toString("utf8"))[1].name)
    )
      throw new Error("The game ZIP lacks the translated database.");
    for (const name of ["index.html", "img/pictures/看板.png"])
      if (!files.has(name)) throw new Error(`The game ZIP lacks ${name}.`);
    for (const name of files.keys())
      if (name === "notes.txt" || name.startsWith("Dictionaries/"))
        throw new Error(`The game ZIP holds ${name}, added while translating.`);
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
}

/**
 * Leaves this checkout for the previous release's launcher as the app leaves
 * a downloaded release: signed, in .runtime/update/next. The install trusts
 * a key made for the test, as it trusts the release keys.
 */
function stageCheckout() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  fs.writeFileSync(
    path.join(install, "release/keys/upgrade-test.pem"),
    publicKey.export({ type: "spki", format: "pem" }),
  );
  const executables = new Set(
    execFileSync("git", ["ls-files", "-s", "-z"], {
      cwd: root,
      encoding: "utf8",
    })
      .split("\0")
      .filter((row) => row.startsWith("100755 "))
      .map((row) => row.split("\t")[1]),
  );
  const names = checkoutFiles().filter(
    (name) => !name.startsWith("release/manifest."),
  );
  const files = new Map(
    names.map((name) => [name, fs.readFileSync(path.join(root, name))]),
  );
  const [current] = JSON.parse(
    fs.readFileSync(path.join(root, "app/package.json"), "utf8"),
  ).version.split("-");
  const version = `${current}-upgrade.1`;
  const manifest = Buffer.from(
    JSON.stringify({
      format: 1,
      version,
      files: Object.fromEntries(
        [...files].map(([name, data]) => [
          name,
          crypto.createHash("sha256").update(data).digest("hex"),
        ]),
      ),
      executables: names.filter((name) => executables.has(name)),
    }),
  );
  files.set("release/manifest.json", manifest);
  files.set(
    "release/manifest.sig",
    Buffer.from(crypto.sign(null, manifest, privateKey).toString("base64")),
  );
  writeStaged(install, files);
  return version;
}

/** Every Database files and Maps & events file's lines, read from the file. */
async function fileLines() {
  const { guided } = await page.call("workspace_snapshot");
  const lines = guided.sourceStatus.lines || {};
  const missing = guided.files.filter((file) => !lines[file.name]);
  if (missing.length)
    throw new Error(
      `No line counts for ${missing.map((file) => file.name).join(", ")}.`,
    );
  return guided.files.map((file) => ({ ...file, ...lines[file.name] }));
}

/** The text of a file's row in the open translation task. */
const fileRow = (name) =>
  page.evaluate(`[...document.querySelectorAll(".translation-file-lines")]
    .map((cell) => cell.parentElement)
    .find((row) => row.getClientRects().length && row.innerText.includes(${JSON.stringify(name)}))
    ?.innerText.replace(/\\s+/g, " ")`);

/**
 * The previous release translates the game with choice help in its own live
 * test; this checkout then updates its install as the app does. The project
 * must read each file's lines from the file, the help included, and finish
 * what is left.
 */
async function upgradeJourney(tag) {
  await step(`${tag} runs its live test on a game with choice help`, () => {
    const previous = path.join(work, "previous-checkout");
    extract(
      execFileSync("git", ["archive", "--format=tar.gz", tag], {
        cwd: root,
        maxBuffer: 1 << 30,
      }),
      previous,
    );
    addChoiceHelp(path.join(previous, "tests/fixtures/mz-game"));
    // Its live test copies the files Git would commit.
    execFileSync("git", ["init", "-q"], { cwd: previous });
    execFileSync("git", ["add", "-A"], { cwd: previous });
    const result = spawnSync(
      process.execPath,
      [path.join(previous, "scripts/e2e.mjs"), "--work", journey],
      { stdio: "inherit" },
    );
    if (result.status !== 0)
      throw new Error(
        `${tag}'s live test failed; its logs are in ${path.join(journey, "logs")}.`,
      );
  });

  const version = await step("Stage this checkout as an update", stageCheckout);

  await step("START applies the update and opens the project", async () => {
    const result = await runStart("start-update", debug, 15 * 60_000);
    if (result.code !== 0) throw startFailed(result);
    const installed = JSON.parse(
      fs.readFileSync(path.join(install, "release/manifest.json"), "utf8"),
    ).version;
    if (installed !== version)
      throw new Error(`START left ${installed} installed, not ${version}.`);
    protocol = JSON.parse(
      fs.readFileSync(
        path.join(install, "backend/dazedtl/api/protocol.json"),
        "utf8",
      ),
    ).version;
    page = await Page.connect(port);
    await page.waitText(path.basename(game));
    await page.shot("updated");
  });

  await step("Each file reads its lines from the file", async () => {
    const map = (await fileLines()).find((file) => file.name === "Map001.json");
    // Four messages, four choices, the map's name and two choices' help.
    if (map.lines !== 11)
      throw new Error(`Map001.json counts ${map.lines} lines, not 11.`);
  });

  await step("Translate finishes what is left", async () => {
    const left = (await fileLines()).filter(
      (file) => file.translated < file.lines,
    );
    if (!left.length) return;
    await connectStandIn();
    // A restarted app opens on the project's overview.
    await page.click("Translation");
    // The stage tab also names its state, such as "Completed".
    await page.click(/^3\s*Translate/);
    for (const [group, task] of [
      ["database", "Database files"],
      ["dialogue", "Maps & events"],
    ])
      if (left.some((file) => file.group === group))
        await translateTask(page, task, async () =>
          (await fileLines()).every(
            (file) => file.group !== group || file.translated === file.lines,
          ),
        );
  });

  await step("The project reads translated and applied", async () => {
    const files = await fileLines();
    const total = files.reduce((sum, file) => sum + file.lines, 0);
    const done = files.reduce((sum, file) => sum + file.translated, 0);
    if (done !== total)
      throw new Error(`${done} of ${total} lines read translated.`);
    await page.click("Translation");
    // The stage tab also names its state, such as "Completed".
    await page.click(/^3\s*Translate/);
    await page.click("Maps & events");
    const row = await until("Map001.json's row", () => fileRow("Map001.json"));
    if (!/11 \/ 11 Applied/.test(row))
      throw new Error(`Map001.json reads "${row}".`);
    await page.click("Project");
    await page.waitText(
      `${total.toLocaleString("en-US")} / ${total.toLocaleString("en-US")}`,
    );
    await page.shot("project");
    page.close();
    page = undefined;
    await closeApp();
    diagnostics();
  });
}
try {
  await (upgradeFrom ? upgradeJourney(upgradeFrom) : liveJourney());
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
    // The text first: a window that draws no frames still answers it.
    if (page)
      fs.writeFileSync(path.join(logs, "window.txt"), await page.text());
    await page?.shot("failure");
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
