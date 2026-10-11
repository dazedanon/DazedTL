// The harness's only channel out of the sandboxed game page.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dazedtlCapture", {
  plan: () => ipcRenderer.sendSync("plan"),
  size: (width, height) => ipcRenderer.invoke("size", width, height),
  capture: (name, meta) => ipcRenderer.invoke("capture", name, meta),
  skip: (screen, reason) => ipcRenderer.send("skip", screen, reason),
  error: (message) => ipcRenderer.send("error", message),
  done: (game) => ipcRenderer.send("done", game),
});
