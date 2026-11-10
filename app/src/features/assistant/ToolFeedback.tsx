import { useState } from "react";
import { Check } from "lucide-react";
import type { Project, ToolFeedback } from "../../api/contracts";
import { reportContext } from "../../app/ShareActions";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { FadingNote } from "../../ui/FadingNote";
import { Feedback } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";

/**
 * The tool feedback the assistant saved as a translation's last step, as a
 * row where each method's work ends: Assistant-led's Progress and Guided's
 * Release. View shows the exact text Copy for Discord and Save file give,
 * DazedTL's facts about the open game and then the feedback, which the main
 * process puts together as it does Share a fix's. A copy or save that went
 * well says so in a note that fades away, and a failure stays; neither
 * moves the buttons.
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
      "Copied. Paste it into DazedTL's Discord.",
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
  // The outcome of the actions in the row, or in the dialog while it shows:
  // a failure, which stays, or a note that fades away.
  const outcome = (keys: string[]) =>
    keys.includes(action.key) && !action.busy
      ? {
          error: action.error && <Feedback error={action.error} />,
          note: action.notice && (
            // A new copy clears the notice first, so its note mounts afresh.
            <FadingNote className="feedback" onGone={action.clear}>
              <Check size={15} className="feedback-mark" />
              {action.notice}
            </FadingNote>
          ),
        }
      : { error: null, note: null };
  const row = outcome(shown === null ? ["feedback-view", "feedback-copy"] : []);
  const dialog = outcome(["feedback-save", "feedback-dialog-copy"]);
  const button = (key: string, label: string, onClick: () => void) => (
    <Button
      disabled={action.busy}
      pending={action.busy && action.key === key}
      onClick={onClick}
    >
      {label}
    </Button>
  );
  return (
    <>
      <ActionRow
        name="Tool feedback"
        label={
          <>
            <strong>Tool feedback</strong>
            <span className="tool-feedback-detail">
              <small data-covered={row.note ? true : undefined}>
                What your assistant thinks DazedTL could do better, to share on
                DazedTL&apos;s Discord · Saved{" "}
                {new Date(feedback.savedAt).toLocaleString()}
              </small>
              {row.note}
            </span>
            {row.error}
          </>
        }
      >
        {button(
          "feedback-view",
          "View",
          () =>
            void action.run(
              async () => setShown(await shared()),
              "",
              "feedback-view",
            ),
        )}
        {button("feedback-copy", "Copy for Discord", () =>
          copy("feedback-copy"),
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
          <ActionBar feedback={dialog.error || dialog.note}>
            {button("feedback-save", "Save file", () => void save())}
            <Button
              variant="primary"
              disabled={action.busy}
              pending={action.busy && action.key === "feedback-dialog-copy"}
              onClick={() => copy("feedback-dialog-copy")}
            >
              Copy for Discord
            </Button>
          </ActionBar>
        </Modal>
      )}
    </>
  );
}
