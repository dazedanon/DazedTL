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
 * Whether *name* is blank or one the backend gave a connection to one of
 * *plans*: a plan's automatic name, or that name and a number when it was
 * taken (settings/store save_connection).
 */
function automaticName(plans: SettingsProvider[], name: string) {
  return (
    !name ||
    [...plans.map((plan) => plan.connectionName), ...FORMER_NAMES].some(
      (base) =>
        name === base ||
        (name.startsWith(`${base} `) &&
          /^\d+$/.test(name.slice(base.length + 1))),
    )
  );
}

/**
 * The connection form's values once Plan moves to *provider*. A provider's
 * plans take the same key, so a typed key stays, and a saved connection to
 * another of the plans keeps its saved key unless the user unticks it. An
 * automatic name is left blank for the backend to name the new plan's,
 * and back on the saved plan the saved one returns.
 */
export function choosePlan<Value extends PlanFields>(
  presets: SettingsProvider[],
  value: Value,
  provider: string,
  saved?: Pick<Connection, "provider" | "has_secret" | "name">,
): Value {
  const plans = plansOf(
    presets,
    presets.find((item) => item.id === value.provider),
  );
  if (!plans.some((plan) => plan.id === provider)) return value;
  return {
    ...value,
    provider,
    name: !automaticName(plans, value.name)
      ? value.name
      : saved?.provider === provider && automaticName(plans, saved.name)
        ? saved.name
        : "",
    reuse_secret:
      !!saved?.has_secret &&
      saved.provider !== provider &&
      plans.some((plan) => plan.id === saved.provider) &&
      !value.secret,
  };
}
