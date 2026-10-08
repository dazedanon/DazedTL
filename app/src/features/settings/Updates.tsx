import type { UpdateState } from "../../api/transport";
import { useUpdates } from "../../app/updates";
import { useAction } from "../../state/useAction";
import { PageBody } from "../../ui/PageLayout";
import { DetailRow, FieldRow } from "../../ui/FieldRow";
import { StatusIcon, type StatusKind } from "../../ui/StatusIcon";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";

/** Where this install stands; checks in progress show beside their button. */
function describe(state: UpdateState): {
  status: StatusKind;
  label: string;
  note: string;
} {
  if (state.git)
    return {
      status: "idle",
      label: "Updated with Git",
      note: "This copy is a Git checkout, so the app leaves its files to Git.",
    };
  if (state.revert)
    return {
      status: "ready",
      label: `Ready to go back to ${state.previous}`,
      note: "DazedTL switches when it restarts.",
    };
  if (state.staged)
    return {
      status: "ready",
      label: `Version ${state.staged} is ready`,
      note: "It installs when DazedTL restarts. Projects, settings and runs are kept.",
    };
  if (state.status === "error")
    return {
      status: "failed",
      label: "Could not check for updates",
      note: state.error,
    };
  if (state.outcome && !state.outcome.ok)
    return {
      status: "failed",
      label: `Version ${state.outcome.version} could not be installed`,
      note: `${state.outcome.message} DazedTL ${state.version} is still in place.`,
    };
  // Automatic checks leave a version the user went back from alone.
  if (state.skipped && state.skipped !== state.version)
    return {
      status: "skipped",
      label: `Skipping ${state.skipped}`,
      note: "You went back from it; checking for updates installs it again.",
    };
  return {
    status: state.checkedAt ? "done" : "idle",
    label: state.checkedAt ? "Up to date" : "Not checked yet",
    note: state.outcome ? `Updated from ${state.outcome.from}.` : "",
  };
}

/** The install's version, its update channel, and the restart that updates. */
export default function Updates({ running }: { running: boolean }) {
  const state = useUpdates();
  const action = useAction();
  if (!state)
    return (
      <PageBody>
        <p className="muted" role="status">
          Loading update status…
        </p>
      </PageBody>
    );
  const working = state.status === "checking" || state.status === "downloading";
  const busy = action.busy || working;
  const ready = !!state.staged || state.revert;
  const { status, label, note } = describe(state);
  return (
    <>
      <PageBody>
        {!state.git && (
          <FieldRow
            id="update-channel"
            label="Channel"
            help="Beta also offers test releases before they reach everyone."
          >
            {(control) => (
              <select
                {...control}
                value={state.channel}
                disabled={busy}
                onChange={(event) =>
                  void action.run(
                    () =>
                      window.dazedtl.updates.channel(
                        event.target.value as UpdateState["channel"],
                      ),
                    "",
                    "check",
                  )
                }
              >
                <option value="stable">Stable</option>
                <option value="beta">Beta</option>
              </select>
            )}
          </FieldRow>
        )}
        <section
          className="action-list connection-panel"
          aria-labelledby="update-version"
        >
          <header className="connection-panel-header panel-header">
            <div>
              <h2 id="update-version">DazedTL {state.version}</h2>
              <span className="connection-panel-state" role="status">
                <StatusIcon size={14} status={status} />
                {label}
              </span>
            </div>
          </header>
          {state.checkedAt && !state.git && (
            <dl className="connection-details">
              <DetailRow label="Last checked">
                {new Date(state.checkedAt).toLocaleString()}
              </DetailRow>
            </dl>
          )}
          {note && <div className="connection-panel-note">{note}</div>}
        </section>
      </PageBody>
      {!state.git && (
        <ActionBar feedback={<div className="feedback" role="status" />}>
          {state.revert && (
            <ActionControl
              variant="quiet"
              label={`Keep ${state.version}`}
              disabled={busy}
              pending={action.busy && action.key === "keep"}
              pendingText="Keeping…"
              error={action.key === "keep" ? action.error : ""}
              onClick={() =>
                void action.run(() => window.dazedtl.updates.keep(), "", "keep")
              }
            />
          )}
          {state.previous && !ready && (
            <ActionControl
              variant="quiet"
              label={`Go back to ${state.previous}`}
              disabled={busy}
              pending={action.busy && action.key === "revert"}
              pendingText="Preparing…"
              error={action.key === "revert" ? action.error : ""}
              onClick={() =>
                void action.run(
                  () => window.dazedtl.updates.revert(),
                  "",
                  "revert",
                )
              }
            />
          )}
          {ready ? (
            <ActionControl
              variant="primary"
              label={state.revert ? "Restart to go back" : "Restart to update"}
              disabled={busy || running}
              disabledReason={running ? "Finish the current run first." : ""}
              pending={action.busy && action.key === "restart"}
              pendingText="Restarting…"
              error={action.key === "restart" ? action.error : ""}
              onClick={() =>
                void action.run(
                  () => window.dazedtl.updates.restart(),
                  "",
                  "restart",
                )
              }
            />
          ) : (
            <ActionControl
              variant="primary"
              label="Check for updates"
              disabled={busy}
              pending={working}
              pendingText={
                state.status === "downloading"
                  ? `Downloading ${state.latest}…${state.progress >= 0 ? ` ${state.progress}%` : ""}`
                  : "Checking for updates…"
              }
              error={
                action.key === "check"
                  ? action.error ||
                    (state.status === "error" ? "Could not check." : "")
                  : ""
              }
              notice={
                action.key === "check" &&
                !action.busy &&
                state.status === "idle" &&
                state.checkedAt
                  ? "Up to date."
                  : ""
              }
              onClick={() =>
                void action.run(
                  () => window.dazedtl.updates.check(),
                  "",
                  "check",
                )
              }
            />
          )}
        </ActionBar>
      )}
    </>
  );
}
