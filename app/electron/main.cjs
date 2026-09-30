const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("node:path");
const { Backend } = require("./backend.cjs");

app.setName("DazedTLNext");
if (process.env.DAZEDTL_NEXT_PROFILE)
  app.setPath("userData", path.resolve(process.env.DAZEDTL_NEXT_PROFILE));
const protocol = require("../../backend/dazedtl/api/protocol.json");
const methods = new Set(Object.keys(protocol.methods));
const outputs = new Set();
let window,
  backend,
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
  window = new BrowserWindow({
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
  backend = new Backend(root, app.getPath("userData"), (message) =>
    window?.webContents.send("dazedtl:stopped", message),
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
          ? result.application.project
          : result.project;
      if (selected?.source) currentSource = selected.source;
      if (method === "guided_export") outputs.add(result.path);
      return { version: protocol.version, ok: true, value: result };
    } catch (error) {
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
      title: "Choose a game folder",
      properties: ["openDirectory"],
    });
    return selected.canceled ? null : selected.filePaths[0];
  });
  ipcMain.handle("dazedtl:open-folder", async (event, kind, target) => {
    trusted(event);
    const folder =
      kind === "project"
        ? currentSource
        : kind === "workspace"
          ? backend.workspace
          : outputs.has(target)
            ? target
            : "";
    if (!folder) throw new Error("Choose an available folder.");
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
