import type { ReactNode } from "react";
import type { GuidedOptions, GuidedState, Phase } from "../../api/contracts";
import { Section } from "../../ui/Section";
import { ActionList } from "../../ui/ActionList";
import { EngineOptions } from "./EngineOptions";

export function TranslationOptions({
  state,
  phase,
  values,
  disabled,
  change,
  fileActions,
}: {
  state: GuidedState;
  phase: Phase;
  values: GuidedOptions;
  disabled: boolean;
  fileActions: ReactNode;
  change: <K extends keyof GuidedOptions>(
    key: K,
    value: GuidedOptions[K],
  ) => void;
}) {
  const behavior =
    phase === "variables"
      ? ["IGNORETLTEXT"]
      : [
          "IGNORETLTEXT",
          "PRESERVEORIGINAL",
          "FIXTEXTWRAP",
          "BRFLAG",
          ...(phase === "database"
            ? ["TLSYSTEMVARIABLES", "TLSYSTEMSWITCHES"]
            : []),
        ];
  return (
    <>
      <Section title="Translation behavior">
        <EngineOptions
          inlineBooleans
          state={state}
          values={values.engine_options}
          keys={behavior}
          disabled={disabled}
          change={(key, value) =>
            change("engine_options", { ...values.engine_options, [key]: value })
          }
        />
      </Section>
      <Section title="Selected working files">
        <ActionList compact>{fileActions}</ActionList>
      </Section>
    </>
  );
}
