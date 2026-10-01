import { api } from "../../api/client";
import type { TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useDocumentDraft } from "../../state/useDocumentDraft";
import { DocumentEditor } from "../../ui/DocumentEditor";
import { Message } from "../../ui/Feedback";
import { Section } from "../../ui/Section";

export function ContextPanel({ state }: { state: TranslationState }) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const draft = useDocumentDraft(
    "translation-context:" + state.projectId,
    state.drafts.documents,
    action.report,
    {
      persist: (value) =>
        api.translation.draft(state.projectId, "documents", value),
      save: (name, revision, text) =>
        api.translation.document(state.projectId, name, revision, text),
    },
  );
  return (
    <Section
      title="Shared translation context"
      hint="Used by all three translation modes"
    >
      <p className="muted">
        Names, character voices, game context, and custom skills remain in the
        game's portable workspace. Each run retains the exact context it used.
      </p>
      <Message message={action.error} onDismiss={action.clear} />
      <DocumentEditor
        documents={state.documents}
        drafts={draft.drafts}
        edit={draft.edit}
        disabled={state.active || action.busy || draft.committing}
        save={(name) => action.run(() => draft.save(name))}
        discard={(name) => action.run(() => draft.discard(name))}
      />
    </Section>
  );
}
