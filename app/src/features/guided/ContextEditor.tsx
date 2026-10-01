import type { Documents } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useContextDraft } from "./useContextDraft";
import { Message } from "../../ui/Feedback";
import { DocumentEditor } from "../../ui/DocumentEditor";

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
  const draft = useContextDraft(projectId, recovered, action.report);
  return (
    <section className="ui-section guided-context">
      <h2>Game context</h2>
      <p className="muted">
        These are the same glossary and game instructions used by the
        translation engine.
      </p>
      <Message message={action.error} onDismiss={action.clear} />
      <DocumentEditor
        documents={documents}
        drafts={draft.drafts}
        edit={draft.edit}
        disabled={disabled || action.busy || draft.committing}
        save={(name) => action.run(() => draft.save(name))}
        discard={(name) => action.run(() => draft.discard(name))}
      />
    </section>
  );
}
