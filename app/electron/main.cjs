const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  shell,
  clipboard,
  screen,
} = require("electron");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");
const { Backend } = require("./backend.cjs");
const { Diagnostics } = require("./diagnostics.cjs");
const { windowSize } = require("./window-size.cjs");
const { rendererRecovery } = require("./renderer-recovery.cjs");

app.setName("DazedTL");
if (process.platform === "win32") app.setAppUserModelId("dev.dazedtl.app");
// The retired Electron preview of DazedMTLTool owns the "DazedTL" folder. Saved
// runs hold absolute profile paths, so a pre-release "DazedTLNext" profile
// stays where it is instead of moving to the released name.
const profiles = app.getPath("appData");
const released = path.join(profiles, "DazedTL2");
const prerelease = path.join(profiles, "DazedTLNext");
app.setPath(
  "userData",
  process.env.DAZEDTL_PROFILE
    ? path.resolve(process.env.DAZEDTL_PROFILE)
    : !fs.existsSync(released) && fs.existsSync(prerelease)
      ? prerelease
      : released,
);
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
  if (window && !window.isDestroyed()) window.hide();
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
  if (quit) return;
  event.preventDefault();
  // A window that is already gone can no longer save drafts; finish instead
  // of closing it, or the app would stay running without a window.
  if (!window || window.isDestroyed()) void finishClose();
  else window.close();
});
// Startup failures would otherwise leave a running process without a window.
function startupFailed(error) {
  diagnostics?.failure("desktop.error", error, { operation: "native" });
  dialog.showErrorBox(
    "DazedTL could not start",
    "Restart DazedTL. If this keeps happening, use Copy diagnostics after the next launch.",
  );
  app.exit(1);
}
app
  .whenReady()
  .then(() => {
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
    window = new BrowserWindow({
      show: false,
      ...windowSize(screen.getPrimaryDisplay().workAreaSize),
      title: "DazedTL",
      backgroundColor: "#171a20",
      icon: path.join(root, "resources/icon.png"),
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        backgroundThrottling: false,
        // Paths read home-relative in the interface; the sandboxed preload
        // has no access to the OS module.
        additionalArguments: [`--dazedtl-home=${os.homedir()}`],
      },
    });
    const fitMinimumSize = () => {
      if (!window || window.isDestroyed()) return;
      const size = windowSize(
        screen.getDisplayMatching(window.getBounds()).workAreaSize,
      );
      const [width, height] = window.getMinimumSize();
      if (width !== size.minWidth || height !== size.minHeight)
        window.setMinimumSize(size.minWidth, size.minHeight);
    };
    window.on("move", fitMinimumSize);
    screen.on("display-metrics-changed", fitMinimumSize);
    window.once("closed", () =>
      screen.off("display-metrics-changed", fitMinimumSize),
    );
    window.once("ready-to-show", () => {
      fitMinimumSize();
      window.maximize();
      window.show();
      // The launcher closes its console once the window is open.
      if (process.env.DAZEDTL_LAUNCH_SIGNAL)
        process.stdout.write("dazedtl:shown\n");
    });
    // A window pinned to the taskbar starts DazedTL the way its shortcut does,
    // rather than as a bare Electron.
    if (process.platform === "win32")
      window.setAppDetails({
        appId: "dev.dazedtl.app",
        appIconPath: path.join(root, "resources/icon.ico"),
        relaunchCommand: `"${path.join(root, "START.bat")}"`,
        relaunchDisplayName: "DazedTL",
      });
    backend = new Backend(
      root,
      app.getPath("userData"),
      (message) => window?.webContents.send("dazedtl:stopped", message),
      diagnostics,
    );
    const recovery = rendererRecovery(window, {
      diagnostics,
      dialog,
      clipboard,
      closing: () => closing || quit,
      beforeReload: () => {
        ready = false;
      },
    });
    window.webContents.on(
      "did-fail-load",
      (_event, errorCode, _description, _url, mainFrame) => {
        if (mainFrame)
          diagnostics.record("renderer.load-failed", { errorCode });
      },
    );
    window.setMenuBarVisibility(false);
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event) => event.preventDefault());
    window.webContents.session.setPermissionRequestHandler(
      (_web, _permission, callback) => callback(false),
    );
    // A window destroyed without the guarded close below, such as by a
    // script calling window.close(), still ends the app and its backend.
    window.on("closed", () => void finishClose());
    window.on("close", (event) => {
      if (quit) return;
      event.preventDefault();
      if (closing) return;
      closing = true;
      const token = (closeToken = ++closeSerial);
      if (recovery.failed()) {
        void closeProblem(
          "The interface cannot save changes right now. Keep it open to recover, or discard unsaved changes and close.",
          token,
        ).catch((error) => {
          diagnostics.failure("desktop.error", error, { operation: "native" });
          if (token !== closeToken) return;
          closing = false;
          closeToken = 0;
        });
        return;
      }
      if (!ready) return void finishClose();
      closeTimer = setTimeout(() => {
        void closeProblem(
          "Saving is taking longer than expected.",
          token,
        ).catch(() => {
          if (token !== closeToken) return;
          closing = false;
          closeToken = 0;
          window.webContents.send("dazedtl:close-cancelled", token);
        });
      }, 10000);
      window.webContents.send("dazedtl:closing", token);
    });
    ipcMain.handle("dazedtl:ready", (event) => {
      trusted(event);
      ready = true;
    });
    ipcMain.handle("dazedtl:copy-text", async (event, text) => {
      trusted(event);
      if (
        typeof text !== "string" ||
        Buffer.byteLength(text, "utf8") > 2_000_000
      )
        throw new Error("Choose a bounded text artifact to copy.");
      await clipboard.writeText(text);
    });
    ipcMain.handle("dazedtl:copy-diagnostics", async (event) => {
      trusted(event);
      try {
        await clipboard.writeText(await diagnostics.report());
      } catch (error) {
        diagnostics.failure("desktop.error", error, { operation: "native" });
        throw new Error("Diagnostics could not be copied. Try again.");
      }
    });
    ipcMain.handle("dazedtl:renderer-error", (event, failure) => {
      trusted(event);
      if (!["render", "error", "unhandledrejection"].includes(failure?.reason))
        return;
      diagnostics.renderer(failure.reason, failure.causes);
    });
    ipcMain.handle("dazedtl:reload-interface", (event) => {
      trusted(event);
      if (closing || quit)
        throw new Error("Wait for the close request to finish.");
      recovery.reload();
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
        if (method === "guided_export" || method === "guided_output_folder")
          outputs.add(result.path);
        if (method === "workspace_snapshot") {
          backupFolders.clear();
          for (const key of [
            "source_backup",
            "game_backup",
            "prepared_source",
            "workspace_backup",
          ]) {
            const backup = result?.translation?.lifecycle?.[key];
            if (backup?.available === true && typeof backup.path === "string")
              backupFolders.add(backup.path);
          }
          for (const artifact of result?.guided?.artifacts || []) {
            if (
              artifact.available === true &&
              typeof artifact.folder === "string"
            )
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
        const failure =
          /** @type {{ code?: string, message?: string, details?: unknown }} */ (
            error
          );
        // Coded errors were explained to the user or recorded by the backend;
        // only unexpected desktop errors need a trail, like backend ones.
        if (!failure.code)
          diagnostics.failure("desktop.error", error, {
            operation: methods.has(method) ? method : "native",
          });
        return {
          version: protocol.version,
          ok: false,
          error: failure.code
            ? {
                code: failure.code,
                message: failure.message,
                details: failure.details,
              }
            : { code: "internal", message: "The operation could not finish." },
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
        title: "Choose a code editor",
        properties: ["openFile"],
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
                ? backupFolders.has(target)
                  ? target
                  : ""
                : outputs.has(target)
                  ? target
                  : "";
      if (!folder || !fs.statSync(folder).isDirectory())
        throw new Error("Choose an available folder.");
      if (kind === "backup" && fs.realpathSync(folder) !== path.resolve(folder))
        throw new Error(
          "The backup location changed. Refresh its status before opening it.",
        );
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
    window
      .loadFile(path.join(root, "app/dist/index.html"))
      .catch(startupFailed);
  })
  .catch(startupFailed);
process.on("uncaughtExceptionMonitor", (error) =>
  diagnostics?.failure("desktop.error", error),
);
