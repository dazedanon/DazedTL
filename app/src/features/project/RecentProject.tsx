/** A recent project's name over where its game is, as the Switch project
 * menu and the Project page's Recent projects list both show it; a game
 * whose folder is gone says so in the Project page's words instead, which
 * its game reads once opened (backend/dazedtl/projects/location.py). */
import type { Project } from "../../api/contracts";
import { unavailableReason } from "../../ui/displayText";
import { PathText } from "../../ui/PathText";
import { StatusIcon } from "../../ui/StatusIcon";

export function RecentProjectName({ project }: { project: Project }) {
  return (
    <span className="recent-project-name">
      <strong>{project.name}</strong>
      {project.available === false ? (
        // The row is short, so the way back and the old path show on hover.
        <small
          className="recent-project-unavailable"
          title={`${unavailableReason(project)}\n${project.source}`}
        >
          <StatusIcon status="warning" size={12} />
          {project.status}
        </small>
      ) : (
        <small>
          <PathText path={project.source} />
        </small>
      )}
    </span>
  );
}
