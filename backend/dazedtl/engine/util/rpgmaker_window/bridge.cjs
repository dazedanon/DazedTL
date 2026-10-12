// The harness page script's only channel out of the sandboxed game page.
// Every window of the run loads it before the harness's own page script.
"use strict";

const { ipcRenderer } = require("electron");

window.dazedtlHarness = Object.freeze({
  /** What the page does in this window, with where an earlier one stopped. */
  plan: () => ipcRenderer.sendSync("harness-plan"),
  /** Tells the harness what the page found or is doing: a `step` names
   * what a crash or hang would interrupt, and `done` ends the run. */
  send: (type, value) => ipcRenderer.send("harness-send", type, value),
  /** Asks the harness for something, such as a capture of the window. */
  call: (name, ...values) =>
    ipcRenderer.invoke("harness-call", name, ...values),
});
