import { useEffect, useRef, useState } from "react";
import { Check, KeyRound, Plus, ShieldCheck } from "lucide-react";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { flushDrafts } from "../../state/leaveGuards";
import { useSettingsDraft } from "./useSettingsDraft";
import ConnectionEditor from "./ConnectionEditor";
import Preferences from "./Preferences";
import { PageLayout, PageHeader, PageBody } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { FieldRow, DetailRow } from "../../ui/FieldRow";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { Button } from "../../ui/Button";
import { ActionBar } from "../../ui/ActionBar";
import { Message } from "../../ui/Feedback";

const sections = [
  { id: "api", label: "API connections" },
  { id: "preferences", label: "Preferences" },
] as const;
type SectionId = (typeof sections)[number]["id"];

export default function Settings() {
  const application = useApplication();
  const action = useAction();
  const draft = useSettingsDraft(action.report);
  const { config } = draft;
  const [section, setSection] = useState<SectionId>("api");
  const [editor, setEditor] = useState<string | null>(null);
  const busy = action.busy || draft.committing;
  const running = !!application.snapshot?.application.running;
  const current = config?.connections.find(
    (item) => item.id === config.activeConnectionId,
  );
  const previousConnection = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (previousConnection.current !== current?.id) {
      previousConnection.current = current?.id;
      if (current?.needsSetup) setEditor(current.id);
    }
  }, [current?.id, current?.needsSetup]);
  const editId =
    editor ?? (config && !config.connections.length ? "new" : null);
  const editConnection = config?.connections.find((item) => item.id === editId);
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
  return (
    <PageLayout
      variant="editor"
      className="settings-page"
      aria-label="Application settings"
    >
      <PageHeader title="Settings" />
      <Tabs
        id="settings"
        label="Settings sections"
        items={sections}
        value={section}
        disabled={busy}
        onChange={move}
      />
      {action.error && section === "api" && (
        <Message message={action.error} onDismiss={action.clear} />
      )}
      {!config ? (
        <PageBody>
          <p className="muted" role="status">
            Loading settings…
          </p>
        </PageBody>
      ) : (
        <TabPanel id="settings" value={section}>
          {section === "preferences" ? (
            <Preferences
              config={config}
              connection={current}
              dirty={draft.dirty}
              busy={busy}
              running={running}
              error={action.error}
              notice={action.notice}
              edit={draft.edit}
              editModelOptions={draft.editModelOptions}
              save={() => action.run(draft.save, "Preferences saved.")}
              revert={() =>
                action.run(draft.revert, "Reverted to saved preferences.")
              }
            />
          ) : editId !== null ? (
            <ConnectionEditor
              key={editId}
              connection={editConnection}
              providers={config.providers}
              running={running}
              save={async (input) => {
                await draft.saveConnection(input);
                action.succeed("Connection saved.");
              }}
              cancel={() => setEditor(null)}
            />
          ) : (
            <>
              <PageBody>
                <Section title="Active connection">
                  {config.connections.length > 1 || !current ? (
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
                  ) : (
                    <h3 className="connection-title">{current.name}</h3>
                  )}
                  {current && (
                    <>
                      <dl className="connection-details">
                        <DetailRow label="Provider">
                          {provider?.label || "Choose a provider"}
                        </DetailRow>
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
                        <DetailRow label="Model">
                          {current.model || (
                            <Button
                              variant="link"
                              onClick={() => move("preferences")}
                            >
                              Choose a model in Preferences
                            </Button>
                          )}
                        </DetailRow>
                      </dl>
                      <div
                        className={`connection-status ${successful ? "connection-status--good" : ""}`}
                        role="status"
                      >
                        {checked?.status === "verified" ? (
                          <ShieldCheck size={17} />
                        ) : checked?.status === "reachable" ? (
                          <Check size={17} />
                        ) : (
                          <KeyRound size={17} />
                        )}
                        <div>
                          <strong>
                            {current.needsSetup
                              ? "Provider setup required"
                              : checked?.status === "not_checked"
                                ? "Saved, not checked"
                                : checked?.status === "verified"
                                  ? "Authentication verified"
                                  : checked?.status === "reachable"
                                    ? "Server reachable"
                                    : "Could not verify connection"}
                          </strong>
                          <p>
                            {current.needsSetup
                              ? "Edit this connection to choose its provider."
                              : checked?.status === "not_checked"
                                ? "Check the connection when you are ready. Saving does not contact the provider."
                                : checked?.message}
                          </p>
                          {checked?.checkedAt && (
                            <small>
                              Last checked{" "}
                              {new Date(checked.checkedAt).toLocaleString()}
                            </small>
                          )}
                        </div>
                      </div>
                    </>
                  )}
                </Section>
              </PageBody>
              <ActionBar
                feedback={
                  <div
                    className={`feedback ${action.error ? "error" : ""}`}
                    role="status"
                  >
                    {action.busy
                      ? "Checking connection…"
                      : running
                        ? "Finish the current run before checking or changing connections."
                        : !config.checksEnabled
                          ? "Connection checks are unavailable in offline mode."
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
                <Button
                  disabled={!current || busy || running}
                  onClick={() => {
                    action.clear();
                    setEditor(current!.id);
                  }}
                >
                  Edit
                </Button>
                <Button
                  variant="primary"
                  disabled={
                    !current ||
                    current.needsSetup ||
                    busy ||
                    running ||
                    !config.checksEnabled
                  }
                  onClick={() =>
                    action.run(() => draft.checkConnection(current!.id))
                  }
                >
                  {checked?.status === "not_checked"
                    ? "Check connection"
                    : "Check again"}
                </Button>
              </ActionBar>
            </>
          )}
        </TabPanel>
      )}
    </PageLayout>
  );
}
