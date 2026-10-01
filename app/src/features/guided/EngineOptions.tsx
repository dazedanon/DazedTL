import type { EngineValue, GuidedState } from "../../api/contracts";
import { FieldRow } from "../../ui/FieldRow";

export function EngineOptions({ state, values, change, keys, disabled }: {
  state: GuidedState; values: Record<string, EngineValue>; change: (key: string, value: EngineValue) => void;
  keys: readonly string[]; disabled: boolean;
}) {
  return <fieldset disabled={disabled} className="guided-engine-options">
    {state.engineSchema.filter((field) => keys.includes(field.key)).map((field) => <FieldRow key={field.key} id={"guided-option-" + field.key} label={field.label}>
      {(props) => field.type === "boolean" ? <input {...props} type="checkbox" checked={values[field.key] === true}
        onChange={(event) => change(field.key, event.target.checked)} /> : field.type === "choices" ?
        <div className="guided-choices">{field.choices?.map((choice) => <label className="toggle" key={choice}>
          <input type="checkbox" checked={Array.isArray(values[field.key]) && (values[field.key] as string[]).includes(choice)}
            onChange={(event) => {
              const current = Array.isArray(values[field.key]) ? values[field.key] as string[] : [];
              change(field.key, event.target.checked ? [...current, choice] : current.filter((item) => item !== choice));
            }} />{choice}
        </label>)}</div> : <input {...props} type={field.type === "integer" ? "number" : "text"}
          value={String(values[field.key] ?? "")} min={field.min} max={field.max}
          onChange={(event) => change(field.key, field.type === "integer" ? Number(event.target.value) : event.target.value)} />}
    </FieldRow>)}
  </fieldset>;
}
