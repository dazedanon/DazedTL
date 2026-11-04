import type { Connection, SettingsProvider } from "../../api/contracts";

/**
 * The presets that are *preset*'s provider's plans, its own among them, or
 * none when it has no plan: presets with a plan that share a label, such as
 * OpenCode's Go subscription and pay-as-you-go balance. The provider list
 * offers them once, at the first, and Plan picks among them.
 */
export function plansOf(
  presets: SettingsProvider[],
  preset: SettingsProvider | undefined,
) {
  return preset?.plan
    ? presets.filter((item) => item.plan && item.label === preset.label)
    : [];
}

/** The provider list: every preset, with a provider's plans once. */
export function providerChoices(presets: SettingsProvider[]) {
  return presets.filter(
    (preset) => (plansOf(presets, preset)[0] ?? preset) === preset,
  );
}

// The automatic names 2.61.0 gave OpenCode's plans, before they were one
// provider, so connections saved then follow a plan switch too.
const FORMER_NAMES = ["OpenCode Go", "OpenCode pay-as-you-go"];

type PlanFields = {
  provider: string;
  name: string;
  secret: string;
  reuse_secret: boolean;
};

/**
 * The connection form's values once Plan moves to *provider*. A provider's
 * plans take the same key, so a typed key stays, and a saved connection to
 * another of the plans keeps its saved key unless the user unticks it. An
 * automatic name follows the plan.
 */
export function choosePlan<Value extends PlanFields>(
  presets: SettingsProvider[],
  value: Value,
  provider: string,
  saved?: Pick<Connection, "provider" | "has_secret">,
): Value {
  const plans = plansOf(
    presets,
    presets.find((item) => item.id === value.provider),
  );
  const next = plans.find((plan) => plan.id === provider);
  if (!next) return value;
  return {
    ...value,
    provider,
    name:
      plans.some((plan) => plan.connectionName === value.name) ||
      FORMER_NAMES.includes(value.name)
        ? next.connectionName
        : value.name,
    reuse_secret:
      !!saved?.has_secret &&
      saved.provider !== provider &&
      plans.some((plan) => plan.id === saved.provider) &&
      !value.secret,
  };
}
