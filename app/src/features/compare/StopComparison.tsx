import { api } from "../../api/client";
import type { CompareOperation } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { ActionControl } from "../../ui/ActionControl";
import { Notice } from "../../ui/Notice";
import { StatusIcon } from "../../ui/StatusIcon";
import type { RunningComparison } from "./compareView";

/** Stops a comparison operation, which keeps what its models finished. */
export function StopComparison({
  projectId,
  operation,
}: {
  projectId: string;
  operation: CompareOperation;
}) {
  const application = useApplication();
  const stop = useAction({ observer: application });
  return (
    <ActionControl
      label="Stop"
      inline
      pending={stop.busy || operation.stopping}
      pendingText="Stopping…"
      error={stop.error}
      onClick={() =>
        void stop.run(() => api.compare.stop(projectId, operation.id))
      }
    />
  );
}

/**
 * The comparison running for this game, with its Stop, where no footer
 * shows it (runPlace), since the app's other work waits for it.
 */
export function RunningNotice({
  projectId,
  running,
}: {
  projectId: string;
  running: RunningComparison;
}) {
  return (
    <Notice>
      <span className="compare-running">
        <StatusIcon status="active" size={14} />
        <span>
          {running.text}. {running.waits}
        </span>
      </span>
      <StopComparison projectId={projectId} operation={running.operation} />
    </Notice>
  );
}
