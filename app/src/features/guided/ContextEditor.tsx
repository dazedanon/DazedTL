import { useState } from "react";
import type { Documents } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useContextDraft } from "./useContextDraft";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";

const title = (name: string) =>
  ({
    glossary: "Glossary",
    game: "Game context",
    quirks: "Translation quirks",
  })[name] || name.replace("custom:", "Skill: ");
export default function ContextEditor({
  projectId,
  documents,
  recovered,
  disabled,
}: {
  projectId: string;
  documents: Documents;
  recovered: Documents;
  disabled: boolean;
}) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const { drafts, committing, edit, save, discard } = useContextDraft(
    projectId,
    recovered,
    action.report,
  );
  const [name, setName] = useState("glossary");
  const document = drafts[name] || documents[name];
  return (
    <section className="card">
      <h2>Game context</h2>
      <p className="muted">
        These are the same glossary and game instructions used by the
        translation engine.
      </p>
      <Message message={action.error} onDismiss={action.clear} />
      <fieldset disabled={disabled || action.busy || committing}>
        <label>
          Document
          <select
            value={name}
            onChange={(event) => setName(event.target.value)}
          >
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
              rows={12}
              value={document.text}
              onChange={(event) =>
                edit(name, event.target.value, document.revision)
              }
            />
            <div className="actions">
              <Button
                size="comfortable"
                variant="primary"
                disabled={!drafts[name]}
                onClick={() => action.run(() => save(name))}
              >
                Save context
              </Button>
              <Button
                size="comfortable"
                disabled={!drafts[name]}
                onClick={() => action.run(() => discard(name))}
              >
                Discard draft
              </Button>
            </div>
          </>
        )}
        {!!Object.keys(drafts).length && (
          <p className="footnote">
            Drafts are saved for recovery. Save or discard them before
            translating.
          </p>
        )}
      </fieldset>
    </section>
  );
}
