const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  shell,
  clipboard,
} = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const { Backend } = require("./backend.cjs");
const { Diagnostics } = require("./diagnostics.cjs");

app.setName("DazedTLNext");
if (process.env.DAZEDTL_NEXT_PROFILE)
  app.setPath("userData", path.resolve(process.env.DAZEDTL_NEXT_PROFILE));
const protocol = require("../../backend/dazedtl/api/protocol.json");
const methods = new Set(Object.keys(protocol.methods));
const outputs = new Set();
const backupFolders = new Set();
let window,
  backend,
  diagnostics,
  closing = false,
  quit = false,
  currentSource = "",
  ready = false,
  closeTimer,
  closeSerial = 0,
  closeToken = 0;
function trusted(event) {
  if (
    event.sender !== window?.webContents ||
    event.senderFrame !== window.webContents.mainFrame
  )
    throw new Error("Untrusted application request.");
}
async function finishClose() {
  if (quit) return;
  quit = true;
  closeToken = 0;
  clearTimeout(closeTimer);
  window?.hide();
  if (backend) await backend.close();
  app.exit(0);
}
async function closeProblem(message, token) {
  if (!closing || token !== closeToken) return;
  clearTimeout(closeTimer);
  const choice = await dialog.showMessageBox(window, {
    type: "warning",
    message: "Some changes have not been saved.",
    detail: message,
    buttons: ["Keep working", "Discard and close"],
    defaultId: 0,
    cancelId: 0,
  });
  if (!closing || token !== closeToken) return;
  if (choice.response === 1) await finishClose();
  else {
    closing = false;
    closeToken = 0;
    window.webContents.send("dazedtl:close-cancelled", token);
  }
}
if (!app.requestSingleInstanceLock()) app.exit(0);
app.on("second-instance", () => {
  window?.show();
  window?.focus();
});
app.on("before-quit", (event) => {
  if (!quit) {
    event.preventDefault();
    window?.close();
  }
});
app.whenReady().then(() => {
  const root = path.resolve(__dirname, "../..");
  diagnostics = new Diagnostics(
    path.join(app.getPath("userData"), "diagnostics"),
    {
      app: app.getVersion(),
      electron: process.versions.electron,
      node: process.versions.node,
      platform: process.platform,
      architecture: process.arch,
      protocol: protocol.version,
      expectedPython: fs
        .readFileSync(path.join(root, ".python-version"), "utf8")
        .trim(),
    },
    root,
  );
  diagnostics.record("desktop.started");
  window = new BrowserWindow({
    show: false,
    width: 1280,
    height: 880,
    minWidth: 900,
    minHeight: 650,
    title: "DazedTL",
    backgroundColor: "#171a20",
    icon: path.join(root, "resources/icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  window.once("ready-to-show", () => {
    window.maximize();
    window.show();
  });
  backend = new Backend(
    root,
    app.getPath("userData"),
    (message) => window?.webContents.send("dazedtl:stopped", message),
    diagnostics,
  );
  window.webContents.on("render-process-gone", (_event, details) =>
    diagnostics.record("renderer.gone", {
      reason: details.reason,
      exitCode: details.exitCode,
    }),
  );
  window.webContents.on(
    "did-fail-load",
    (_event, errorCode, _description, _url, mainFrame) => {
      if (mainFrame) diagnostics.record("renderer.load-failed", { errorCode });
    },
  );
  window.setMenuBarVisibility(false);
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler(
    (_web, _permission, callback) => callback(false),
  );
  window.on("close", (event) => {
    if (quit) return;
    event.preventDefault();
    if (closing) return;
    closing = true;
    const token = (closeToken = ++closeSerial);
    if (!ready) return void finishClose();
    closeTimer = setTimeout(
      () =>
        closeProblem("Saving is taking longer than expected.", token).catch(
          () => {
            if (token !== closeToken) return;
            closing = false;
            closeToken = 0;
            window.webContents.send("dazedtl:close-cancelled", token);
          },
        ),
      10000,
    );
    window.webContents.send("dazedtl:closing", token);
  });
  ipcMain.handle("dazedtl:ready", (event) => {
    trusted(event);
    ready = true;
  });
  ipcMain.handle("dazedtl:copy-text", (event, text) => {
    trusted(event);
    if (typeof text !== "string" || Buffer.byteLength(text, "utf8") > 2_000_000)
      throw new Error("Choose a bounded text artifact to copy.");
    clipboard.writeText(text);
  });
  ipcMain.handle("dazedtl:copy-diagnostics", (event) => {
    trusted(event);
    try {
      clipboard.writeText(diagnostics.report());
    } catch (error) {
      diagnostics.failure("desktop.error", error, { operation: "native" });
      throw new Error("Diagnostics could not be copied. Try again.");
    }
  });
  ipcMain.handle("dazedtl:call", async (event, version, method, params) => {
    trusted(event);
    try {
      if (version !== protocol.version)
        throw Object.assign(
          new Error(
            "The application and backend versions do not match. Restart after updating.",
          ),
          { code: "protocol" },
        );
      if (!methods.has(method))
        throw Object.assign(new Error("Unknown application operation."), {
          code: "validation",
        });
      if (closing && !protocol.methods[method].duringClose)
        throw Object.assign(new Error("The app is saving before closing."), {
          code: "validation",
        });
      const result = await backend.request(method, params);
      const selected =
        method === "workspace_snapshot"
          ? result?.application?.project
          : result?.project;
      if (selected?.source) currentSource = selected.source;
      if (method === "guided_export") outputs.add(result.path);
      if (method === "workspace_snapshot") {
        backupFolders.clear();
        for (const key of ["source_backup", "prepared_source", "workspace_backup"]) {
          const backup = result?.translation?.lifecycle?.[key];
          if (backup?.available === true && typeof backup.path === "string")
            backupFolders.add(backup.path);
        }
        for (const artifact of result?.guided?.artifacts || []) {
          if (artifact.available === true && typeof artifact.folder === "string")
            outputs.add(artifact.folder);
        }
      }
      for (const job of result?.translation?.jobs || []) {
        if (
          job.kind === "operation" &&
          job.status === "complete" &&
          typeof job.result?.path === "string"
        )
          outputs.add(path.dirname(job.result.path));
      }
      return { version: protocol.version, ok: true, value: result };
    } catch (error) {
      diagnostics.failure("desktop.error", error, {
        operation: methods.has(method) ? method : "native",
      });
      return {
        version: protocol.version,
        ok: false,
        error: {
          code: error.code || "internal",
          message: error.message || "The operation could not finish.",
        },
      };
    }
  });

  ipcMain.handle("dazedtl:choose-folder", async (event) => {
    trusted(event);
    const selected = await dialog.showOpenDialog(window, {
      title: "Choose a folder",
      properties: ["openDirectory"],
    });
    return selected.canceled ? null : selected.filePaths[0];
  });
  ipcMain.handle("dazedtl:choose-editor", async (event) => {
    trusted(event);
    const selected = await dialog.showOpenDialog(window, {
      title: "Choose a code editor", properties: ["openFile"],
    });
    return selected.canceled ? null : selected.filePaths[0];
  });
  ipcMain.handle("dazedtl:open-folder", async (event, kind, target) => {
    trusted(event);
    const folder =
      kind === "project"
        ? currentSource
        : kind === "projectWorkspace" && currentSource
          ? path.join(currentSource, ".dazedtl", "len-method")
          : kind === "workspace"
            ? backend.workspace
            : kind === "backup"
              ? (backupFolders.has(target) ? target : "")
              : outputs.has(target)
                ? target
                : "";
    if (!folder || !fs.statSync(folder).isDirectory())
      throw new Error("Choose an available folder.");
    if (kind === "backup" && fs.realpathSync(folder) !== path.resolve(folder))
      throw new Error("The backup location changed. Refresh its status before opening it.");
    if (
      kind === "projectWorkspace" &&
      !fs
        .realpathSync(folder)
        .startsWith(fs.realpathSync(currentSource) + path.sep)
    )
      throw new Error(
        "The project workspace must stay inside the selected game.",
      );
    const error = await shell.openPath(folder);
    if (error) throw new Error(error);
  });
  ipcMain.handle("dazedtl:close-ready", async (event, reply) => {
    trusted(event);
    if (!closing || reply?.token !== closeToken) return;
    clearTimeout(closeTimer);
    if (reply.error) await closeProblem(String(reply.error), reply.token);
    else await finishClose();
  });
  window.loadFile(path.join(root, "app/dist/index.html"));
});
process.on("uncaughtExceptionMonitor", (error) =>
  diagnostics?.failure("desktop.error", error),
);
