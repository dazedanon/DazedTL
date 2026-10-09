import { api } from "../../api/client";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useMinute } from "../../state/useMinute";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { Section } from "../../ui/Section";
import { StatusHeading } from "../../ui/StatusMark";
import { timeAgo } from "../../ui/displayText";
import type { AssistantTaskView } from "./assistantTasks";

/** The Project page section the top bar's count opens. */
export const assistantTasksHeading = "assistant-tasks";

/** "Copied 14:02 · 47 min ago"; older copies give their date. */
function copied(since: string, now: number) {
  const at = new Date(since);
  const time =
    at.toDateString() === new Date(now).toDateString()
      ? at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : at.toLocaleDateString([], { month: "short", day: "numeric" });
  return `Copied ${time} · ${timeAgo(since, now)}`;
}

/**
 * Every task copied to a coding assistant that still needs it or you, in one
 * place. Finished and dismissed tasks leave; their results stay in their task.
 */
export function AssistantTaskList({
  projectId,
  tasks,
  busy,
  open,
}: {
  projectId: string;
  tasks: AssistantTaskView[];
  busy: boolean;
  open: (task: AssistantTaskView) => void;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const now = useMinute();
  if (!tasks.length) return null;
  return (
    <Section
      id={assistantTasksHeading}
      title="Assistant tasks"
      hint="The app only sees what your assistant saves."
      className="assistant-tasks"
    >
      <ActionList>
        {tasks.map((task) => {
          const key = "dismiss:" + task.kind;
          return (
            <ActionRow
              key={task.kind}
              label={
                <>
                  <StatusHeading state={task.state} title={task.title} />
                  <small>
                    {/* A reason reads as a sentence, so it comes last. */}
                    {[
                      task.since && copied(task.since, now),
                      task.place.label,
                      task.detail,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </>
              }
            >
              <ActionControl
                label="Dismiss"
                variant="quiet"
                disabled={busy || action.busy}
                pending={action.busy && action.key === key}
                pendingText="Dismissing…"
                error={action.key === key ? action.error : ""}
                onClick={() =>
                  void action.run(
                    () => api.dismissAssistantTask(projectId, task.kind),
                    "",
                    key,
                  )
                }
              />
              <Button disabled={busy} onClick={() => open(task)}>
                {task.state === "needs_review" ? "Review" : "Open"}
              </Button>
            </ActionRow>
          );
        })}
      </ActionList>
    </Section>
  );
}
