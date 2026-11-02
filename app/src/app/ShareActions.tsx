import { Bug, Wrench } from "lucide-react";
import type { Project } from "../api/contracts";
import type { ReportContext } from "../api/transport";
import { methodLabels } from "../features/project/MethodDialog";
import { useAction } from "../state/useAction";
import { Button } from "../ui/Button";
import { engineLabel } from "../ui/displayText";
import { GuideLink } from "../ui/GuideLink";

/**
 * The sidebar's copies for Discord, both naming the open game: Report a
 * problem copies a bug report, and Share a fix a task for the user's
 * assistant, which writes up a fix it made in the game. One line below them
 * says how the last copy went.
 */
export function ShareActions({ project }: { project?: Project | null }) {
  const action = useAction();
  const context: ReportContext = {
    game: project?.name,
    engine: project
      ? engineLabel(project.engine_label || project.engine)
      : undefined,
    mode: project?.method ? methodLabels[project.method] : undefined,
  };
  const copy = (
    key: "report" | "fix",
    write: (context: ReportContext) => Promise<void>,
    failure: string,
    notice: string,
  ) =>
    action.run(
      async () => {
        try {
          await write(context);
        } catch {
          throw new Error(failure);
        }
      },
      notice,
      key,
    );
  return (
    <>
      <Button
        variant="quiet"
        pending={action.busy && action.key === "report"}
        title="Copy a report for Discord with your version, system, game and recent errors filled in"
        onClick={() =>
          copy(
            "report",
            (context) => window.dazedtl.copyProblemReport(context),
            "The report could not be copied. Try again.",
            "Report copied.",
          )
        }
      >
        <Bug size={18} />
        Report a problem
      </Button>
      <Button
        variant="quiet"
        pending={action.busy && action.key === "fix"}
        title="Copy a task for your assistant to write up a fix you made in this game, to share on Discord"
        onClick={() =>
          copy(
            "fix",
            (context) => window.dazedtl.copyFixTask(context),
            "The task could not be copied. Try again.",
            "Task copied. Paste it into your assistant.",
          )
        }
      >
        <Wrench size={18} />
        Share a fix
      </Button>
      {(action.error || action.notice) && (
        <p
          className="sidebar-feedback"
          role={action.error ? "alert" : "status"}
        >
          {action.error || action.notice}
          {action.notice && action.key === "fix" && (
            <>
              {" "}
              <GuideLink section="contributing" />
            </>
          )}
        </p>
      )}
    </>
  );
}
