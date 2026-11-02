import { Bug } from "lucide-react";
import type { Project } from "../api/contracts";
import { methodLabels } from "../features/project/MethodDialog";
import { useAction } from "../state/useAction";
import { Button } from "../ui/Button";
import { engineLabel } from "../ui/displayText";

export function ProblemReportAction({ project }: { project?: Project | null }) {
  const action = useAction();
  async function copy() {
    try {
      await window.dazedtl.copyProblemReport({
        game: project?.name,
        engine: project
          ? engineLabel(project.engine_label || project.engine)
          : undefined,
        mode: project?.method ? methodLabels[project.method] : undefined,
      });
    } catch {
      throw new Error("The report could not be copied. Try again.");
    }
  }
  return (
    <>
      <Button
        variant="quiet"
        pending={action.busy}
        title="Copy a report for Discord with your version, system, game and recent errors filled in"
        onClick={() => action.run(copy, "Report copied.")}
      >
        <Bug size={18} />
        Report a problem
      </Button>
      {(action.error || action.notice) && (
        <p
          className="sidebar-feedback"
          role={action.error ? "alert" : "status"}
        >
          {action.error || action.notice}
        </p>
      )}
    </>
  );
}
