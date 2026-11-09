import { api } from "../../api/client";
import type { CompareOperation } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { ActionControl } from "../../ui/ActionControl";
import { Notice } from "../../ui/Notice";
import { StatusIcon } from "../../ui/StatusIcon";
import type { RunningComparison } from "./compareView";

/**
 * A running comparison's status and its Stop, which keeps what its models
 * finished. Once a stop is asked for, the status says so and Stop goes, so
 * one indicator shows the one state; a refused stop keeps Stop with why.
 */
function useStop(projectId: string, operation: CompareOperation) {
  const application = useApplication();
  const stop = useAction({ observer: application });
  const stopping = stop.busy || operation.stopping;
  return {
    stopping,
    control: !stopping && (
      <ActionControl
        label="Stop"
        inline
        error={stop.error}
        onClick={() =>
          void stop.run(() => api.compare.stop(projectId, operation.id))
        }
      />
    ),
  };
}

/** The footer's one status line while a comparison runs, then its Stop. */
export function RunningStatus({
  projectId,
  operation,
  text,
}: {
  projectId: string;
  operation: CompareOperation;
  /** What it does (runningStatus). */
  text: string;
}) {
  const { stopping, control } = useStop(projectId, operation);
  return (
    <>
      <div className="compare-run-status" role="status">
        <StatusIcon status="active" size={15} />
        <span>{stopping ? "Stopping the comparison…" : text}</span>
      </div>
      {control}
    </>
  );
}

/**
 * The comparison running for this game, with its Stop, where the page has
 * no footer to show it: before its lines are read, or with the game folder
 * missing. The app's other work waits for it, so it says so.
 */
export function RunningNotice({
  projectId,
  running,
}: {
  projectId: string;
  running: RunningComparison;
}) {
  const { stopping, control } = useStop(projectId, running.operation);
  return (
    <Notice>
      <span className="compare-running">
        <StatusIcon status="active" size={14} />
        <span>
          {stopping
            ? "Stopping the comparison…"
            : `${running.text}. ${running.waits}`}
        </span>
      </span>
      {control}
    </Notice>
  );
}
