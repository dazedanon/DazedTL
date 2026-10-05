/** Native recovery remains usable when JavaScript in the window cannot respond. */
function rendererRecovery(
  window,
  { diagnostics, dialog, clipboard, beforeReload, closing },
) {
  const contents = window.webContents;
  let failed = false,
    reloading = false,
    prompting = false;
  const available = () =>
    !window.isDestroyed() && !contents.isDestroyed() && !closing();
  function reload() {
    if (!available() || reloading) return;
    reloading = true;
    beforeReload();
    diagnostics.record("renderer.reload");
    // A hung renderer may never service an ordinary reload. Only the explicit
    // native recovery action may replace it without the renderer's draft flush.
    if (failed && !contents.isCrashed()) contents.forcefullyCrashRenderer();
    contents.reload();
  }
  async function offerRecovery() {
    if (prompting || reloading || !available()) return;
    prompting = true;
    let feedback = "";
    try {
      while (failed && available()) {
        const choice = await dialog.showMessageBox(window, {
          type: "warning",
          title: "DazedTL recovery",
          message: contents.isCrashed()
            ? "The interface stopped unexpectedly."
            : "The interface is not responding.",
          detail:
            (feedback ? feedback + "\n\n" : "") +
            "Reloading restores the interface while running jobs stay active. Changes that have not reached recovery storage may be lost.",
          buttons: [
            contents.isCrashed() ? "Keep open" : "Wait",
            "Reload interface",
            "Copy diagnostics",
          ],
          defaultId: 0,
          cancelId: 0,
          noLink: true,
        });
        if (!failed || !available()) break;
        if (choice.response === 1) {
          reload();
          break;
        }
        if (choice.response !== 2) break;
        try {
          clipboard.writeText(diagnostics.report());
          feedback = "Diagnostics copied.";
        } catch {
          feedback = "Diagnostics could not be copied. Try again.";
        }
      }
    } catch (error) {
      diagnostics.failure("desktop.error", error, { operation: "native" });
    } finally {
      prompting = false;
    }
  }
  contents.on("render-process-gone", (_event, details) => {
    diagnostics.record("renderer.gone", {
      reason: details.reason,
      exitCode: details.exitCode,
    });
    failed = true;
    void offerRecovery();
  });
  window.on("unresponsive", () => {
    diagnostics.record("renderer.unresponsive");
    failed = true;
    void offerRecovery();
  });
  window.on("responsive", () => {
    if (!contents.isCrashed()) failed = false;
  });
  contents.on("did-finish-load", () => {
    failed = false;
    reloading = false;
  });
  return { reload, failed: () => failed };
}

module.exports = { rendererRecovery };
