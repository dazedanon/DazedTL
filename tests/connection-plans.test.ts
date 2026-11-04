import assert from "node:assert/strict";
import test from "node:test";
import type { SettingsProvider } from "../app/src/api/contracts.ts";
import {
  choosePlan,
  providerChoices,
} from "../app/src/features/settings/providerPlans.ts";

const preset = (
  id: SettingsProvider["id"],
  label: string,
  plan?: string,
): SettingsProvider => ({
  id,
  label,
  ...(plan ? { plan } : {}),
  connectionName: plan ? `${label} (${plan})` : label,
  protocol: "openai",
  defaultEndpoint: "",
});
const presets = [
  preset("deepseek", "DeepSeek"),
  preset("opencode-go", "OpenCode", "Go subscription"),
  preset("opencode", "OpenCode", "Pay-as-you-go balance"),
  preset("custom", "Custom / local"),
];

test("a provider's plans are one provider choice, at its first plan", () => {
  assert.deepEqual(
    providerChoices(presets).map((item) => item.id),
    ["deepseek", "opencode-go", "custom"],
  );
});

test("a saved connection keeps its key and automatic name across plans", () => {
  const saved = { provider: "opencode-go" as const, has_secret: true };
  const initial = {
    provider: "opencode-go",
    name: "OpenCode (Go subscription)",
    secret: "",
    reuse_secret: false,
  };
  const moved = choosePlan(presets, initial, "opencode", saved);
  assert.deepEqual(moved, {
    provider: "opencode",
    name: "OpenCode (Pay-as-you-go balance)",
    secret: "",
    reuse_secret: true,
  });
  // Moving back leaves nothing to save.
  assert.deepEqual(choosePlan(presets, moved, "opencode-go", saved), initial);
  // A name the user chose stays.
  assert.equal(
    choosePlan(presets, { ...initial, name: "Mine" }, "opencode", saved).name,
    "Mine",
  );
});

test("another provider's saved key never moves to a plan", () => {
  const value = {
    provider: "opencode-go",
    name: "DeepSeek",
    secret: "",
    reuse_secret: false,
  };
  const saved = { provider: "deepseek" as const, has_secret: true };
  assert.equal(
    choosePlan(presets, value, "opencode", saved).reuse_secret,
    false,
  );
});
