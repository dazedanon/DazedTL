import { useState, type ReactNode } from "react";
import type { Documents } from "../api/contracts";
import { Button } from "./Button";
import { Tabs } from "./Tabs";

const title = (name: string) =>
  ({
    glossary: "Glossary",
    game: "Game context",
    quirks: "Translation quirks",
  })[name] || name.replace("custom:", "Skill: ");

// The layout the engine reads from each guidance file, shown while it is empty.
const formats: Record<string, string> = {
  glossary:
    "# Game Characters\nアリス (Alice) - Female. The heroine; polite, formal speech.\n\n# Terms\n魔導書 (Grimoire)",
  quirks:
    "- Battle log and system messages stay in the third person.\n- ゴンベエ's ござる endings read as archaic samurai speech.",
  game: "世界観 (Theme / setting) - \n時代感 (Era / technology level) - \n文体方針 (Register policy) - \n固有名詞方針 (Naming policy) - ",
};

export function DocumentEditor({
  documents,
  drafts,
  disabled,
  edit,
  save,
  discard,
  names,
  selectedName,
  select,
  focused = false,
  fill = false,
  showActions = true,
  before,
  tabNames,
  tabLabel,
  titles,
}: {
  documents: Documents;
  drafts: Documents;
  disabled: boolean;
  edit: (name: string, text: string, revision: string) => void;
  save: (name: string) => void;
  discard: (name: string) => void;
  names?: string[];
  selectedName?: string;
  select?: (name: string) => void;
  focused?: boolean;
  fill?: boolean;
  showActions?: boolean;
  before?: (name: string) => ReactNode;
  tabNames?: string[];
  tabLabel?: (name: string) => ReactNode;
  titles?: Record<string, string>;
}) {
  const labelFor = (name: string) => titles?.[name] || title(name);
  const [current, setName] = useState("glossary");
  const available = (
    names || [...new Set([...Object.keys(documents), ...Object.keys(drafts)])]
  ).filter((name) => documents[name] || drafts[name]);
  const preferred = selectedName || current;
  const name = available.includes(preferred)
    ? preferred
    : available[0] || preferred;
  const document = drafts[name] || documents[name];
  return (
    <fieldset
      disabled={disabled}
      className={`document-editor${focused ? " document-editor--focused" : ""}${fill ? " document-editor--fill" : ""}`}
    >
      {focused ? (
        available.length > 1 && (
          <Tabs
            id="guidance-documents"
            label="Guidance documents"
            value={name}
            items={available
              .filter((key) => !tabNames || tabNames.includes(key))
              .map((key) => ({
                id: key,
                label: tabLabel
                  ? tabLabel(key)
                  : labelFor(key) + (drafts[key] ? " · Draft" : ""),
              }))}
            onChange={select || setName}
            disabled={disabled}
          />
        )
      ) : (
        <label>
          Document
          <select
            value={name}
            onChange={(event) => (select || setName)(event.target.value)}
          >
            {available.map((key) => (
              <option key={key} value={key}>
                {labelFor(key)}
                {drafts[key] ? " · Draft" : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {document && (
        <div
          className="document-editor-content"
          role={focused && available.length > 1 ? "tabpanel" : undefined}
          id={focused ? `guidance-documents-panel-${name}` : undefined}
          aria-labelledby={
            focused && available.length > 1
              ? `guidance-documents-tab-${name}`
              : undefined
          }
        >
          {before?.(name)}
          <textarea
            aria-label={
              focused ? labelFor(name) + " text" : "Game context text"
            }
            rows={fill ? 4 : focused ? 9 : 16}
            spellCheck={false}
            placeholder={formats[name]}
            value={document.text}
            onChange={(event) =>
              edit(name, event.target.value, document.revision)
            }
          />
          {showActions && (
            <div className="actions">
              <Button
                variant="primary"
                disabled={!drafts[name]}
                onClick={() => save(name)}
              >
                Save context
              </Button>
              <Button disabled={!drafts[name]} onClick={() => discard(name)}>
                Discard draft
              </Button>
            </div>
          )}
        </div>
      )}
      {showActions && !!Object.keys(drafts).length && (
        <p className="footnote">
          Drafts are saved for recovery. Save or discard them before starting
          work.
        </p>
      )}
    </fieldset>
  );
}
