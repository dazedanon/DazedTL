// Drives a running DazedTL window over the DevTools protocol, as the live
// test and test scenarios do: clicks controls by accessible name with real
// mouse input, types as keyboard input, calls the backend as the interface
// does, and takes screenshots.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

export const message = (error) =>
  error instanceof Error ? error.message : String(error);

/** Polls `check` until it returns a truthy value. */
export async function until(description, check, timeout = 30_000) {
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

/** The protocol version the interface of the install at `root` speaks. */
export const protocolVersion = (root) =>
  JSON.parse(
    fs.readFileSync(
      path.join(root, "backend/dazedtl/api/protocol.json"),
      "utf8",
    ),
  ).version;

export class Page {
  /**
   * Connects to the window of the install at `root`, or with `node`, to its
   * Electron main process. Another app on the same port, such as another
   * session's, is never driven.
   * @param {number} port
   * @param {{ root: string, node?: boolean }} options
   */
  static async connect(port, { root, node = false }) {
    // Chromium and Node may spell the same file URL differently.
    const spelling = (url) => {
      const value = decodeURI(url);
      return process.platform === "win32" ? value.toLowerCase() : value;
    };
    // The window names the page by its real path, past any linked folder
    // such as a worktree's .runtime shared with the main checkout.
    const own = spelling(
      pathToFileURL(
        path.join(fs.realpathSync.native(root), "app/dist/index.html"),
      ).href,
    );
    const target = await until(
      "DazedTL to accept DevTools connections",
      async () => {
        const targets = await (
          await fetch(`http://127.0.0.1:${port}/json/list`)
        ).json();
        // The main process's inspector lists no pages; its port was free
        // when the app started.
        if (node) return targets.find((item) => item.type === "node");
        const pages = targets.filter((item) => item.type === "page");
        if (pages.length && !pages.some((item) => spelling(item.url) === own))
          throw new Error(
            `Port ${port} serves another app (${pages.map((item) => item.url).join(", ")}).`,
          );
        return pages.find((item) => spelling(item.url) === own);
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
    return new Page(socket, protocolVersion(root));
  }

  constructor(socket, protocol) {
    this.socket = socket;
    this.protocol = protocol;
    this.serial = 0;
    this.pending = new Map();
    socket.addEventListener("message", (event) => {
      const reply = JSON.parse(String(event.data));
      const task = this.pending.get(reply.id);
      if (!task) return;
      this.pending.delete(reply.id);
      if (reply.error)
        task.reject(new Error(`${task.method}: ${reply.error.message}`));
      else task.resolve(reply.result);
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

  /** Saves a PNG of the window to `file`. */
  async shot(file) {
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
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, Buffer.from(data, "base64"));
  }

  /** Calls the backend through the window, as the interface does. */
  async call(method, params = {}) {
    const reply = await this.evaluate(
      `window.dazedtl.call(${JSON.stringify(this.protocol)}, ${JSON.stringify(method)}, ${JSON.stringify(params)})`,
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

  /** Waits until the app runs no operation, such as Apply's follow-up work. */
  idle(timeout = 5 * 60_000) {
    return until(
      "the app to finish its work",
      async () => !(await this.call("workspace_snapshot")).application.running,
      timeout,
    );
  }

  /**
   * The center of the enabled control whose accessible name matches, when it
   * shows uncovered, after scrolling it into view; otherwise null.
   * @param {string | RegExp} name
   */
  locate(name) {
    const pattern =
      typeof name === "string"
        ? `^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`
        : name.source;
    return this.evaluate(`(() => {
      const pattern = new RegExp(${JSON.stringify(pattern)});
      const label = (element) =>
        (element.getAttribute("aria-label") || element.textContent).replace(/\\s+/g, " ").trim();
      const found = [
        ...document.querySelectorAll("button, a, label, [role=button], [role=tab], [role=radio], [role=option], [role=menuitem]"),
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
    })()`);
  }

  /**
   * Clicks the enabled control whose accessible name matches, with mouse input
   * at its center, so a covered or disabled control fails as it would for a user.
   * @param {string | RegExp} name
   */
  async click(name, timeout = 60_000) {
    const at = await until(
      `an enabled "${name}" control`,
      () => this.locate(name),
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
