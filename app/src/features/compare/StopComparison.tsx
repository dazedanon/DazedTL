import { api } from "../../api/client";
import type { CompareOperation } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { ActionControl } from "../../ui/ActionControl";

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
