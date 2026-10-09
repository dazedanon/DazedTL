import { useState } from "react";
import { api } from "../../api/client";
import type { TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { flushDrafts } from "../../state/leaveGuards";
import { useAction } from "../../state/useAction";
import { useMinute } from "../../state/useMinute";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { timeAgo } from "../../ui/displayText";
import { Feedback } from "../../ui/Feedback";
import { JobStatus } from "../../ui/JobStatus";
import { CheckField } from "../../ui/FieldRow";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";
import { PathText } from "../../ui/PathText";

/** An assistant this recent may still be working in the game folder. */
const RECENT_MINUTES = 15;

/**
 * Starts an Assistant-led project over: the original game files come back,
 * the attempt moves to .dazedtl/archived, and the next starting prompt
 * begins again from preparation.
 */
export function StartOver({
  state,
  activity,
  available,
}: {
  state: TranslationState;
  /** The assistant's latest report or helper call. */
  activity?: string;
  /** Whether an attempt exists to start over; an open dialog stays to
   * report its result after the attempt is gone. */
  available: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {available && (
        <Button variant="link" onClick={() => setOpen(true)}>
          Start over…
        </Button>
      )}
      {open && (
        <StartOverDialog
          state={state}
          activity={activity}
          close={() => setOpen(false)}
        />
      )}
    </>
  );
}

function StartOverDialog({
  state,
  activity,
  close,
}: {
  state: TranslationState;
  activity?: string;
  close: () => void;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const now = useMinute();
  const [keepContext, setKeepContext] = useState(true);
  const [jobId, setJobId] = useState("");
  const job = state.jobs.find((item) => item.id === jobId);
  const running = !!job && ["ready", "running", "waiting"].includes(job.status);
  const done = job?.status === "complete";
  const busy = action.busy || running;
  const failure =
    action.error ||
    (job && ["failed", "interrupted", "stopped"].includes(job.status)
      ? job.message
      : "");
  const paidRun = state.jobs.some(
    (item) =>
      item.kind === "translation" &&
      ["running", "waiting", "uncertain"].includes(item.status),
  );
  const recent =
    activity && now - Date.parse(activity) < RECENT_MINUTES * 60_000;
  const archive =
    typeof job?.result?.archive === "string" ? job.result.archive : "";
  return (
    <Modal label="Start over" size="sm" dismissible={!busy} onDismiss={close}>
      <DialogHeader title={done ? "Started over" : "Start over?"} />
      {done ? (
        <DialogBody>
          <p>
            {state.lifecycle.source_backup
              ? "The original game files are back. "
              : ""}
            The earlier attempt is in <PathText path={archive} wrap />.
          </p>
          <p>Copy the starting prompt to begin again.</p>
        </DialogBody>
      ) : (
        <DialogBody>
          <p>
            {state.lifecycle.source_backup
              ? "DazedTL puts back the original game files and moves your assistant's work and the game's Git history to .dazedtl/archived."
              : "DazedTL moves your assistant's work to .dazedtl/archived. The game has no original backup yet, so its files stay as they are."}{" "}
            The next starting prompt begins again from preparation.
          </p>
          <p className="muted">
            Backups, save games, Image Manager work and your options stay.
          </p>
          {paidRun && (
            <Notice tone="warning">
              Pause the API run first. Its paid work belongs to this attempt.
            </Notice>
          )}
          {recent && (
            <Notice tone="warning">
              Your assistant used DazedTL {timeAgo(activity, now)}. Stop its
              session first; DazedTL can&apos;t stop it.
            </Notice>
          )}
          <CheckField
            id="start-over-keep-context"
            label="Keep glossary and notes"
            checked={keepContext}
            disabled={busy}
            onChange={setKeepContext}
          />
        </DialogBody>
      )}
      <ActionBar
        feedback={
          done ? null : running ? (
            <JobStatus
              compact
              job={{
                label: "Start over",
                status: job.status,
                message: job.message,
              }}
            />
          ) : action.busy ? (
            <Feedback loading loadingText="Starting over…" />
          ) : (
            failure && <Feedback error={failure} />
          )
        }
      >
        {done ? (
          <Button variant="primary" data-autofocus onClick={close}>
            Close
          </Button>
        ) : (
          <>
            <Button data-autofocus disabled={busy} onClick={close}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={busy || paidRun}
              pending={busy}
              onClick={() =>
                void action.run(async () => {
                  await flushDrafts();
                  const started = await api.translation.startOver(
                    state.projectId,
                    keepContext,
                  );
                  setJobId(started.id);
                })
              }
            >
              Start over
            </Button>
          </>
        )}
      </ActionBar>
    </Modal>
  );
}
