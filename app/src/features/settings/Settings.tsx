import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useOnChange } from "../../state/useOnChange";
import { flushDrafts } from "../../state/leaveGuards";
import { useSettingsDraft } from "./useSettingsDraft";
import ConnectionEditor from "./ConnectionEditor";
import { ModelMenu } from "./ModelMenu";
import TranslationDefaults from "./TranslationDefaults";
import Updates from "./Updates";
import { updateAttention, useUpdates } from "../../app/updates";
import { RemoveConnection } from "./RemoveConnection";
import { PageLayout, PageHeader, PageBody } from "../../ui/PageLayout";
import { StatusIcon } from "../../ui/StatusIcon";
import { FieldRow, DetailRow } from "../../ui/FieldRow";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { Button } from "../../ui/Button";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Message } from "../../ui/Feedback";

const sections = [
  { id: "api", label: "API connections" },
  { id: "preferences", label: "Translation defaults" },
  { id: "updates", label: "Updates" },
] as const;
type SectionId = (typeof sections)[number]["id"];

export default function Settings({
  onDirty,
}: {
  /** Tells the shell about a kept draft, so it can mark Settings while hidden. */
  onDirty?: (dirty: boolean) => void;
}) {
  const application = useApplication();
  const action = useAction();
  const draft = useSettingsDraft(action.report);
  useEffect(() => onDirty?.(draft.dirty), [onDirty, draft.dirty]);
  const { config } = draft;
  const [section, setSection] = useState<SectionId>("api");
  const attention = updateAttention(useUpdates());
  const busy = action.busy || draft.committing;
  const running = !!application.snapshot?.application.running;
  const current = config?.connections.find(
    (item) => item.id === config.activeConnectionId,
  );
  // A newly active connection that still needs setup opens its editor.
  const [editor, setEditor] = useState<string | null>(() =>
    current?.needsSetup ? current.id : null,
  );
  useOnChange(current?.id, (id) => {
    if (id && current?.needsSetup) setEditor(id);
  });
  const editId =
    editor ?? (config && !config.connections.length ? "new" : null);
  const editConnection = config?.connections.find((item) => item.id === editId);
  const [removing, setRemoving] = useState<string | null>(null);
  const removal = config?.connections.find((item) => item.id === removing);
  const move = (next: SectionId) =>
    action.run(async () => {
      await flushDrafts();
      setSection(next);
    });
  const provider = config?.providers.find(
    (item) => item.id === current?.provider,
  );
  const checked = current?.check;
  const successful =
    checked?.status === "verified" || checked?.status === "reachable";
  const check = (id: string) =>
    action.run(() => draft.checkConnection(id), "checked", "check");
  return (
    <PageLayout
      variant="editor"
      className="settings-page"
      aria-label="Application settings"
    >
      <PageHeader title="Settings" />
      <div className="frame-row">
        <Tabs
          id="settings"
          label="Settings sections"
          items={sections.map((item) =>
            item.id === "updates" && attention
              ? {
                  ...item,
                  status: (
                    <span
                      className="update-dot"
                      role="img"
                      aria-label="Needs attention"
                    />
                  ),
                }
              : item,
          )}
          value={section}
          disabled={busy}
          onChange={move}
        />
      </div>
      {action.error && action.key !== "check" && section === "api" && (
        <Message message={action.error} onDismiss={action.clear} />
      )}
      {section === "updates" ? (
        <TabPanel id="settings" value={section}>
          <Updates running={running} />
        </TabPanel>
      ) : !config ? (
        <PageBody>
          <p className="muted" role="status">
            Loading settings…
          </p>
        </PageBody>
      ) : (
        <TabPanel id="settings" value={section}>
          {section === "preferences" ? (
            <TranslationDefaults
              config={config}
              connection={current}
              dirty={draft.dirty}
              busy={busy}
              running={running}
              error={action.error}
              notice={action.notice}
              edit={draft.edit}
              editModelOptions={draft.editModelOptions}
              save={() => action.run(draft.save, "Translation defaults saved.")}
              revert={() =>
                action.run(draft.revert, "Reverted to saved defaults.")
              }
            />
          ) : editId !== null ? (
            <ConnectionEditor
              key={editId}
              connection={editConnection}
              providers={config.providers}
              running={running}
              checksEnabled={config.checksEnabled}
              save={async (input) => {
                const { saved } = await draft.saveConnection(input);
                const connection = saved.connections.find(
                  (item) => item.id === saved.activeConnectionId,
                );
                // New or changed credentials are checked right away; the
                // check button reports the result.
                if (
                  saved.checksEnabled &&
                  connection?.check.status === "not_checked" &&
                  !connection.needsSetup
                )
                  void check(connection.id);
                else action.succeed("Connection saved.");
              }}
              cancel={
                config.connections.length ? () => setEditor(null) : undefined
              }
            />
          ) : (
            <>
              <PageBody>
                {(config.connections.length > 1 || !current) && (
                  <FieldRow id="active-connection" label="Connection">
                    {(control) => (
                      <select
                        {...control}
                        value={config.activeConnectionId}
                        disabled={busy || running}
                        onChange={(event) =>
                          action.run(
                            () => draft.selectConnection(event.target.value),
                            "Connection selected.",
                          )
                        }
                      >
                        <option value="" disabled>
                          Choose a connection
                        </option>
                        {config.connections.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.name}
                            {item.needsSetup ? " (needs setup)" : ""}
                          </option>
                        ))}
                      </select>
                    )}
                  </FieldRow>
                )}
                {current && (
                  // One panel per connection, headed by its name and state.
                  <section
                    className="action-list connection-panel"
                    aria-labelledby="active-connection-name"
                  >
                    <header className="connection-panel-header panel-header">
                      <div>
                        <h2 id="active-connection-name">{current.name}</h2>
                        <span className="connection-panel-state" role="status">
                          <StatusIcon
                            size={14}
                            status={
                              current.needsSetup
                                ? "warning"
                                : successful
                                  ? "done"
                                  : checked?.status === "not_checked"
                                    ? "idle"
                                    : "failed"
                            }
                          />
                          {current.needsSetup
                            ? "Provider setup required"
                            : checked?.status === "not_checked"
                              ? "Saved, not checked"
                              : checked?.status === "verified"
                                ? "Authentication verified"
                                : checked?.status === "reachable"
                                  ? "Server reachable"
                                  : "Could not verify connection"}
                        </span>
                      </div>
                      <div className="actions">
                        <Button
                          variant="quiet"
                          disabled={busy || running}
                          onClick={() => {
                            action.clear();
                            setRemoving(current.id);
                          }}
                        >
                          Remove…
                        </Button>
                        <Button
                          disabled={busy || running}
                          onClick={() => {
                            action.clear();
                            setEditor(current.id);
                          }}
                        >
                          Edit
                        </Button>
                      </div>
                    </header>
                    <dl className="connection-details">
                      <DetailRow label="Provider">
                        {provider?.label || "Choose a provider"}
                      </DetailRow>
                      {current.provider === "openrouter" &&
                        current.openrouter_host && (
                          <DetailRow label="Host">
                            {current.openrouter_host}
                          </DetailRow>
                        )}
                      <DetailRow label="API key">
                        {current.keyless
                          ? "Not required"
                          : current.has_secret
                            ? "Saved"
                            : "Not configured"}
                      </DetailRow>
                      {current.endpoint && (
                        <DetailRow label="Server">
                          <span className="connection-address">
                            {current.endpoint}
                          </span>
                        </DetailRow>
                      )}
                      <DetailRow
                        label="Model"
                        valueClassName="connection-model"
                      >
                        <ModelMenu
                          model={current.model}
                          connection={current.name}
                          disabled={busy || running}
                        />
                      </DetailRow>
                    </dl>
                    {(current.needsSetup ||
                      current.check.status !== "not_checked") && (
                      <div className="connection-panel-note">
                        {current.needsSetup
                          ? "Edit this connection to choose its provider."
                          : checked?.message}
                        {checked?.checkedAt && (
                          <small>
                            Last checked{" "}
                            {new Date(checked.checkedAt).toLocaleString()}
                          </small>
                        )}
                      </div>
                    )}
                  </section>
                )}
              </PageBody>
              <ActionBar
                feedback={
                  <div className="feedback" role="status">
                    {running
                      ? "Finish the current run before checking or changing connections."
                      : action.key === "check"
                        ? ""
                        : action.notice}
                  </div>
                }
              >
                <Button
                  variant="quiet"
                  disabled={busy || running}
                  onClick={() => {
                    action.clear();
                    setEditor("new");
                  }}
                >
                  <Plus size={14} />
                  Add another
                </Button>
                <ActionControl
                  variant="primary"
                  label={
                    checked?.status === "not_checked"
                      ? "Check connection"
                      : "Check again"
                  }
                  disabled={
                    !current ||
                    current.needsSetup ||
                    busy ||
                    running ||
                    !config.checksEnabled
                  }
                  disabledReason={
                    !config.checksEnabled
                      ? "Unavailable in offline mode."
                      : current?.needsSetup
                        ? "Finish setting up this connection first."
                        : ""
                  }
                  pending={action.busy && action.key === "check"}
                  pendingText="Checking connection…"
                  error={
                    action.key !== "check"
                      ? ""
                      : action.error ||
                        (action.notice && !successful
                          ? "Could not verify the connection. See the details above."
                          : "")
                  }
                  // A finished check repeats the card's result beside its button.
                  notice={
                    action.key === "check" && action.notice
                      ? successful
                        ? checked?.status === "verified"
                          ? "Authentication verified."
                          : "Server reachable."
                        : ""
                      : ""
                  }
                  onClick={() => check(current!.id)}
                />
              </ActionBar>
            </>
          )}
        </TabPanel>
      )}
      {removal && config && (
        <RemoveConnection
          connection={removal}
          next={
            removal.id === config.activeConnectionId
              ? config.connections.find((item) => item.id !== removal.id)
              : undefined
          }
          remove={async (unfinished) => {
            await draft.removeConnection(removal.id, unfinished);
            action.succeed(`${removal.name} removed.`);
          }}
          close={() => setRemoving(null)}
        />
      )}
    </PageLayout>
  );
}
