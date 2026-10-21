import { useState, type ReactNode } from "react";
import { FolderOpen, MoreHorizontal } from "lucide-react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type {
  Checkpoint,
  CheckpointTimeline,
  Project,
  TranslationJob,
  TranslationState,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { flushDrafts } from "../../state/leaveGuards";
import { useAction } from "../../state/useAction";
import { useRead } from "../../state/useRead";
import { ActionControl, earlierSuccess } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Feedback, Message } from "../../ui/Feedback";
import { HelpPopover } from "../../ui/HelpPopover";
import { Menu, MenuItem, MenuSeparator } from "../../ui/Menu";
import { Modal } from "../../ui/Modal";
import { StatusIcon } from "../../ui/StatusIcon";
import { sentence } from "../../ui/displayText";
import { VersionChanges } from "../translation/VersionChanges";
import {
  blockedBy,
  changedFiles,
  day,
  fileName,
  plural,
  readKey,
  runs,
  when,
} from "./checkpoints";

type Operation = "checkpoint_back" | "checkpoint_undo" | "checkpoint_copy";
const operations: readonly string[] = [
  "checkpoint_back",
  "checkpoint_undo",
  "checkpoint_copy",
];
const pendingText: Record<Operation, string> = {
  checkpoint_back: "Going back…",
  checkpoint_undo: "Undoing…",
  checkpoint_copy: "Saving a copy…",
};

/**
 * Every change DazedTL made to the game, one checkpoint each, by game
 * version and stage; each can be viewed, gone back to, undone or saved as a
 * copy. The game update flow sits between the header and the list.
 */
