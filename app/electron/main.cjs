const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  shell,
  clipboard,
  screen,
  Notification,
  net,
} = require("electron");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");
const { Backend } = require("./backend.cjs");
const { Diagnostics } = require("./diagnostics.cjs");
const { windowSize } = require("./window-size.cjs");
const { rendererRecovery } = require("./renderer-recovery.cjs");
const { Updates } = require("./updates.cjs");
const { NotificationSound } = require("./sound.cjs");
const { sendToPhone } = require("./phone.cjs");

app.setName("DazedTL");
const appId = "dev.dazedtl.app";
// Desktop notifications need a fixed toast activator, so the Start menu
// shortcut that registers them stays valid from one run to the next.
const toastActivator = "{0F0248AA-BE0C-4113-8B58-2CCD1B97F80E}";
if (process.platform === "win32") {
  app.setAppUserModelId(appId);
  app.setToastActivatorCLSID(toastActivator);
}
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
// Shown notifications stay until the user returns, so they can leave the
// notification center then instead of lingering there.
const notices = new Set();
function clearNotices() {
  for (const notice of notices) notice.close();
  notices.clear();
}
let window,
  backend,
  diagnostics,
  updates,
  running = false,
  // "Restart to update" closes through the usual save handshake; the close
  // token it started marks the close that relaunches.
  restartPending = false,
  restartFor = 0,
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
  const restart = restartFor !== 0 && restartFor === closeToken;
  closeToken = 0;
  clearTimeout(closeTimer);
  if (window && !window.isDestroyed()) window.hide();
  // Clicked after the app ends, Windows would start a bare Electron.
  clearNotices();
  if (backend) await backend.close();
  if (restart)
    try {
      updates.relaunch();
    } catch (error) {
      // The launcher still applies the update on the next start.
      diagnostics?.failure("desktop.error", error, { operation: "native" });
    }
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
  // finishClose ends with app.exit, which skips this event. Any other quit,
  // such as Electron's own once a destroyed window was the last, waits for it
  // to stop the backend.
  event.preventDefault();
  if (quit) return;
  // A window that is already gone can no longer save drafts; finish instead
  // of closing it, or the app would stay running without a window.
  if (!window || window.isDestroyed()) void finishClose();
  else window.close();
});
// Where Windows looks for the shortcuts that register notifications.
const programs = () =>
  path.join(app.getPath("appData"), "Microsoft/Windows/Start Menu/Programs");
let notificationsRegistered = false;
let electronShortcutWatched = false;
/**
 * Windows shows a desktop app's notifications under the Start menu shortcut
 * carrying its app ID, and drops them while there is none. The launcher's
 * DazedTL shortcut takes the ID while it opens this install, so they read
 * DazedTL from the first one.
 */
function registerNotifications(root) {
  const link = path.join(programs(), "DazedTL.lnk");
  if (!fs.existsSync(link)) return;
  try {
    const current = shell.readShortcutLink(link);
    if (
      path.resolve(current.target).toLowerCase() !==
      path.join(root, "START.bat").toLowerCase()
    )
      return;
    if (
      current.appUserModelId !== appId ||
      current.toastActivatorClsid !== toastActivator
    )
      shell.writeShortcutLink(link, "update", {
        target: current.target,
        appUserModelId: appId,
        toastActivatorClsid: toastActivator,
      });
    notificationsRegistered = true;
    removeElectronShortcut();
  } catch (error) {
    diagnostics?.failure("desktop.error", error, { operation: "native" });
  }
}
/**
 * Electron also writes a shortcut named after its executable, "Electron",
 * which opens a bare Electron, when a run first shows a notification. With
 * the DazedTL shortcut registered, that one only clutters the Start menu.
 */
