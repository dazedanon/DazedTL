import { useRef, useState } from "react";
import { FolderOpen, Pencil, Plus, RotateCcw } from "lucide-react";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { useSettingsDraft } from "./useSettingsDraft";
import ConnectionDialog from "./ConnectionDialog";
import type { Settings as Configuration } from "../../api/contracts";
import { PageLayout, PageHeader, PageBody } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { FieldRow } from "../../ui/FieldRow";
import { Tabs, TabPanel } from "../../ui/Tabs";
import { Button } from "../../ui/Button";
import { ActionBar } from "../../ui/ActionBar";
import { Feedback } from "../../ui/Feedback";

const sections = [
  { id: "provider", label: "Provider & model" },
  { id: "translation", label: "Translation" },
  { id: "engine", label: "Engine options" },
] as const;
type SectionId = (typeof sections)[number]["id"];
export default function Settings() {
  const application = useApplication();
  const action = useAction({ after: application.refresh });
  const { config, dirty, committing, edit, save, revert, credential } =
    useSettingsDraft(action.report);
  const [section, setSection] = useState<SectionId>("provider");
  const [editor, setEditor] = useState<{
    connection: Configuration["keys"][number] | null;
  } | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const busy = action.busy || committing;
  const selected = config?.keys.find(
    (connection) => connection.name === config.active_key,
  );
  function numbers(name: string, label: string, help?: string) {
    const definition = config!.fields.find((field) => field.key === name);
    return (
      <FieldRow id={"setting-" + name} label={label} help={help}>
        {(control) => (
          <input
            {...control}
            type="number"
            className="short-control"
            required
            min={definition?.min}
            max={definition?.max}
            step={definition?.type === "number" ? "any" : 1}
            value={String(config!.values[name])}
            onChange={(event) =>
              edit(
                name,
                event.target.value === "" ? "" : Number(event.target.value),
              )
            }
          />
        )}
      </FieldRow>
    );
  }
  return (
    <PageLayout
      variant="editor"
      className="settings-page"
      aria-label="Application settings"
    >
      <PageHeader
        title="Settings"
        actions={
          <Button
            variant="quiet"
            className="workspace-shortcut"
            onClick={() =>
              window.dazedtl.openFolder("workspace").catch(action.report)
            }
          >
            <FolderOpen size={15} />
            Workspace folder
          </Button>
        }
      />
      <Tabs
        id="settings"
        label="Settings sections"
        items={sections}
        value={section}
        disabled={busy}
        onChange={(value) => {
          setSection(value);
          scroll.current?.scrollTo(0, 0);
        }}
      />
      <form
        className="editor-form"
        onSubmit={(event) => {
          event.preventDefault();
          action.run(save, "Settings saved.");
        }}
      >
        <PageBody ref={scroll}>
          {!config ? (
            <p className="muted" role="status">
              Loading settings…
            </p>
          ) : (
            <fieldset disabled={busy}>
              <TabPanel id="settings" value={section}>
                {section === "provider" && (
                  <>
                    <Section title="Connection">
                      <FieldRow id="active-connection" label="Saved connection">
                        {(control) => (
                          <div className="connection-controls">
                            <select
                              {...control}
                              value={config.active_key}
                              disabled={!config.keys.length}
                              onChange={(event) => {
                                const name = event.target.value;
                                action.run(
                                  () => credential({ action: "select", name }),
                                  "Connection selected.",
                                );
                              }}
                            >
                              {!config.keys.length && (
                                <option value="">No saved connections</option>
                              )}
                              {config.keys.map((connection) => (
                                <option key={connection.name}>
                                  {connection.name}
                                </option>
                              ))}
                            </select>
                            <Button
                              variant="quiet"
                              onClick={() => setEditor({ connection: null })}
                            >
                              <Plus size={14} />
                              Add
                            </Button>
                            <Button
                              variant="quiet"
                              disabled={!selected}
                              onClick={() =>
                                setEditor({ connection: selected || null })
                              }
                            >
                              <Pencil size={14} />
                              Edit
                            </Button>
                          </div>
                        )}
                      </FieldRow>
                      <div className="field-row">
                        <span className="field-label">Endpoint</span>
                        <div className="field-control">
                          <span
                            className="endpoint-value"
                            title={
                              selected?.endpoint || String(config.values.api)
                            }
                          >
                            {selected
                              ? selected.endpoint ||
                                String(config.values.api) ||
                                "Provider default"
                              : "Add a connection to configure its endpoint."}
                          </span>
                        </div>
                      </div>
                      <FieldRow
                        id="provider-protocol"
                        label="Provider protocol"
                      >
                        {(control) => (
                          <select
                            {...control}
                            value={String(config.values.API_PROVIDER)}
                            onChange={(event) =>
                              edit("API_PROVIDER", event.target.value)
                            }
                          >
                            <option value="openai">OpenAI compatible</option>
                            <option value="anthropic">Anthropic</option>
                            <option value="gemini">Google Gemini</option>
                            <option value="mistral">Mistral</option>
                          </select>
                        )}
                      </FieldRow>
                      <FieldRow id="translation-model" label="Model">
                        {(control) => (
                          <input
                            {...control}
                            required
                            value={String(config.values.model)}
                            onChange={(event) =>
                              edit("model", event.target.value)
                            }
                          />
                        )}
                      </FieldRow>
                    </Section>
                    <Section title="Token prices" hint="USD per million tokens">
                      <div className="paired-settings">
                        {numbers("input_cost", "Input")}
                        {numbers("output_cost", "Output")}
                      </div>
                      <p className="settings-note">
                        Used in cost estimates. Your provider determines the
                        actual charges.
                      </p>
                    </Section>
                  </>
                )}
                {section === "translation" && (
                  <Section title="Translation defaults">
                    <FieldRow id="target-language" label="Target language">
                      {(control) => (
                        <input
                          {...control}
                          required
                          value={String(config.values.language)}
                          onChange={(event) =>
                            edit("language", event.target.value)
                          }
                        />
                      )}
                    </FieldRow>
                    {numbers(
                      "batchsize",
                      "Entries per request",
                      "Text entries sent together in one request.",
                    )}
                    <p className="settings-note">
                      Applied to new translation runs.
                    </p>
                  </Section>
                )}
                {section === "engine" && (
                  <Section
                    title="RPG Maker formatting"
                    hint="Characters per line"
                  >
                    <div className="paired-settings">
                      {numbers("width", "Dialogue")}
                      {numbers("faceWidth", "With a face image")}
                      {numbers("listWidth", "Lists")}
                      {numbers("noteWidth", "Notes")}
                    </div>
                    <p className="settings-note">
                      Defaults for new projects. Existing games retain their own
                      formatting settings.
                    </p>
                  </Section>
                )}
              </TabPanel>
            </fieldset>
          )}
        </PageBody>
        <ActionBar
          feedback={
            <Feedback
              loadingText="Loading settings…"
              error={action.error}
              loading={!config}
              pending={busy}
              dirty={dirty}
              notice={action.notice}
            />
          }
        >
          <Button
            disabled={!dirty || busy || !config}
            onClick={() => action.run(revert, "Reverted to saved settings.")}
          >
            <RotateCcw size={14} />
            Revert
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!dirty || busy || !config}
          >
            Save changes
          </Button>
        </ActionBar>
      </form>
      {editor && config && (
        <ConnectionDialog
          connection={editor.connection}
          names={config.keys.map((connection) => connection.name)}
          close={() => setEditor(null)}
          save={async (value) => {
            await credential({ action: "save", ...value });
            await application.refresh();
            action.succeed("Connection saved.");
          }}
        />
      )}
    </PageLayout>
  );
}
