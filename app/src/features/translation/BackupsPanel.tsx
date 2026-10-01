import { useState } from "react";
import { api } from "../../api/client";
import type { BackupCatalog, BackupRecord, TranslationState } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { Button } from "../../ui/Button";
import { Section } from "../../ui/Section";
import { Message } from "../../ui/Feedback";
import { ActionControl } from "../../ui/ActionControl";

const bytes = (value: number) =>
  value < 1024
    ? value + " B"
    : value < 1024 ** 2
      ? (value / 1024).toFixed(1) + " KiB"
      : value < 1024 ** 3
        ? (value / 1024 ** 2).toFixed(1) + " MiB"
        : (value / 1024 ** 3).toFixed(2) + " GiB";

export function BackupSummary({ record, fallback }: { record?: BackupRecord; fallback: string }) {
  if (!record) return <>{fallback}</>;
  if (record.available === false) return <>Unavailable · {record.issue}</>;
  return (
    <>
      Saved · {record.files.toLocaleString()} files
      {record.bytes_added !== undefined && (
        <small className="translation-backup-storage">
          {record.reused_snapshot ? "Unchanged snapshot reused" : bytes(record.bytes_added) + " added"}
          {" · "}{bytes(record.bytes_reused || 0)} reused
        </small>
      )}
    </>
  );
}

export function BackupsPanel({ state }: { state: TranslationState }) {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const [catalog, setCatalog] = useState<BackupCatalog | null>(null);
  const [identity, setIdentity] = useState("");
  const [destination, setDestination] = useState("");
  const selected = catalog?.snapshots.find((item) => item.id === identity);
  const restored = state.jobs.find((job) => job.status === "complete" && job.result?.restored === true);
  const disabled = state.active || action.busy;
  const restoreJob = state.jobs.find((job) => job.action === "restore_backup");
  return (
    <Section title="Restore points">
      <p className="muted">
        Backups stay with this game in .dazedtl/backups. Unchanged files are stored once.
        Earlier full-copy backups remain available in the app workspace.
      </p>
      <Message message={["list", "restore"].includes(action.key) ? "" : action.error} onDismiss={action.clear} />
      <ActionControl
        label={catalog ? "Refresh restore points" : "List restore points"}
        pending={action.busy && action.key === "list"}
        pendingText="Loading restore points…"
        error={action.key === "list" ? action.error : ""}
        notice={action.key === "list" ? action.notice : ""}
        disabled={disabled}
        onClick={() => action.run(async () => {
          const result = await api.translation.backups(state.projectId);
          setCatalog(result);
          setIdentity((current) => result.snapshots.some((item) => item.id === current) ? current : result.snapshots[0]?.id || "");
        }, "Restore points loaded.", "list")}
      />
      {catalog?.warnings.map((warning) => <p className="banner" key={warning}>{warning}</p>)}
      {catalog && !catalog.snapshots.length && <p>No saved backups found.</p>}
      {!!catalog?.snapshots.length && (
        <>
          <label>
            Backup to restore
            <select value={identity} disabled={disabled} onChange={(event) => setIdentity(event.target.value)}>
              {catalog.snapshots.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.kind === "source" ? "Source game" : "Translation workspace"}
                  {" · "}{new Date(item.created).toLocaleString()}
                  {" · "}{item.files} files · {item.id.slice(0, 8)}
                  {item.version === 1 ? " · Earlier full copy" : ""}
                </option>
              ))}
            </select>
          </label>
          {selected?.bytes_total != null && <p className="muted">Restored content: {bytes(selected.bytes_total)}</p>}
          <label>
            New restore folder
            <div className="actions">
              <input value={destination} disabled={disabled} onChange={(event) => setDestination(event.target.value)} />
              <Button disabled={disabled} onClick={() => action.run(async () => {
                const parent = await window.dazedtl.chooseFolder();
                if (parent) setDestination(parent.replace(/[\\/]+$/, "") + "/DazedTL-restore-" + identity.slice(0, 8));
              })}>Choose parent folder</Button>
            </div>
          </label>
          <p className="muted">
            Restore verifies the saved files and creates a separate folder outside the game.
            Source backups contain game files; workspace backups contain the contents of .dazedtl.
            Existing folders are never overwritten.
          </p>
          <ActionControl label="Restore verified copy" disabled={disabled || !identity || !destination.trim()}
            pending={action.busy && action.key === "restore"} pendingText="Starting restore…"
            error={action.key === "restore" ? action.error : ""} job={restoreJob}
            onClick={() => action.run(() => api.translation.operation(state.projectId, "restore_backup", { backup_id: identity, destination }), "", "restore")} />
        </>
      )}
      {typeof restored?.result?.path === "string" && <p className="translation-path">Restored copy: {restored.result.path}</p>}
    </Section>
  );
}
