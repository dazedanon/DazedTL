import { useState } from "react";
import type { Documents } from "../api/contracts";
import { savedMessage, unreadableLeftOut } from "../state/documentState";
import type { useAction } from "../state/useAction";
import type { useDocumentDraft } from "../state/useDocumentDraft";
import { DocumentsChangedDialog } from "./DocumentsChangedDialog";

/**
 * Save for guidance documents, the same in every method. A document whose
 * file DazedTL can't read is left out, its draft kept, and the others save;
 * when a file changed on disk since its draft began, Save first asks to
 * keep the file, discarding the draft, or the draft, saved over the file.
 * The message says what the save did.
 */
export function useDocumentsSave({
  documents,
  draft,
  action,
  label,
  whole = false,
  actionKey = "",
}: {
  documents: Documents;
  draft: ReturnType<typeof useDocumentDraft>;
  action: ReturnType<typeof useAction>;
  /** The tab that saves them, which its messages name. */
  label: "Context" | "Guidance";
  /** Save sends the whole set, so it runs without a draft too, creating
   * the documents Save creates even empty. */
  whole?: boolean;
  actionKey?: string;
}) {
  const [asking, setAsking] = useState<{
    names: string[];
    changed: string[];
    skipped: string[];
  } | null>(null);
  async function finish(
    names: string[],
    discarded: string[],
    skipped: string[],
  ) {
    const result = await action.run(
      async () => {
        for (const name of discarded) await draft.discard(name);
        return names.length || whole ? draft.save(names) : null;
      },
      "",
      actionKey,
    );
    if (result.ok)
      action.succeed(
        savedMessage(label, result.value, discarded, skipped, documents),
        actionKey,
      );
  }
  function save(names: string[]) {
    const skipped = unreadableLeftOut(documents, draft.drafts, names, whole);
    const chosen = names.filter(
      (name) => documents[name]?.state !== "unreadable",
    );
    const changed = chosen.filter(
      (name) => !!draft.drafts[name] && !!documents[name]?.changed,
    );
    if (changed.length) setAsking({ names: chosen, changed, skipped });
    else void finish(chosen, [], skipped);
  }
  const dialog = asking && (
    <DocumentsChangedDialog
      documents={documents}
      drafts={draft.drafts}
      names={asking.changed}
      busy={action.busy}
      cancel={() => setAsking(null)}
      keepFiles={() => {
        setAsking(null);
        void finish(
          asking.names.filter((name) => !asking.changed.includes(name)),
          asking.changed,
          asking.skipped,
        );
      }}
      keepDrafts={() => {
        setAsking(null);
        draft.rebase(asking.changed, documents);
        void finish(asking.names, [], asking.skipped);
      }}
    />
  );
  return { save, dialog };
}
