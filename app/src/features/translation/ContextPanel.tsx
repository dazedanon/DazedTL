import { useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useLanguages } from "../../app/LanguagesProvider";
import {
  guidanceFileFormats,
  guidanceFormats,
} from "../guided/guidanceFormats";
import { documentNames } from "../../state/documentState";
import { useAction } from "../../state/useAction";
import { useDocumentDraft } from "../../state/useDocumentDraft";
import {
  saveKey,
  shortcutKeys,
  shortcutLabel,
  useShortcut,
} from "../../state/useShortcut";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { DocumentEditor } from "../../ui/DocumentEditor";
import { Feedback } from "../../ui/Feedback";
import { PageBody } from "../../ui/PageLayout";
import { HelpPopover } from "../../ui/HelpPopover";
import { useDocumentsSave } from "../../ui/useDocumentsSave";
import { checkoutRefusal } from "./checkout";

export function ContextPanel({
  state,
  copy,
}: {
  state: TranslationState;
  /** The page's copy control, demoted while this editor has a draft. */
  copy: (variant: "primary" | "default") => ReactNode;
}) {
  const application = useApplication();
  const languages = useLanguages();
  const action = useAction({ observer: application });
  const draft = useDocumentDraft(
    "translation-context:" + state.projectId,
    state.drafts.documents,
    action.report,
    {
      persist: (value) =>
        api.translation.draft(state.projectId, "documents", value),
      // This editor saves one document at a time.
      save: (documents) => {
        const [[name, { revision, text }]] = Object.entries(documents);
        return api.translation.document(state.projectId, name, revision, text);
      },
    },
  );
  const saver = useDocumentsSave({
    documents: state.documents,
    draft,
    action,
    label: "Context",
  });
  const [selected, setSelected] = useState("glossary");
  const names = documentNames(state.documents, draft.drafts);
  const name = names.includes(selected) ? selected : names[0] || selected;
  const dirty = !!draft.drafts[name];
  const disabled = state.active || action.busy || draft.committing;
  const document = state.documents[name];
  const refused =
    document?.state === "unreadable"
      ? `DazedTL can't read ${document.file}.`
      : checkoutRefusal(state);
  const save = () => saver.save([name]);
  const body = useRef<HTMLDivElement>(null);
  useShortcut(saveKey, dirty && !disabled && !refused ? save : null, body, {
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
        <DocumentEditor
          documents={state.documents}
          drafts={draft.drafts}
          edit={draft.edit}
          disabled={disabled}
          selectedName={name}
          select={setSelected}
          placeholders={guidanceFormats(languages.source)}
          formats={guidanceFileFormats}
        />
      </PageBody>
      <ActionBar
        feedback={
          // A failed save, such as one waiting for the original game files
          // to be recorded, shows beside Save context.
          <Feedback
            error={action.error}
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
        <ActionControl
          label="Save context"
          variant={dirty ? "primary" : "default"}
          title={`Save context (${shortcutLabel.save})`}
          aria-keyshortcuts={shortcutKeys.save}
          disabled={disabled || !dirty || !!refused}
          disabledReason={dirty ? refused : ""}
          onClick={save}
        />
        {copy(dirty ? "default" : "primary")}
      </ActionBar>
      {saver.dialog}
    </>
  );
}
