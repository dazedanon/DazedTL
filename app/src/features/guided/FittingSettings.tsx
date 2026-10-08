/** What the line width check reads: text areas, event commands and row limits. */
import type { TextToolsForm } from "../../api/contracts";
import { CheckField, CheckGroup } from "../../ui/FieldRow";
import { HelpPopover } from "../../ui/HelpPopover";

const areas = [
  ["dialogue", "Dialogue"],
  ["face_dialogue", "Dialogue with portrait"],
  ["list", "List and help descriptions"],
  ["notes", "Supported note patterns"],
] as const;

/** The event commands the check can rewrap, named as Other event text names them. */
const commands = [
  [401, "Messages"],
  [405, "Scrolling text"],
  [122, "Variable assignments"],
  [324, "Nickname changes"],
  [325, "Profile changes"],
  [357, "MZ plugin commands"],
] as const;

/** The checked event codes; a blank list means every supported one. */
export function fittingCodes(codes: string): number[] {
  const parsed = codes
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map(Number);
  return parsed.length ? parsed : commands.map(([code]) => code);
}

const list = (names: string[]) =>
  new Intl.ListFormat("en", { type: "conjunction" }).format(names);

/** The settings in two short lines, for the task's summary row. */
export function fittingSummary(text: TextToolsForm, onlyOverflow: boolean) {
  const codes = fittingCodes(text.codes);
  const checked = areas.filter(([key]) => text.categories.includes(key));
  const events = commands
    .filter(([code]) => codes.includes(code))
    .map(([, name]) => name.toLowerCase());
  return [
    [
      checked.length === areas.length
        ? "All text areas"
        : list(checked.map(([, name]) => name)) || "No text areas",
      // Event commands only feed the dialogue areas.
      checked.some(([key]) => key === "dialogue" || key === "face_dialogue") &&
        (events.length === commands.length
          ? "every supported event command"
          : list(events)),
    ]
      .filter(Boolean)
      .join(" · "),
    [
      onlyOverflow ? "Only lines over their limit" : "Every line",
      text.protect_rows
        ? `skips fixed-size text that would need more than ${text.max_rows} rows`
        : "no row limit",
    ].join(" · "),
  ];
}

/** The settings sheet's fields; the form saves each change as it is made. */
export function FittingSettings({
  text,
  onlyOverflow,
  disabled,
  editText,
  editOnlyOverflow,
}: {
  text: TextToolsForm;
  onlyOverflow: boolean;
  disabled: boolean;
  editText: <K extends keyof TextToolsForm>(
    key: K,
    value: TextToolsForm[K],
  ) => void;
  editOnlyOverflow: (value: boolean) => void;
}) {
  const codes = fittingCodes(text.codes);
  return (
    <fieldset disabled={disabled}>
      <CheckGroup id="fitting-areas" label="Text areas">
        {areas.map(([key, label]) => (
          <CheckField
            key={key}
            id={`fitting-area-${key}`}
            label={label}
            checked={text.categories.includes(key)}
            onChange={(checked) =>
              editText(
                "categories",
                checked
                  ? [...text.categories, key]
                  : text.categories.filter((value) => value !== key),
              )
            }
          />
        ))}
      </CheckGroup>
      <CheckGroup
        id="fitting-commands"
        label="Event commands"
        help="Choices, custom windows and other plugin text are outside this check."
      >
        {commands.map(([code, name]) => (
          <CheckField
            key={code}
            id={`fitting-code-${code}`}
            label={`${name} (${code})`}
            checked={codes.includes(code)}
            // A blank list means every command, so the last one stays on.
            disabled={codes.length === 1 && codes.includes(code)}
            onChange={(checked) =>
              editText(
                "codes",
                commands
                  .map(([value]) => value)
                  .filter((value) =>
                    value === code ? checked : codes.includes(value),
                  )
                  .join(","),
              )
            }
          />
        ))}
      </CheckGroup>
      <CheckGroup id="fitting-rewrap" label="Rewrap" stacked>
        <CheckField
          id="fitting-only-overflow"
          label="Only lines wider than their limit"
          checked={onlyOverflow}
          onChange={editOnlyOverflow}
        />
        <div className="check-field">
          <input
            id="fitting-protect-rows"
            type="checkbox"
            checked={text.protect_rows}
            onChange={(event) => editText("protect_rows", event.target.checked)}
          />
          <label htmlFor="fitting-protect-rows">
            Skip fixed-size text that would need more than
          </label>
          <input
            type="number"
            className="inline-number"
            aria-label="Row limit"
            min={1}
            max={100}
            value={text.max_rows}
            disabled={!text.protect_rows}
            onChange={(event) => {
              const value = Number(event.target.value);
              if (Number.isInteger(value) && value >= 1 && value <= 100)
                editText("max_rows", value);
            }}
          />
          <span>rows</span>
          <HelpPopover label="Fixed-size text">
            Descriptions, profiles, scrolling text and plugin text show in a
            window of fixed height. Messages continue in a new window, so they
            are never skipped.
          </HelpPopover>
        </div>
      </CheckGroup>
    </fieldset>
  );
}
