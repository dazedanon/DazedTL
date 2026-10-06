import { useState } from "react";
import type {
  GuidedState,
  Job,
  Phase,
  TranslationState,
} from "../../api/contracts";
import { ActionBar } from "../../ui/ActionBar";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { ActivityHistory } from "./ActivityHistory";
import { historyPhaseLabels } from "./historyView";

/** One stage's runs over its task; Inspect opens on top and returns here. */
export function RunHistorySheet({
  state,
  translation,
  phase,
  inspect,
  close,
}: {
  state: GuidedState;
  translation: TranslationState;
  phase: Phase;
  inspect: (job: Job) => void;
  close: () => void;
}) {
  const [footer, setFooter] = useState<HTMLElement | null>(null);
  return (
    <Modal
      label="Run history"
      size="full"
      className="run-history-sheet"
      onDismiss={close}
    >
      <DialogHeader
        title={`${historyPhaseLabels[phase] || "Translation"} · Run history`}
        onClose={close}
      />
      <DialogBody className="history-host-body">
        <ActivityHistory
          state={state}
          translation={translation}
          inspect={inspect}
          phase={phase}
          footerTarget={footer}
        />
      </DialogBody>
      <ActionBar
        feedback={<div ref={setFooter} className="history-host-footer" />}
      >
        {null}
      </ActionBar>
    </Modal>
  );
}
