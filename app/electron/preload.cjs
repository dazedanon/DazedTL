const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("dazedtl", {
  call: (version, method, params = {}) =>
    ipcRenderer.invoke("dazedtl:call", version, method, params),
  ready: () => ipcRenderer.invoke("dazedtl:ready"),
  copyText: (text) => ipcRenderer.invoke("dazedtl:copy-text", text),
  copyDiagnostics: () => ipcRenderer.invoke("dazedtl:copy-diagnostics"),
  chooseFolder: () => ipcRenderer.invoke("dazedtl:choose-folder"),
  openFolder: (kind, target) =>
    ipcRenderer.invoke("dazedtl:open-folder", kind, target),
  onClose: (handler, cancelled) => {
    let activeToken = 0;
    const listener = async (_event, token) => {
      activeToken = token;
      let error = "";
      try {
        await handler();
      } catch (value) {
        error = value instanceof Error ? value.message : String(value);
      }
      await ipcRenderer.invoke("dazedtl:close-ready", { token, error });
    };
    const cancelListener = (_event, token) => {
      if (token !== activeToken) return;
      activeToken = 0;
      cancelled();
    };
    ipcRenderer.on("dazedtl:closing", listener);
    ipcRenderer.on("dazedtl:close-cancelled", cancelListener);
    return () => {
      ipcRenderer.removeListener("dazedtl:closing", listener);
      ipcRenderer.removeListener("dazedtl:close-cancelled", cancelListener);
    };
  },
  onStopped: (handler) => {
    const listener = (_event, message) => handler(message);
    ipcRenderer.on("dazedtl:stopped", listener);
    return () => ipcRenderer.removeListener("dazedtl:stopped", listener);
  },
});
