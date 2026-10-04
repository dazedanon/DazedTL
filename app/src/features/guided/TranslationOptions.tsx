import type { ReactNode } from "react";
import type { GuidedOptions, GuidedState, Phase } from "../../api/contracts";
import { Section } from "../../ui/Section";
import { FieldRow } from "../../ui/FieldRow";
import { ActionList } from "../../ui/ActionList";
import { EngineOptions } from "./EngineOptions";

export function TranslationOptions({ state, phase, values, disabled, change, fileActions }: {
  state: GuidedState; phase: Phase; values: GuidedOptions; disabled: boolean; fileActions: ReactNode;
  change: <K extends keyof GuidedOptions>(key: K, value: GuidedOptions[K]) => void;
}) {
  const behavior = phase === "variables" ? ["IGNORETLTEXT"] : ["IGNORETLTEXT", "PRESERVEORIGINAL", "FIXTEXTWRAP", "BRFLAG",
    ...(phase === "database" ? ["TLSYSTEMVARIABLES", "TLSYSTEMSWITCHES"] : [])];
  const widthKeys = phase === "database" ? ["listWidth", "noteWidth"] as const
    : phase === "dialogue" ? ["width", "faceWidth"] as const : phase === "advanced" ? ["width", "noteWidth"] as const : [];
  const labels = { width: "Dialogue", faceWidth: "With portrait", listWidth: "List / help", noteWidth: "Notes" };
  return <>
    <Section title="Translation behavior"><EngineOptions inlineBooleans state={state} values={values.engine_options} keys={behavior} disabled={disabled}
      change={(key, value) => change("engine_options", { ...values.engine_options, [key]: value })} /></Section>
    {!!widthKeys.length && <details className="translation-width-options"><summary>Text wrapping limits</summary><fieldset disabled={disabled}>
      {widthKeys.map(key => <FieldRow key={key} id={`translation-width-${key}`} label={labels[key]}>{props => <input {...props} type="number" min={20}
        max={key === "faceWidth" ? values.widths.width : 300} value={values.widths[key]}
        onChange={event => change("widths", { ...values.widths, [key]: Number(event.target.value) })} />}</FieldRow>)}
    </fieldset></details>}
    <Section title="Selected working files"><ActionList compact>{fileActions}</ActionList></Section>
  </>;
}
