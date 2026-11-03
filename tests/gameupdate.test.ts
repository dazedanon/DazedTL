import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const plugin = fs.readFileSync(
  path.join(
    import.meta.dirname,
    "../backend/dazedtl/engine/gameupdate/gameupdate/TranslationUpdateCheck.js",
  ),
  "utf8",
);

test("the in-game update check reaches GitGud with the header its admin asks apps to send", async (t) => {
  // Since 2026-11-02 GitGud answers a request without X-Gitlab-Token or
  // another header its Cloudflare rule looks for with a challenge page.
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
  const warning = await new Promise<string>((resolve) => {
    const https = {
      get(
        options: { headers?: Record<string, string> },
        callback: (response: EventEmitter) => void,
      ) {
        const named = Object.keys(options.headers ?? {}).some(
          (name) => name.toLowerCase() === "x-gitlab-token",
        );
        const response = Object.assign(new EventEmitter(), {
          statusCode: named ? 200 : 403,
          resume() {},
          setEncoding() {},
        });
        const request = Object.assign(new EventEmitter(), {
          setTimeout() {},
          destroy() {},
        });
        setImmediate(() => {
          callback(response);
          if (!named) return resolve("");
          response.emit(
            "data",
            JSON.stringify({ commit: { id: "b".repeat(40) } }),
          );
          response.emit("end");
        });
        return request;
      },
    };
    vm.runInNewContext(plugin, {
      require: (name: string) => (name === "https" ? https : require(name)),
      process: { cwd: () => game, execPath: path.join(game, "Game") },
      window: { alert: resolve },
      setTimeout,
    });
  });
  assert.match(warning, /gitgud\.io\/Owner\/Game/);
});
