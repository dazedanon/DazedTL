import type { EngineValue, EventTextState } from "../../api/contracts.ts";

export const selectorKeys = {
  CODE357: "ENABLED_PLUGINS_357",
  CODE355655: "ENABLED_PATTERNS_355655",
} as const;
export type SelectorKey = (typeof selectorKeys)[keyof typeof selectorKeys];
export type PickerFilter = "all" | "selected" | "recommended";
export interface SourceChoice {
  id: string;
  group: string;
  details: string;
}
export interface SourcePickerDraft {
  key: SelectorKey;
  selected: string[];
  baseline: string[];
  query: string;
  filter: PickerFilter;
}

/**
 * Current findings applied with every source off, saved and in the draft
 * `values`: the selected event files have no other event text to translate,
 * so the task needs no run.
 */
export const nothingToTranslate = (
  state: Pick<EventTextState, "status" | "applied" | "enabled" | "rows">,
  values: Record<string, EngineValue>,
) =>
  state.status === "ready" &&
  state.applied &&
  !state.enabled.length &&
  !state.rows.some((row) => values[row.key] === true);

export function filteredChoices(
  choices: SourceChoice[],
  selected: readonly string[],
  recommended: readonly string[],
  query: string,
  filter: PickerFilter,
) {
  const needle = query.trim().toLocaleLowerCase();
  const chosen = new Set(selected),
    advised = new Set(recommended);
  return choices.filter(
    (choice) =>
      (!needle ||
        (choice.id + " " + choice.group + " " + choice.details)
          .toLocaleLowerCase()
          .includes(needle)) &&
      (filter === "all" ||
        (filter === "selected" ? chosen : advised).has(choice.id)),
  );
}

export function toggleChoice(
  selected: readonly string[],
  id: string,
  checked: boolean,
) {
  return [
    ...new Set(
      checked ? [...selected, id] : selected.filter((value) => value !== id),
    ),
  ].sort();
}

export function sourceErrors(
  state: EventTextState,
  values: Record<string, EngineValue>,
) {
  const errors: string[] = [];
  for (const row of state.rows) {
    if (typeof values[row.key] !== "boolean")
      errors.push("Choose an enabled or disabled state for " + row.label + ".");
    if (row.selector) {
      const value = values[row.selector];
      if (
        !Array.isArray(value) ||
        value.some((id) => !row.choices.some((choice) => choice.id === id))
      )
        errors.push("Remove unsupported selections for " + row.label + ".");
      else if (
        values[row.key] &&
        !value.length &&
        !state.builtinHits[row.key]?.length
      )
        errors.push(
          "Select a registered handler or pattern for " +
            row.label +
            "; this scope has no built-in matches.",
        );
    }
  }
  if (values.CODE122) {
    const text = values.CODE122_VAR_RANGES;
    if (typeof text !== "string" || !text.trim())
      errors.push("Enter explicit variable IDs for 122.");
    else if (
      text.split(",").some((part) => {
        const match = /^(\d+)\s*(?:[-\u2013\u2014]\s*(\d+))?$/.exec(
          part.trim(),
        );
        return (
          !match ||
          Number(match[1]) > 99999 ||
          (match[2] &&
            (Number(match[2]) < Number(match[1]) || Number(match[2]) > 99999))
        );
      })
    )
      errors.push(
        "Use valid variable IDs and inclusive ranges between 0 and 99999.",
      );
  }
  return errors;
}
