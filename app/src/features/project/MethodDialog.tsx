import { useState } from "react";
import type { Project, TranslationMethod } from "../../api/contracts";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { engineLabel } from "../../ui/displayText";
import { Modal } from "../../ui/Modal";
import { OptionCards } from "../../ui/OptionCards";
import { PathText } from "../../ui/PathText";

export const methodLabels: Record<TranslationMethod, string> = {
  guided: "Guided steps",
  len: "Assistant-led",
  manual: "Manual",
};
export const guidedEngines = ["MVMZ", "ACE"];
const methods: TranslationMethod[] = ["guided", "len", "manual"];

/**
 * Chooses how a game is translated. A new game asks once; the Project page
 * can switch later, and the other method's saved work stays for a switch back.
 */
export function MethodDialog({
  project,
  busy,
  choose,
  close,
}: {
  project: Project;
  busy: boolean;
  choose: (method: TranslationMethod) => void;
  close: () => void;
}) {
  const guidedSupported = guidedEngines.includes(project.engine);
  const recommended: TranslationMethod = guidedSupported ? "guided" : "len";
  const current = project.method;
  // Changing starts on the first other method the game can use; a first
  // choice on the recommended one.
  const [method, setMethod] = useState<TranslationMethod>(
    current
      ? methods.find(
          (other) =>
            other !== current && (other !== "guided" || guidedSupported),
        )!
      : recommended,
  );
  // The current method is marked and can't be chosen again.
  const badge = (value: TranslationMethod) =>
    value === current
      ? "Current"
      : value === recommended
        ? "Recommended"
        : undefined;
  return (
    <Modal
      label="Choose a translation method"
      size="md"
      dismissible={!busy}
      onDismiss={close}
    >
      <DialogHeader
        title={`Translate ${project.name}`}
        description={
          <span className="path-line">
            <span>{engineLabel(project.engine_label || project.engine)} ·</span>
            <PathText path={project.source} />
          </span>
        }
      />
      <DialogBody>
        <OptionCards
          label="Translation method"
          value={method}
          autoFocus
          disabled={busy}
          onChange={setMethod}
          options={[
            {
              value: "guided",
              title: methodLabels.guided,
              badge: badge("guided"),
              disabled: !guidedSupported || current === "guided",
              description: guidedSupported
                ? "Prepare, translate, apply and release in stages, with an estimate before any paid work."
                : "Available for RPG Maker MV, MZ and Ace games.",
            },
            {
              value: "len",
              title: methodLabels.len,
              badge: badge("len"),
              disabled: current === "len",
              description:
                "Your coding assistant translates through the app from one starting prompt, using Len's game-translation skills. Any engine.",
            },
            {
              value: "manual",
              title: methodLabels.manual,
              badge: badge("manual"),
              disabled: current === "manual",
              description:
                "Your own tools extract the text into a file and write it back; DazedTL translates the file with your API key. Any engine.",
            },
          ]}
        />
      </DialogBody>
      <ActionBar
        feedback={
          <span className="method-note">
            {current
              ? `Your ${methodLabels[current]} work stays and returns if you switch back.`
              : "You can change this later on the Project page."}
          </span>
        }
      >
        <Button disabled={busy} onClick={close}>
          Cancel
        </Button>
        <Button variant="primary" pending={busy} onClick={() => choose(method)}>
          {current
            ? `Switch to ${methodLabels[method]}`
            : `Start with ${methodLabels[method]}`}
        </Button>
      </ActionBar>
    </Modal>
  );
}