function removeElectronShortcut() {
  const stray = path.join(programs(), "Electron.lnk");
  try {
    if (
      !notificationsRegistered ||
      !fs.existsSync(stray) ||
      path.resolve(shell.readShortcutLink(stray).target).toLowerCase() !==
        process.execPath.toLowerCase()
    )
      return false;
    fs.rmSync(stray);
    return true;
  } catch (error) {
    diagnostics?.failure("desktop.error", error, { operation: "native" });
    return false;
  }
}
/** Electron writes its shortcut in the background, once per run. */
function watchElectronShortcut() {
  if (!notificationsRegistered || electronShortcutWatched) return;
  electronShortcutWatched = true;
  if (removeElectronShortcut()) return;
  const watcher = fs.watch(programs(), (_event, name) => {
    if (name === "Electron.lnk" && removeElectronShortcut()) stop();
  });
  const timer = setTimeout(() => stop(), 60_000);
  const stop = () => {
    watcher.close();
    clearTimeout(timer);
  };
}
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
    if (process.platform === "win32") {
      window.setAppDetails({
        appId,
        appIconPath: path.join(root, "resources/icon.ico"),
        relaunchCommand: `"${path.join(root, "START.bat")}"`,
        relaunchDisplayName: "DazedTL",
      });
      registerNotifications(root);
    }
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
      restartFor = restartPending ? token : 0;
      restartPending = false;
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
        if (method === "workspace_snapshot")
          running = !!result?.application?.running;
        if (method === "guided_export" || method === "guided_output_folder")
          outputs.add(result.path);
        // The backup store from before checkpoints, which Checkpoints opens.
        if (
          method === "project_checkpoints" &&
          typeof result?.backups === "string"
        )
          outputs.add(result.backups);
        if (method === "workspace_snapshot") {
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
          // A copy Checkpoints saved opens as its own folder.
          if (
            job.kind === "operation" &&
            job.status === "complete" &&
            job.action === "checkpoint_copy" &&
            typeof job.result?.folder === "string"
          )
            outputs.add(job.result.folder);
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

    updates = new Updates(root, app.getPath("userData"), (state) => {
      if (window && !window.isDestroyed())
        window.webContents.send("dazedtl:update-state", state);
    });
    void updates.start();
    ipcMain.handle("dazedtl:updates", (event) => {
      trusted(event);
      return updates.state;
    });
    ipcMain.handle("dazedtl:update-check", (event) => {
      trusted(event);
      return updates.check(true);
    });
    ipcMain.handle("dazedtl:update-channel", (event, channel) => {
      trusted(event);
      return updates.channel(channel);
    });
    ipcMain.handle("dazedtl:update-revert", (event) => {
      trusted(event);
      return updates.revert();
    });
    ipcMain.handle("dazedtl:update-keep", (event) => {
      trusted(event);
      return updates.keep();
    });
    ipcMain.handle("dazedtl:update-restart", (event) => {
      trusted(event);
      if (!updates.state.staged && !updates.state.revert)
        throw new Error("No update is ready to install.");
      if (running)
        throw new Error(
          "Finish the current run first; updating restarts DazedTL.",
        );
      if (closing || quit)
        throw new Error("Wait for the close request to finish.");
      restartPending = true;
      window.close();
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
              : outputs.has(target)
                ? target
                : "";
      if (!folder || !fs.statSync(folder).isDirectory())
        throw new Error("Choose an available folder.");
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
    const bringBack = () => {
      if (window.isDestroyed()) return;
      if (window.isMinimized()) window.restore();
      window.show();
      window.focus();
    };
    // A notification and the taskbar entry it lights up last until the user
    // returns.
    window.on("focus", () => {
      window.flashFrame(false);
      clearNotices();
    });
    // Windows reports a click in its notification center here, since the
    // notification's own click event ends when the popup does.
    if (process.platform === "win32") Notification.handleActivation(bringBack);
    ipcMain.handle("dazedtl:notify", (event, message) => {
      trusted(event);
      const { title, body, test } = message || {};
      if (
        typeof title !== "string" ||
        typeof body !== "string" ||
        title.length > 200 ||
        body.length > 1000
      )
        throw new Error("Choose a short notification.");
      if (window.isFocused() && !test) return;
      if (!Notification.isSupported())
        throw new Error("This system does not show desktop notifications.");
      if (!window.isFocused()) window.flashFrame(true);
      const notice = new Notification({
        title,
        body,
        icon: path.join(root, "resources/icon.png"),
        // The chime, when chosen, is the app's own sound.
        silent: true,
      });
      notices.add(notice);
      notice.on("click", bringBack);
      notice.on("failed", () => notices.delete(notice));
      notice.show();
      watchElectronShortcut();
    });
    // Unlike the desktop notification, the phone hears about work even while
    // the window is in front, since the user may have walked away from it.
    ipcMain.handle("dazedtl:phone", (event, message) => {
      trusted(event);
      return sendToPhone(message || {}, (url, init) => net.fetch(url, init));
    });
    const sound = new NotificationSound(
      path.join(app.getPath("userData"), "notification-sound"),
    );
    ipcMain.handle("dazedtl:sound-read", (event) => {
      trusted(event);
      return sound.read();
    });
    ipcMain.handle("dazedtl:sound-choose", (event) => {
      trusted(event);
      return sound.choose(window, dialog);
    });
    ipcMain.handle("dazedtl:sound-save", (event, value) => {
      trusted(event);
      sound.save(value);
    });
    ipcMain.handle("dazedtl:sound-clear", (event) => {
      trusted(event);
      sound.clear();
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
