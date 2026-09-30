import type { Connection, Settings, Value } from "../../api/contracts";
import { PageBody } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { FieldRow } from "../../ui/FieldRow";
import { ActionBar } from "../../ui/ActionBar";
import { Feedback } from "../../ui/Feedback";
import { Button } from "../../ui/Button";

export default function Preferences({
  config,
  connection,
  dirty,
  busy,
  running,
  error,
  notice,
  edit,
  save,
  revert,
  workspace,
}: {
  config: Settings;
  connection?: Connection;
  dirty: boolean;
  busy: boolean;
  running: boolean;
  error: string;
  notice: string;
  edit: (key: string, value: Value) => void;
  save: () => void;
  revert: () => void;
  workspace: () => void;
}) {
  function number(name: string, label: string, help?: string) {
    const definition = config.fields.find((item) => item.key === name);
    return (
      <FieldRow id={"preference-" + name} label={label} help={help}>
        {(control) => (
          <input
            {...control}
            className="short-control"
            type="number"
            required
            min={definition?.min}
            max={definition?.max}
            step={definition?.type === "number" ? "any" : 1}
            value={String(config.values[name])}
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
    <form
      className="editor-form"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <PageBody>
        <fieldset disabled={busy}>
          <Section title="Translation defaults">
            <FieldRow
              id="translation-model"
              label="Translation model"
              help={
                connection
                  ? `Saved for ${connection.name}. Choose a text model before starting a run.`
                  : "Used for estimates until you add an API connection."
              }
            >
              {(control) => (
                <>
                  <input
                    {...control}
                    required={!connection}
                    list="connection-models"
                    value={String(config.values.model)}
                    placeholder="Choose or enter a model ID"
                    onChange={(event) => edit("model", event.target.value)}
                  />
                  <datalist id="connection-models">
                    {connection?.models.map((model) => (
                      <option key={model} value={model} />
                    ))}
                  </datalist>
                </>
              )}
            </FieldRow>
            {connection && !connection.models.length && (
              <p className="settings-note">
                Check the connection to load available model suggestions, or
                enter a model ID.
              </p>
            )}
            <FieldRow id="target-language" label="Target language">
              {(control) => (
                <input
                  {...control}
                  required
                  value={String(config.values.language)}
                  onChange={(event) => edit("language", event.target.value)}
                />
              )}
            </FieldRow>
          </Section>
          <details className="settings-advanced">
            <summary>Advanced translation options</summary>
            <Section title="Requests">
              {number(
                "batchsize",
                "Entries per request",
                "Text entries sent together in one request.",
              )}
            </Section>
            <Section
              title="Manual estimate rates"
              hint="USD per million tokens"
            >
              <div className="paired-settings">
                {number("input_cost", "Input")}
                {number("output_cost", "Output")}
              </div>
              <p className="settings-note">
                Only affects estimates. Match these rates to your selected
                model.
              </p>
            </Section>
            <Section title="RPG Maker formatting" hint="Characters per line">
              <div className="paired-settings">
                {number("width", "Dialogue")}
                {number("faceWidth", "With a face image")}
                {number("listWidth", "Lists")}
                {number("noteWidth", "Notes")}
              </div>
              <p className="settings-note">
                Defaults for new projects. Existing games retain their own
                formatting settings.
              </p>
            </Section>
          </details>
          <div className="settings-workspace">
            <Button variant="quiet" onClick={workspace}>
              Open workspace folder
            </Button>
          </div>
        </fieldset>
      </PageBody>
      <ActionBar
        feedback={
          <Feedback
            error={error}
            pending={busy}
            dirty={dirty}
            notice={
              running && dirty
                ? "Save preferences after the current run finishes."
                : notice
            }
          />
        }
      >
        <Button disabled={!dirty || busy} onClick={revert}>
          Revert
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={!dirty || busy || running}
        >
          Save preferences
        </Button>
      </ActionBar>
    </form>
  );
}
