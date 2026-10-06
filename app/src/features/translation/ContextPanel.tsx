import { useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useDocumentDraft } from "../../state/useDocumentDraft";
import {
  saveKey,
  shortcutKeys,
  shortcutLabel,
  useShortcut,
} from "../../state/useShortcut";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { DocumentEditor } from "../../ui/DocumentEditor";
import { Feedback, Message } from "../../ui/Feedback";
import { PageBody } from "../../ui/PageLayout";
import { HelpPopover } from "../../ui/HelpPopover";

export function ContextPanel({
  state,
  copy,
}: {
  state: TranslationState;
  /** The page's copy control, demoted while this editor has a draft. */
  copy: (variant: "primary" | "default") => ReactNode;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
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
  const [selected, setSelected] = useState("glossary");
  const names = [
    ...new Set([...Object.keys(state.documents), ...Object.keys(draft.drafts)]),
  ];
  const name = names.includes(selected) ? selected : names[0] || selected;
  const dirty = !!draft.drafts[name];
  const disabled = state.active || action.busy || draft.committing;
  const save = () => void action.run(() => draft.save(name), "Context saved.");
  const body = useRef<HTMLDivElement>(null);
  useShortcut(saveKey, dirty && !disabled ? save : null, body, {
    inFields: true,
  });
  return (
    <>
      <PageBody ref={body} className="lens-context-body">
        <p className="muted lens-context-note">
          Names, voices and game context for every translation mode.{" "}
          <HelpPopover label="Context">
            These files and custom skills stay in the game&apos;s portable
            workspace. Each run keeps the exact context it used.
          </HelpPopover>
        </p>
        <Message message={action.error} onDismiss={action.clear} />
        <DocumentEditor
          documents={state.documents}
          drafts={draft.drafts}
          edit={draft.edit}
          disabled={disabled}
          selectedName={name}
          select={setSelected}
          focused
          fill
          showActions={false}
          save={(next) => void action.run(() => draft.save(next))}
          discard={(next) => void action.run(() => draft.discard(next))}
        />
      </PageBody>
      <ActionBar
        feedback={
          <Feedback
            pending={draft.committing}
            dirty={dirty}
            notice={action.notice}
          />
        }
      >
        {dirty && (
          <Button
            disabled={disabled}
            onClick={() => void action.run(() => draft.discard(name))}
          >
            Discard draft
          </Button>
        )}
        <Button
          variant={dirty ? "primary" : "default"}
          title={`Save context (${shortcutLabel.save})`}
          aria-keyshortcuts={shortcutKeys.save}
          disabled={disabled || !dirty}
          onClick={save}
        >
          Save context
        </Button>
        {copy(dirty ? "default" : "primary")}
      </ActionBar>
    </>
  );
}
