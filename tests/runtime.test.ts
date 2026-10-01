import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { root, requireNode } from "../scripts/dependencies.mjs";

test("Node updates can launch the app while setup retains its exact runtime pin", () => {
  const expected = fs.readFileSync(path.join(root, ".node-version"), "utf8").trim();
  const [major, minor, patch] = expected.split(".").map(Number);
  const descriptor = Object.getOwnPropertyDescriptor(process.versions, "node")!;
  const cases = [
    { version: expected, supported: true, exact: true },
    { version: `${major}.${minor}.${patch + 1}`, supported: true, exact: false },
    { version: `${major}.${minor + 1}.0`, supported: true, exact: false },
    { version: `${major}.${minor - 1}.0`, supported: false, exact: false },
    { version: `${major + 1}.0.0`, supported: false, exact: false },
    { version: `${major - 1}.99.0`, supported: false, exact: false },
    { version: `${major}.${minor + 1}.0-rc.1`, supported: false, exact: false },
  ];
  try {
    for (const { version, supported, exact } of cases) {
      Object.defineProperty(process.versions, "node", { ...descriptor, value: version });
      if (supported) assert.doesNotThrow(() => requireNode(), version);
      else assert.throws(() => requireNode(), /Use Node/, version);
      if (exact) assert.doesNotThrow(() => requireNode({ exact: true }), version);
      else assert.throws(() => requireNode({ exact: true }), /for setup/, version);
    }
  } finally {
    Object.defineProperty(process.versions, "node", descriptor);
  }
});
