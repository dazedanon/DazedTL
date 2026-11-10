import { useState } from "react";
import type { Project, ToolFeedback } from "../../api/contracts";
import { reportContext } from "../../app/ShareActions";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { ActionRow } from "../../ui/ActionList";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";

const copied = "Copied. Paste it into DazedTL's Discord.";

/**
 * The tool feedback the assistant saved as a translation's last step, as a
 * row where each method's work ends: Assistant-led's Progress and Guided's
 * Release. View shows the exact text Copy for Discord and Save file give,
 * DazedTL's facts about the open game and then the feedback, which the main
 * process puts together as it does Share a fix's.
 */
export function ToolFeedbackRow({
  project,
  feedback,
}: {
  project: Project;
  feedback: ToolFeedback;
}) {
  const action = useAction();
  const [shown, setShown] = useState<string | null>(null);
  const shared = () =>
    window.dazedtl.toolFeedback(reportContext(project), feedback.text);
  const copy = (key: string) =>
    void action.run(
      async () => window.dazedtl.copyText(await shared()),
      copied,
      key,
    );
  const save = async () => {
    const result = await action.run(
      async () =>
        window.dazedtl.saveToolFeedback(
          `${project.name} tool feedback.md`,
          await shared(),
        ),
      "",
      "feedback-save",
    );
    // A cancelled save says nothing.
    if (result.ok && result.value)
      action.succeed(`Saved to ${result.value}.`, "feedback-save");
  };
  const view = () =>
    void action.run(async () => setShown(await shared()), "", "feedback-view");
  const control = (
    key: string,
    label: string,
    onClick: () => void,
    pendingText: string,
    variant?: "primary",
  ) => (
    <ActionControl
      label={label}
      variant={variant}
      disabled={action.busy}
      pending={action.busy && action.key === key}
      pendingText={pendingText}
      error={action.key === key ? action.error : ""}
      notice={action.key === key ? action.notice : ""}
      onClick={onClick}
    />
  );
  return (
    <>
      <ActionRow
        title="Tool feedback"
        description={`What your assistant thinks DazedTL could do better, to share on DazedTL's Discord · Saved ${new Date(feedback.savedAt).toLocaleString()}`}
      >
        {control("feedback-view", "View", view, "Opening…")}
        {control(
          "feedback-copy",
          "Copy for Discord",
          () => copy("feedback-copy"),
          "Copying…",
        )}
      </ActionRow>
      {shown !== null && (
        <Modal
          label="Tool feedback"
          size="lg"
          dismissible={!action.busy}
          onDismiss={() => setShown(null)}
        >
          <DialogHeader
            title="Tool feedback"
            description="What your assistant thinks DazedTL could do better, with your DazedTL version, system and game, ready to post on DazedTL's Discord."
            onClose={() => setShown(null)}
            closeDisabled={action.busy}
          />
          <DialogBody>
            <pre className="translation-report">{shown}</pre>
          </DialogBody>
          <ActionBar feedback={null}>
            {control(
              "feedback-save",
              "Save file",
              () => void save(),
              "Saving…",
            )}
            {control(
              "feedback-dialog-copy",
              "Copy for Discord",
              () => copy("feedback-dialog-copy"),
              "Copying…",
              "primary",
            )}
          </ActionBar>
        </Modal>
      )}
    </>
  );
}
