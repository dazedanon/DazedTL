import { useState, type ComponentProps } from "react";

/**
 * A number typed freely and saved once it reads as one. While a minus sign or
 * an emptied field is half typed the field keeps it, rather than the store
 * turning it back into the last number; the saved value is held to the range
 * the renderer accepts, and to whole numbers where it counts them.
 * An emptied field leaves the saved number alone unless `empty` names the
 * number it stands for; the field itself reads empty until it loses focus.
 */
export function NumberInput({
  value,
  min,
  max,
  step = 1,
  whole = false,
  clamp = true,
  empty,
  onChange,
  ...input
}: Omit<
  ComponentProps<"input">,
  "type" | "value" | "min" | "max" | "step" | "onChange"
> & {
  value: number;
  min: number;
  max: number;
  step?: number;
  whole?: boolean;
  /** Hold the saved number to min and max; off for a limit the save reports. */
  clamp?: boolean;
  /** What an emptied field saves; without it the saved number stays. */
  empty?: number;
  onChange: (value: number) => void;
}) {
  const [typed, setTyped] = useState<string | null>(null);
  return (
    <input
      {...input}
      type="number"
      min={min}
      max={max}
      step={step}
      value={typed ?? String(value)}
      onChange={(event) => {
        setTyped(event.target.value);
        const number = event.target.valueAsNumber;
        if (Number.isFinite(number)) {
          const rounded = whole ? Math.round(number) : number;
          onChange(clamp ? Math.min(max, Math.max(min, rounded)) : rounded);
        } else if (event.target.value === "" && empty !== undefined)
          onChange(empty);
      }}
      onBlur={() => setTyped(null)}
    />
  );
}