export function CheckpointsPanel({
  project,
  state,
  update,
}: {
  project: Project;
  state: TranslationState;
  /** The game update flow, shown under the header. */
  update: ReactNode;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const [viewing, setViewing] = useState<Checkpoint | null>(null);
  const configured = !!state.git?.configured;
  const read = useRead(readKey(project.id, state.git), () =>
    api.translation.checkpoints(project.id),
  );
  // The last timeline stays in view while a newer one is read.
  const [shown, setShown] = useState<{
    project: string;
    value: CheckpointTimeline;
  } | null>(null);
  if (read.value && shown?.value !== read.value)
    setShown({ project: project.id, value: read.value });
  const timeline =
    read.value ?? (shown?.project === project.id ? shown.value : null);
  const updating =
    !!state.git?.pending_operations.length ||
    !!state.git?.asset_sync_pending ||
    state.jobs.some(
      (job) =>
        ["stage_update", "version_preview", "version_apply"].includes(
          job.action || "",
        ) && ["ready", "running", "waiting"].includes(job.status),
    );
  const busy =
    action.busy || state.active || !!application.snapshot?.application.running;
  const blocked = updating
    ? "Finish or cancel the game update first."
    : busy
      ? "Wait for the current work to finish."
      : "";
  // Only the newest go back, undo or copy reports, beside its checkpoint,
  // until the user starts another.
  const newest = state.jobs
    .filter(
      (job) =>
        job.kind === "operation" &&
        operations.includes(job.action || "") &&
        !earlierSuccess(job),
    )
    .sort((a, b) => b.created.localeCompare(a.created))[0];
  const reported =
    newest && (!action.key || action.key.endsWith(`:${newest.target}`))
      ? newest
      : undefined;
  const start = (operation: Operation, row: Checkpoint) =>
    action.run(
      async () => {
        await flushDrafts();
        let destination: string | undefined;
        if (operation === "checkpoint_copy") {
          destination = (await window.dazedtl.chooseFolder()) ?? undefined;
          if (!destination) return;
        }
        await api.translation.checkpoint(
          project.id,
          operation,
          row.commit,
          destination,
        );
      },
      "",
      `${operation}:${row.commit}`,
    );
  const current = timeline?.versions[0];
  const boundary = current?.checkpoints.find((row) => row.kind !== "change");
  return (
    <div className="checkpoints-panel">
      {configured && (
        <div className="checkpoints-head">
          <span className="checkpoints-label">Game version</span>
          <strong className="checkpoints-number">
            {timeline?.version || state.git?.original_version || "Not recorded"}
          </strong>
          {boundary && (
            <small>
              {boundary.kind === "update"
                ? `Updated ${day(boundary.time)}${boundary.release ? ` · ${boundary.release}` : ""}`
                : `Set up ${day(boundary.time)}`}
            </small>
          )}
          {timeline && (
            <span className="checkpoints-status" role="status">
              {timeline.outside.length ? (
                <>
                  <StatusIcon status="warning" size={14} />
                  {plural(timeline.outside.length, "file")} edited outside
                  DazedTL
                  <HelpPopover label="Edits made outside DazedTL">
                    They become their own checkpoint before DazedTL’s next
                    change, including a go back or undo, so they can be undone
                    too.
                  </HelpPopover>
                </>
              ) : (
                <>
                  <StatusIcon status="done" size={14} />
                  All changes saved
                  <HelpPopover label="Checkpoints">
                    Every change DazedTL makes to the game is saved here as a
                    checkpoint in the game folder’s Git. Edits made outside
                    DazedTL are saved too, before its next change.
                  </HelpPopover>
                </>
              )}
            </span>
          )}
          {!!timeline?.outside.length && (
            <small className="checkpoints-outside">
              {timeline.outside.length > 3
                ? `${timeline.outside.slice(0, 2).join(", ")} and ${timeline.outside.length - 2} more`
                : timeline.outside.join(", ")}
            </small>
          )}
        </div>
      )}
      {update}
      {configured && read.error && !timeline ? (
        <>
          <Message
            message={`Checkpoints could not be read: ${messageOf(read.error)}`}
          />
          <Button onClick={read.retry}>Try again</Button>
        </>
      ) : null}
      {timeline?.versions.map((version) => (
        <section
          key={version.version || "untracked"}
          className="checkpoints-version"
          aria-label={
            version.version ? `Version ${version.version}` : "Earlier changes"
          }
        >
          <div className="checkpoints-version-title">
            <h3>
              {version.version
                ? `Version ${version.version}`
                : "Earlier changes"}
            </h3>
            {!version.current && (
              <small>Earlier version: view or save a copy</small>
            )}
          </div>
          <ActionList>
            {runs(version.checkpoints).map((run) => (
              <div key={run.rows[0].commit} className="checkpoints-run">
                <div className="checkpoints-stage">
                  {run.group}
                  <span>· {plural(run.rows.length, "change")}</span>
                </div>
                {run.rows.map((row) => (
                  <CheckpointRow
                    key={row.commit}
                    row={row}
                    blocked={blocked}
                    pending={
                      action.busy &&
                      action.key.endsWith(`:${row.commit}`) &&
                      (action.key.split(":")[0] as Operation)
                    }
                    error={
                      action.key.endsWith(`:${row.commit}`) ? action.error : ""
                    }
                    job={reported?.target === row.commit ? reported : undefined}
                    start={(operation) => start(operation, row)}
                    view={() => setViewing(row)}
                  />
                ))}
              </div>
            ))}
          </ActionList>
        </section>
      ))}
      {timeline?.backups && (
        <p className="checkpoints-backups">
          Backups from before checkpoints stay in .dazedtl/backups.{" "}
          <ActionControl
            inline
            variant="link"
            label="Open folder"
            icon={<FolderOpen size={14} aria-hidden="true" />}
            disabled={action.busy}
            error={action.key === "backups" ? action.error : ""}
            onClick={() =>
              action.run(
                () => window.dazedtl.openFolder("output", timeline.backups!),
                "",
                "backups",
              )
            }
          />
        </p>
      )}
      {viewing && (
        <CheckpointChanges
          projectId={project.id}
          row={viewing}
          close={() => setViewing(null)}
        />
      )}
    </div>
  );
}

function CheckpointRow({
  row,
  blocked,
  pending,
  error,
  job: reported,
  start,
  view,
}: {
  row: Checkpoint;
  /** Why no checkpoint can be gone back to, undone or copied now. */
  blocked: string;
  pending: Operation | false;
  error: string;
  job?: TranslationJob;
  start: (operation: Operation) => void;
  view: () => void;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const job = reported;
  const running = !!job && ["ready", "running", "waiting"].includes(job.status);
  const result = job?.result as
    { files?: number; folder?: string } | null | undefined;
  const feedback = pending ? (
    <Feedback loading loadingText={pendingText[pending]} />
  ) : error ? (
    <Feedback error={error} />
  ) : running ? (
    <Feedback
      loading
      loadingText={pendingText[job.action as Operation] || "Working…"}
    />
  ) : job?.status === "complete" ? (
    job.action === "checkpoint_copy" ? (
      <>
        {/* The folder's name says which copy; the user chose where. */}
        <span title={result?.folder}>
          <Feedback
            notice={`Saved a copy: ${fileName(result?.folder || "")}`}
          />
        </span>
        <ActionControl
          inline
          variant="link"
          label="Open folder"
          icon={<FolderOpen size={14} aria-hidden="true" />}
          disabled={action.busy}
          error={action.error}
          onClick={() =>
            action.run(
              () => window.dazedtl.openFolder("output", result?.folder ?? ""),
              "",
              "open",
            )
          }
        />
      </>
    ) : (
      <Feedback
        notice={
          !result?.files
            ? "The game already matched this checkpoint."
            : job.action === "checkpoint_back"
              ? `Went back; ${plural(result.files, "file")} changed. Undo it from the top of the list.`
              : `Undone; ${plural(result.files, "file")} changed. Undo the new checkpoint to put it back.`
        }
      />
    )
  ) : job ? (
    <Feedback error={job.message || sentence(job.status)} />
  ) : null;
  const disabled = !!blocked || !!pending || running;
  return (
    <ActionRow
      label={
        <>
          <strong>{row.title}</strong>
          {row.current && <span className="checkpoints-current">Current</span>}
          <small>
            {when(row.time)} · {changedFiles(row)}
          </small>
        </>
      }
    >
      <Button disabled={!!pending || running} onClick={view}>
        View changes
      </Button>
      <Menu
        variant="quiet"
        className="checkpoints-more"
        label={`Actions for ${row.title}`}
        aria-label={`More actions for ${row.title}, ${when(row.time)}`}
        title={
          blocked ||
          (!row.restorable
            ? "Save a copy"
            : row.kind === "change"
              ? "Go back, undo or save a copy"
              : "Go back or save a copy")
        }
        disabled={disabled}
        trigger={<MoreHorizontal size={16} aria-hidden="true" />}
      >
        {row.restorable ? (
          <>
            <MenuItem
              disabled={row.current}
              description={
                row.current
                  ? "The game is at this checkpoint now."
                  : "Files return to how they were after this change."
              }
              onSelect={() => start("checkpoint_back")}
            >
              Go back to here
            </MenuItem>
            {row.kind === "change" && (
              <MenuItem
                disabled={!!row.blocker}
                description={
                  row.blocker
                    ? blockedBy(row)
                    : "Takes out only this change; later ones stay."
                }
                onSelect={() => start("checkpoint_undo")}
              >
                Undo this change
              </MenuItem>
            )}
          </>
        ) : (
          <MenuItem
            disabled
            description="This is an earlier game version. Save a copy to use it."
            onSelect={() => undefined}
          >
            Go back to here
          </MenuItem>
        )}
        <MenuSeparator />
        <MenuItem
          description="The whole game as of here, in a new folder."
          onSelect={() => start("checkpoint_copy")}
        >
          Save a copy…
        </MenuItem>
      </Menu>
      {feedback && <div className="checkpoints-feedback">{feedback}</div>}
    </ActionRow>
  );
}

function CheckpointChanges({
  projectId,
  row,
  close,
}: {
  projectId: string;
  row: Checkpoint;
  close: () => void;
}) {
  const changes = useRead(`${projectId}\n${row.commit}`, () =>
    api.translation.checkpointChanges(projectId, row.commit),
  );
  return (
    <Modal label={row.title} size="lg" onDismiss={close}>
      <DialogHeader
        title={row.title}
        description={`${row.group} · ${when(row.time)} · ${changedFiles(row)}`}
        onClose={close}
      />
      <DialogBody>
        {changes.value ? (
          <VersionChanges
            value={changes.value}
            listLabel="Files this checkpoint changed"
            unread=""
          />
        ) : changes.error ? (
          <>
            <Message message={messageOf(changes.error)} />
            <Button onClick={changes.retry}>Try again</Button>
          </>
        ) : (
          <Feedback loading loadingText="Reading the changes…" />
        )}
      </DialogBody>
    </Modal>
  );
}
