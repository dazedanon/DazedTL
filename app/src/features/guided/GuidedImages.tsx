import type { ImageManagerState } from "../../api/imageContracts";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { Message } from "../../ui/Feedback";

export type ImageEntryMode = "discovery" | "manual" | "findings" | "review";

export function GuidedImages({
  state,
  error,
  busy,
  open,
  copy,
  refresh,
}: {
  state: ImageManagerState | null;
  error: string;
  busy: boolean;
  open: (mode: ImageEntryMode) => void;
  copy: () => void;
  refresh: () => void;
}) {
  const counts = state?.counts;
  return (
    <section className="guided-image-entry" aria-label="Image work">
      <div className="guided-image-summary">
        <span>
          {counts
            ? `${counts.indexed.toLocaleString()} indexed · ${counts.examined.toLocaleString()} examined · ${counts.notExamined.toLocaleString()} not examined`
            : "Image inventory is loading."}
        </span>
        <Button
          variant="quiet"
          disabled={busy || !state}
          onClick={() => open("manual")}
        >
          Choose images myself
        </Button>
      </div>
      <Message message={error} />
      {state?.supported === false && (
        <p className="muted">
          Image Manager supports MV/MZ images and loose PNG files. Ace archives
          need a separate extraction tool.
        </p>
      )}
      <ActionList>
        <ActionRow
          label={
            <>
              <strong>Find relevant images</strong>
              <small>
                Your assistant identifies images that need translation.
              </small>
            </>
          }
        >
          <Button
            variant="primary"
            disabled={busy || !state}
            onClick={() => open("discovery")}
          >
            Find images to translate
          </Button>
        </ActionRow>
        <ActionRow
          label={
            <>
              <strong>Choose image candidates</strong>
              <small>
                {counts
                  ? `${counts.recommended.toLocaleString()} recommended · ${counts.uncertain.toLocaleString()} uncertain`
                  : "Recommendations will appear with a saved discovery report."}
              </small>
            </>
          }
        >
          <Button
            disabled={busy || !counts?.examined}
            onClick={() => open("findings")}
          >
            Review image candidates
          </Button>
        </ActionRow>
        <ActionRow
          label={
            <>
              <strong>Edit selected images</strong>
              <small>
                {counts?.selected
                  ? `${counts.selected.toLocaleString()} selected in Image Manager${counts.selectedNotPrepared ? ` · ${counts.selectedNotPrepared} need editable copies` : ""}`
                  : "Choose images and make editable copies in Image Manager."}
              </small>
            </>
          }
        >
          <Button
            disabled={
              busy || !counts?.selected || !!counts?.selectedNotPrepared
            }
            onClick={copy}
          >
            Copy image task
          </Button>
          <Button disabled={busy || !state} onClick={refresh}>
            Refresh results
          </Button>
        </ActionRow>
        <ActionRow
          label={
            <>
              <strong>Apply reviewed results</strong>
              <small>Review the exact batch before changing game files.</small>
            </>
          }
        >
          <Button
            disabled={busy || !counts?.selectedReady}
            onClick={() => open("review")}
          >
            Review &amp; apply ({counts?.selectedReady || 0})
          </Button>
        </ActionRow>
      </ActionList>
      <p className="muted">
        {state?.discovery.lastReport
          ? `Last saved discovery report: ${new Date(state.discovery.lastReport).toLocaleString()}`
          : "No discovery report yet"}
        {state?.editing.lastReport
          ? ` · Last saved image report: ${new Date(state.editing.lastReport).toLocaleString()}`
          : ""}
      </p>
    </section>
  );
}
