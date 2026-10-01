import { useState } from "react";
import type { Documents } from "../api/contracts";
import { Button } from "./Button";

const title = (name: string) =>
  ({
    glossary: "Glossary",
    game: "Game context",
    quirks: "Translation quirks",
  })[name] || name.replace("custom:", "Skill: ");

export function DocumentEditor({
  documents,
  drafts,
  disabled,
  edit,
  save,
  discard,
}: {
  documents: Documents;
  drafts: Documents;
  disabled: boolean;
  edit: (name: string, text: string, revision: string) => void;
  save: (name: string) => void;
  discard: (name: string) => void;
}) {
  const [name, setName] = useState("glossary");
  const document = drafts[name] || documents[name];
  return (
    <fieldset disabled={disabled}>
      <label>
        Document
        <select value={name} onChange={(event) => setName(event.target.value)}>
          {Object.keys(documents).map((key) => (
            <option key={key} value={key}>
              {title(key)}
              {drafts[key] ? " · Draft" : ""}
            </option>
          ))}
        </select>
      </label>
      {document && (
        <>
          <textarea
            aria-label="Game context text"
            rows={16}
            value={document.text}
            onChange={(event) =>
              edit(name, event.target.value, document.revision)
            }
          />
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
        </>
      )}
      {!!Object.keys(drafts).length && (
        <p className="footnote">
          Drafts are saved for recovery. Save or discard them before starting
          work.
        </p>
      )}
    </fieldset>
  );
}
