import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test, { type TestContext } from "node:test";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const plugin = fs.readFileSync(
  path.join(
    import.meta.dirname,
    "../backend/dazedtl/engine/gameupdate/gameupdate/TranslationUpdateCheck.js",
  ),
  "utf8",
);

type Answer = { status: number; body?: string };
type Route = (path: string, headers: Record<string, string>) => Answer;

/**
 * Runs the in-game check in a GitGud game whose installed patch is older than
 * the branch, against *route* standing in for GitGud, and resolves with the
 * warning it shows, or "" once a request it makes fails with nothing after.
 */
function warningFrom(t: TestContext, route: Route) {
  const game = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-check-"));
  t.after(() => fs.rmSync(game, { recursive: true, force: true }));
  fs.mkdirSync(path.join(game, "gameupdate"));
  fs.writeFileSync(
    path.join(game, "gameupdate/patch-config.txt"),
    "forge=gitlab\nhost=gitgud.io\nusername=Owner\nrepo=Game\nbranch=main\n",
  );
  fs.writeFileSync(
    path.join(game, "gameupdate/previous_patch_sha.txt"),
    "a".repeat(40),
  );
  return new Promise<string>((resolve) => {
    let pending = 0;
    const https = {
      get(
        options: { path: string; headers?: Record<string, string> },
        callback: (response: EventEmitter) => void,
      ) {
        const answer = route(options.path, options.headers ?? {});
        const response = Object.assign(new EventEmitter(), {
          statusCode: answer.status,
          resume() {},
          setEncoding() {},
        });
        const request = Object.assign(new EventEmitter(), {
          setTimeout() {},
          destroy() {},
        });
        pending++;
        setImmediate(() => {
          callback(response);
          if (answer.status === 200) {
            response.emit("data", answer.body ?? "");
            response.emit("end");
          }
          // A warning comes in this turn or not at all.
          setImmediate(() => --pending || resolve(""));
        });
        return request;
      },
    };
    vm.runInNewContext(plugin, {
      require: (name: string) => (name === "https" ? https : require(name)),
      process: { cwd: () => game, execPath: path.join(game, "Game") },
      window: { alert: resolve },
      setTimeout,
      unescape,
    });
  });
}

const named = (headers: Record<string, string>) =>
  Object.keys(headers).some((name) => name.toLowerCase() === "x-gitlab-token");

// A Git smart HTTP ref advertisement, in pkt-lines.
function advertisement(refs: [string, string][]) {
  const pkt = (line: string) =>
    (line.length + 4).toString(16).padStart(4, "0") + line;
  return (
    pkt("# service=git-upload-pack\n") +
    "0000" +
    refs
      .map(([sha, ref], index) =>
        pkt(`${sha} ${ref}${index ? "" : "\0multi_ack side-band-64k"}\n`),
      )
      .join("") +
    "0000"
  );
}

test("the in-game update check reaches GitGud with the header its admin asks apps to send", async (t) => {
  // Since 2026-11-02 GitGud answers a request without X-Gitlab-Token or
  // another header its Cloudflare rule looks for with a challenge page.
  const warning = await warningFrom(t, (requested, headers) =>
    requested.startsWith("/api/v4/") && named(headers)
      ? {
          status: 200,
          body: JSON.stringify({ commit: { id: "b".repeat(40) } }),
        }
      : { status: 403 },
  );
  assert.match(warning, /gitgud\.io\/Owner\/Game/);
});

test("the in-game update check reads the branch from Git when the API refuses it", async (t) => {
  const asked: string[] = [];
  const warning = await warningFrom(t, (requested) => {
    asked.push(requested);
    if (requested === "/Owner/Game.git/info/refs?service=git-upload-pack")
      return {
        status: 200,
        body: advertisement([
          ["a".repeat(40), "HEAD"],
          ["a".repeat(40), "refs/heads/old"],
          ["b".repeat(40), "refs/heads/main"],
        ]),
      };
    return { status: 403 };
  });
  assert.match(warning, /gitgud\.io\/Owner\/Game/);
  assert.equal(asked.length, 2);
});
