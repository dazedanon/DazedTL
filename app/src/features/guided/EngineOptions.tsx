import type { EngineValue, GuidedState } from "../../api/contracts";
import { FieldRow } from "../../ui/FieldRow";

export function EngineOptions({ state, values, change, keys, disabled, dependencies = {}, collapseChoices = false, inlineBooleans = false, descriptions = {} }: {
  state: GuidedState; values: Record<string, EngineValue>; change: (key: string, value: EngineValue) => void;
  keys: readonly string[]; disabled: boolean; dependencies?: Record<string, string>; collapseChoices?: boolean; inlineBooleans?: boolean;
  descriptions?: Record<string, { label: string; help: string }>;
}) {
  return <fieldset disabled={disabled} className={`guided-engine-options${inlineBooleans ? " guided-engine-options--inline" : ""}`}>
    {keys.flatMap((key) => state.engineSchema.filter((field) => field.key === key)).map((field) => {
      if (inlineBooleans && field.type === "boolean") return <label key={field.key} className="guided-option-toggle">
        <input type="checkbox" checked={values[field.key] === true} disabled={!!dependencies[field.key] && values[dependencies[field.key]] !== true}
          onChange={event => change(field.key, event.target.checked)} />{field.label}
      </label>;
      const description = descriptions[field.key];
      const control = <FieldRow key={field.key} id={"guided-option-" + field.key} label={description?.label || field.label} help={description?.help} helpDisplay="popover">
      {(props) => field.type === "boolean" ? <input {...props} type="checkbox" checked={values[field.key] === true}
        disabled={!!dependencies[field.key] && values[dependencies[field.key]] !== true}
        onChange={(event) => change(field.key, event.target.checked)} /> : field.type === "choices" ?
        <div className="guided-choices">{field.choices?.map((choice) => <label className="toggle" key={choice}>
          <input type="checkbox" disabled={!!dependencies[field.key] && values[dependencies[field.key]] !== true} checked={Array.isArray(values[field.key]) && (values[field.key] as string[]).includes(choice)}
            onChange={(event) => {
              const current = Array.isArray(values[field.key]) ? values[field.key] as string[] : [];
              change(field.key, event.target.checked ? [...current, choice] : current.filter((item) => item !== choice));
            }} />{choice}
        </label>)}</div> : <input {...props} type={field.type === "integer" ? "number" : "text"}
          disabled={!!dependencies[field.key] && values[dependencies[field.key]] !== true}
          value={String(values[field.key] ?? "")} min={field.min} max={field.max}
          onChange={(event) => change(field.key, field.type === "integer" ? Number(event.target.value) : event.target.value)} />}
      </FieldRow>;
      return field.type === "choices" && collapseChoices ? <details key={field.key}><summary>{field.label}</summary>{control}</details> : control;
    })}
  </fieldset>;
}
