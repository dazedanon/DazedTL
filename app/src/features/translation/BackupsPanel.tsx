import { useState } from "react";
import { api } from "../../api/client";
import type {
  BackupCatalog,
  BackupRecord,
  TranslationState,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import { Button } from "../../ui/Button";
import { Section } from "../../ui/Section";
import { Message } from "../../ui/Feedback";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { FieldRow } from "../../ui/FieldRow";
import { ActionSlot } from "../../ui/ActionSlot";

const bytes = (value: number) =>
  value < 1024
    ? value + " B"
    : value < 1024 ** 2
      ? (value / 1024).toFixed(1) + " KiB"
      : value < 1024 ** 3
        ? (value / 1024 ** 2).toFixed(1) + " MiB"
        : (value / 1024 ** 3).toFixed(2) + " GiB";
const fileCount = (value: number) =>
  `${value.toLocaleString()} ${value === 1 ? "file" : "files"}`;

export function BackupSummary({
  record,
  fallback,
}: {
  record?: BackupRecord;
  fallback: string;
}) {
  if (!record) return <>{fallback}</>;
  if (record.available === false) return <>Unavailable · {record.issue}</>;
  return <>Saved · {fileCount(record.files)}</>;
}

type Snapshot = BackupCatalog["snapshots"][number];
function backupName(item: Snapshot, state: TranslationState) {
  if (item.id === state.lifecycle.prepared_source?.id)
    return (
      "Prepared original" +
      (state.git?.original_version ? " · " + state.git.original_version : "")
    );
  const incoming = state.jobs.find(
    (job) =>
      job.action === "stage_update" &&
      (job.result?.source_backup as BackupRecord | undefined)?.id === item.id,
  );
  if (incoming) return "Official release · " + String(incoming.result?.version);
  return item.kind === "source" ? "Game files" : "Translation project files";
}

export function BackupsPanel({
  state,
  actionTarget,
}: {
  state: TranslationState;
  actionTarget?: HTMLElement | null;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [recovering, setRecovering] = useState(false);
  const [catalog, setCatalog] = useState<BackupCatalog | null>(null);
  const [kind, setKind] = useState<Snapshot["kind"]>("source");
  const [identity, setIdentity] = useState("");
  const [destination, setDestination] = useState("");
  const matches = catalog?.snapshots.filter((item) => item.kind === kind) || [];
  const selected = matches.find((item) => item.id === identity);
  const disabled =
    state.active || action.busy || !!application.snapshot?.application.running;
  const restoreJob = state.jobs.find((job) => job.action === "restore_backup");
  const selectedRestore =
    restoreJob && (!restoreJob.result || restoreJob.result.id === identity)
      ? restoreJob
      : undefined;
  const operation = (name: string, args: Record<string, unknown> = {}) =>
    action.run(
      async () => {
        await flushDrafts();
        await api.translation.operation(state.projectId, name, args);
      },
      "",
      name,
    );
  const load = () =>
    action.run(
      async () => {
        const result = await api.translation.backups(state.projectId);
        setCatalog(result);
        setIdentity((current) =>
          result.snapshots.some(
            (item) => item.id === current && item.kind === kind,
          )
            ? current
            : result.snapshots.find((item) => item.kind === kind)?.id || "",
        );
      },
      "",
      "list",
    );
  const control = (name: string, label: string, blocked = false) => (
    <ActionControl
      label={label}
      disabled={disabled || blocked}
      pending={action.busy && action.key === name}
      pendingText="Saving backup…"
      error={action.key === name ? action.error : ""}
      job={state.jobs.find((job) => job.action === name)}
      onClick={() => operation(name)}
    />
  );
  const openFolder = (key: "source_backup" | "workspace_backup") => {
    const record = state.lifecycle[key];
    return (
      record && (
        <ActionControl
          inline
          variant="link"
          label="Open folder"
          title={record.path}
          disabled={disabled || record.available === false}
          pending={action.busy && action.key === key}
          pendingText="Opening…"
          error={action.key === key ? action.error : ""}
          notice={action.key === key ? action.notice : ""}
          onClick={() =>
            action.run(
              () => window.dazedtl.openFolder("backup", record.path),
              "Backup folder opened.",
              key,
            )
          }
        />
      )
    );
  };
  if (!recovering)
    return (
      <div className="backup-panel">
        <p>
          Save copies before making changes. Backups stay with the game in
          .dazedtl/backups, and unchanged files share storage.
        </p>
        <ActionList>
          <ActionRow
            label={
              <>
                <strong>Game files</strong>
                <small>
                  The game as it is now. Earlier backups remain available.
                </small>
                <small className="backup-saved">
                  <BackupSummary
                    record={state.lifecycle.source_backup}
                    fallback="No game backup saved yet"
                  />
                  {openFolder("source_backup")}
                </small>
              </>
            }
          >
            {control("backup_source", "Save game backup")}
          </ActionRow>
          <ActionRow
            label={
              <>
                <strong>Translation project files</strong>
                <small>
                  Glossary, notes and working files in .dazedtl, saved
                  separately from the game files.
                </small>
                <small className="backup-saved">
                  <BackupSummary
                    record={state.lifecycle.workspace_backup}
                    fallback="No project backup saved yet"
                  />
                  {openFolder("workspace_backup")}
                </small>
              </>
            }
          >
            {control("backup_workspace", "Save project backup")}
          </ActionRow>
        </ActionList>
        <Section title="Need an earlier copy?">
          <p>
            Choose a saved backup and recover it into a new folder. Your current
            game stays in place. Preparation and patch checkpoints also save
            backups, and earlier full-copy backups from the app workspace are
            included.
          </p>
          <ActionSlot target={actionTarget}>
            <Button
              disabled={disabled}
              onClick={() => {
                setRecovering(true);
                void load();
              }}
            >
              Recover files…
            </Button>
          </ActionSlot>
        </Section>
      </div>
    );
  return (
    <div className="backup-panel">
      <Button
        variant="quiet"
        disabled={action.busy}
        onClick={() => {
          setRecovering(false);
          action.clear();
        }}
      >
        Back to backups
      </Button>
      <Section title="Recover files to a new folder">
        <p>
          Choose the kind of files you need, then the saved copy. Recovery
          verifies its contents and never overwrites an existing folder.
        </p>
        <div
          className="backup-kinds"
          role="group"
          aria-label="Files to recover"
        >
          {(
            [
              ["source", "Game files"],
              ["workspace", "Translation project files"],
            ] as const
          ).map(([value, label]) => (
            <Button
              key={value}
              aria-pressed={kind === value}
              disabled={disabled}
              onClick={() => {
                setKind(value);
                setIdentity(
                  catalog?.snapshots.find((item) => item.kind === value)?.id ||
                    "",
                );
                setDestination("");
              }}
            >
              {label}
            </Button>
          ))}
        </div>
        <p className="muted">
          {kind === "source"
            ? "Each saved copy contains the game files as they were on that date."
            : "Recovers the contents of .dazedtl, such as your glossary and project notes. This does not restore the game itself."}
        </p>
        {catalog?.warnings.map((warning) => (
          <Message key={warning} message={warning} />
        ))}
        <ActionControl
          label={catalog ? "Refresh saved copies" : "Load saved copies"}
          variant="quiet"
          disabled={disabled}
          pending={action.busy && action.key === "list"}
          pendingText="Loading saved copies…"
          error={action.key === "list" ? action.error : ""}
          onClick={load}
        />
        {catalog && !matches.length && (
          <p>No backups of these files have been saved yet.</p>
        )}
        {!!matches.length && (
          <div className="version-form">
            <FieldRow id="backup-saved-copy" label="Saved copy" wide>
              {(props) => (
                <select
                  {...props}
                  disabled={disabled}
                  value={identity}
                  onChange={(event) => {
                    setIdentity(event.target.value);
                    setDestination("");
                  }}
                >
                  {matches.map((item) => (
                    <option key={item.id} value={item.id}>
                      {backupName(item, state)} ·{" "}
                      {new Date(item.created).toLocaleString()} ·{" "}
                      {fileCount(item.files)}
                    </option>
                  ))}
                </select>
              )}
            </FieldRow>
            {selected && (
              <p className="muted">
                {fileCount(selected.files)}
                {selected.bytes_total !== null
                  ? " · " + bytes(selected.bytes_total)
                  : ""}
                {selected.version === 1 ? " · Earlier full copy" : ""}
              </p>
            )}
            <FieldRow id="backup-recovery-folder" label="New recovery folder">
              {(props) => (
                <div className="version-folder">
                  <input
                    {...props}
                    disabled={disabled}
                    value={destination}
                    onChange={(event) => setDestination(event.target.value)}
                    placeholder="Choose a new folder outside the current game"
                  />
                  <Button
                    disabled={disabled}
                    onClick={() =>
                      action.run(
                        async () => {
                          const parent = await window.dazedtl.chooseFolder();
                          if (parent)
                            setDestination(
                              parent.replace(/[\\/]+$/, "") +
                                "/DazedTL-recovered-" +
                                kind +
                                "-" +
                                identity.slice(0, 8),
                            );
                        },
                        "",
                        "folder",
                      )
                    }
                  >
                    Choose location
                  </Button>
                </div>
              )}
            </FieldRow>
            <Message message={action.key === "folder" ? action.error : ""} />
            <ActionSlot target={actionTarget}>
              <ActionControl
                label={
                  kind === "source"
                    ? "Recover game files"
                    : "Recover project files"
                }
                variant="primary"
                disabled={disabled || !selected || !destination.trim()}
                pending={action.busy && action.key === "restore_backup"}
                pendingText="Starting recovery…"
                error={action.key === "restore_backup" ? action.error : ""}
                job={selectedRestore}
                onClick={() =>
                  operation("restore_backup", {
                    backup_id: identity,
                    destination,
                  })
                }
              />
            </ActionSlot>
          </div>
        )}
        {typeof selectedRestore?.result?.path === "string" &&
          selectedRestore.status === "complete" && (
            <p className="translation-path">
              Last recovery saved to: {selectedRestore.result.path}
            </p>
          )}
      </Section>
    </div>
  );
}
