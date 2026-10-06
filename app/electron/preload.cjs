const { contextBridge, ipcRenderer } = require("electron");
// Electron prefixes an error a handler throws with its channel name; only the
// handler's own message is meant for the user.
const invoke = (channel, ...args) =>
  ipcRenderer.invoke(channel, ...args).catch((error) => {
    throw new Error(
      String(error?.message ?? error).replace(
        /^Error invoking remote method '[^']*': (?:[A-Za-z]*Error: )?/,
        "",
      ),
    );
  });
contextBridge.exposeInMainWorld("dazedtl", {
  call: (version, method, params = {}) =>
    invoke("dazedtl:call", version, method, params),
  ready: () => invoke("dazedtl:ready"),
  copyText: (text) => invoke("dazedtl:copy-text", text),
  copyDiagnostics: () => invoke("dazedtl:copy-diagnostics"),
  reportRendererError: (failure) => invoke("dazedtl:renderer-error", failure),
  reloadInterface: () => invoke("dazedtl:reload-interface"),
  chooseFolder: () => invoke("dazedtl:choose-folder"),
  chooseEditor: () => invoke("dazedtl:choose-editor"),
  openFolder: (kind, target) => invoke("dazedtl:open-folder", kind, target),
  onClose: (handler, cancelled) => {
    let activeToken = 0;
    const respond = async (token) => {
      activeToken = token;
      let error = "";
      try {
        await handler();
      } catch (value) {
        error = value instanceof Error ? value.message : String(value);
      }
      try {
        await invoke("dazedtl:close-ready", { token, error });
      } catch {
        // Without a reply, the main process shows its close-timeout choice.
      }
    };
    const listener = (_event, token) => void respond(token);
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
