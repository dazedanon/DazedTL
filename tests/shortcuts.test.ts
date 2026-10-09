import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { root } from "../scripts/dependencies.mjs";
import { shortcuts } from "../scripts/shortcuts.mjs";

test(
  "a second install leaves the menu entry with a newer install and takes it from an older or removed one",
  { skip: process.platform !== "linux" },
  () => {
    // Setting up an older copy beside the user's install repointed their
    // shortcuts to the older copy.
    const home = fs.mkdtempSync(path.join(os.tmpdir(), "dazedtl-shortcuts-"));
    const previous = process.env.XDG_DATA_HOME;
    process.env.XDG_DATA_HOME = home;
    const entry = path.join(home, "applications", "dazedtl.desktop");
    const opens = () =>
      /^Icon=(.+)$/m.exec(fs.readFileSync(entry, "utf8"))?.[1];
    const install = (name: string, version: string) => {
      const folder = path.join(home, name);
      fs.mkdirSync(path.join(folder, "app"), { recursive: true });
      fs.writeFileSync(path.join(folder, "START.sh"), "");
      fs.writeFileSync(
        path.join(folder, "app", "package.json"),
        JSON.stringify({ version }),
      );
      return folder;
    };
    const ownedBy = (folder: string) => {
      fs.mkdirSync(path.dirname(entry), { recursive: true });
      fs.writeFileSync(
        entry,
        `[Desktop Entry]\nIcon=${path.join(folder, "resources", "icon.png")}\n`,
      );
    };
    try {
      const newer = install("newer", "999.0.0");
      ownedBy(newer);
      const state: { shortcuts?: string } = {};
      shortcuts(state);
      assert.equal(opens(), path.join(newer, "resources", "icon.png"));
      // It asks again on its next start, after the newer one may be gone.
      assert.equal(state.shortcuts, undefined);
      for (const folder of [
        install("older", "0.0.1"),
        path.join(home, "removed"),
      ]) {
        ownedBy(folder);
        shortcuts(state);
        assert.equal(opens(), path.join(root, "resources", "icon.png"));
        assert.equal(state.shortcuts, root);
        delete state.shortcuts;
      }
    } finally {
      if (previous === undefined) delete process.env.XDG_DATA_HOME;
      else process.env.XDG_DATA_HOME = previous;
      fs.rmSync(home, { recursive: true, force: true });
    }
  },
);
