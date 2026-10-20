/**
 * Assistant-led release playtest: the starting prompt has the assistant run
 * it, and this tab shows its report; the user may run it again.
 */

import type { ReactNode } from "react";
import type { Job, PlaytestState } from "../../api/contracts";
import { api } from "../../api/client";
import type { useAction } from "../../state/useAction";
import { PlaytestWork } from "../guided/Playtest";
import { playtestFailure } from "../guided/playtestView";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { PageBody } from "../../ui/PageLayout";

export function PlaytestTab({
  projectId,
  playtest,
  job,
  action,
  disabled,
  waiting,
  copy,
}: {
  projectId: string;
  playtest: PlaytestState;
  /** The latest playtest started, running or finished. */
  job?: Job;
  action: ReturnType<typeof useAction>;
  disabled: boolean;
  /** The assistant is still at work, and plays the game again after its
   * fixes and QA's corrections. */
  waiting: boolean;
  /** The page's starting prompt. */
  copy: ReactNode;
}) {
  const running = job?.status === "running";
  const feedback = (key: string, pendingText: string) => ({
    feedbackKey: key,
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  return (
    <>
      <PageBody>
        <PlaytestWork
          projectId={projectId}
          playtest={playtest}
          running={running}
          progress={running ? job?.message : undefined}
          failed={playtestFailure(playtest, job)}
          rerun="Run it again, or your assistant runs it again as it finishes."
          waiting={waiting}
        />
      </PageBody>
      <ActionBar feedback={null}>
        {running ? (
          <ActionControl
            label="Stop playtest"
            disabled={action.busy}
            {...feedback("playtest-stop", "Stopping…")}
            onClick={() =>
              action.run(() => api.stop(projectId), "", "playtest-stop")
            }
          />
        ) : (
          <ActionControl
            label="Run playtest again"
            disabled={disabled}
            {...feedback("playtest", "Starting…")}
            onClick={() =>
              action.run(
                () => api.guided.playtest(projectId, "run"),
                "",
                "playtest",
              )
            }
          />
        )}
        {copy}
      </ActionBar>
    </>
  );
}
