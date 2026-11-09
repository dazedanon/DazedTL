/**
 * Start over for text QA, in both methods' Text QA panel: its task and
 * review notes go aside, and the next task reviews every line.
 */

import { useState } from "react";
import { api } from "../../api/client";
import type { PlaytestState, QaState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { flushDrafts } from "../../state/leaveGuards";
import { useAction } from "../../state/useAction";
import { useMinute } from "../../state/useMinute";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { plural, timeAgo } from "../../ui/displayText";
import { Feedback } from "../../ui/Feedback";
import { CheckField } from "../../ui/FieldRow";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";
import { qaStartOver } from "./qaView";

export function QaStartOver({
  projectId,
  qa,
  playtest,
  focus,
  restorable,
  disabled,
}: {
  projectId: string;
  qa: QaState;
  playtest?: PlaytestState | null;
  /** The page offers QA's focus before it starts. */
  focus: boolean;
  /** History on the Project page can restore QA's batches. */
  restorable: boolean;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <p className="qa-start-over">
        <Button
          variant="link"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          Start over…
        </Button>
      </p>
      {open && (
        <QaStartOverDialog
          projectId={projectId}
          qa={qa}
          playtest={playtest}
          focus={focus}
          restorable={restorable}
          close={() => setOpen(false)}
        />
      )}
    </>
  );
}

function QaStartOverDialog({
  projectId,
  qa,
  playtest,
  focus,
  restorable,
  close,
}: {
  projectId: string;
  qa: QaState;
  playtest?: PlaytestState | null;
  focus: boolean;
  restorable: boolean;
  close: () => void;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const now = useMinute();
  const [clear, setClear] = useState(true);
  const notes = qaStartOver(qa, playtest, now);
  return (
    <Modal
      label="Start Text QA over"
      size="sm"
      dismissible={!action.busy}
      onDismiss={close}
    >
      <DialogHeader title="Start Text QA over?" />
      <DialogBody>
        <p>
          DazedTL sets this QA task aside and clears its review notes from the
          game folder. Your assistant then reviews every line again from the
          start{focus ? ", in the focus you choose" : ""}.
        </p>
        {notes.applied > 0 && (
          <p className="muted">
            Corrections QA already applied stay in the game
            {restorable ? "; History on the Project page can undo them." : "."}
          </p>
        )}
        {notes.active && (
          <Notice tone="warning">
            This task was last worked on {timeAgo(notes.active, now)}. If your
            assistant is still on it, stop its session first; DazedTL can&apos;t
            stop it.
          </Notice>
        )}
        {notes.playtest !== null && (
          <CheckField
            id="qa-start-over-playtest"
            label="Clear playtest results"
            description={
              (notes.playtest
                ? `The ${plural(notes.playtest, "problem")} it found ${notes.playtest === 1 ? "goes" : "go"} too`
                : "Its report goes too") +
              ", and the next QA run plays the game again."
            }
            checked={clear}
            disabled={action.busy}
            onChange={setClear}
          />
        )}
      </DialogBody>
      <ActionBar
        feedback={
          action.busy ? (
            <Feedback loading loadingText="Starting over…" />
          ) : (
            action.error && <Feedback error={action.error} />
          )
        }
      >
        <Button data-autofocus disabled={action.busy} onClick={close}>
          Cancel
        </Button>
        <Button
          variant="danger"
          disabled={action.busy}
          onClick={() =>
            void action.run(async () => {
              await flushDrafts();
              await api.guided.qaStartOver(
                projectId,
                notes.playtest !== null && clear,
              );
              close();
            })
          }
        >
          Start over
        </Button>
      </ActionBar>
    </Modal>
  );
}
