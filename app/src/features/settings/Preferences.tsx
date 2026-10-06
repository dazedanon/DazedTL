import { useRef, useState } from "react";
import ModelOptionsEditor from "./ModelOptionsEditor";
import type {
  Connection,
  Settings,
  PreferenceValues,
  ModelOptions,
} from "../../api/contracts";
import {
  shortcutKeys,
  shortcutLabel,
  useSaveForm,
} from "../../state/useShortcut";
import { PageBody } from "../../ui/PageLayout";
import { Section } from "../../ui/Section";
import { FieldRow } from "../../ui/FieldRow";
import { ActionBar } from "../../ui/ActionBar";
import { Feedback } from "../../ui/Feedback";
import { Button } from "../../ui/Button";
import { ComboBox } from "../../ui/ComboBox";

export default function Preferences({
  config,
  connection,
  dirty,
  busy,
  running,
  error,
  notice,
  edit,
  editModelOptions,
  save,
  revert,
}: {
  config: Settings;
  connection?: Connection;
  dirty: boolean;
  busy: boolean;
  running: boolean;
  error: string;
  notice: string;
  edit: (key: keyof PreferenceValues, value: string) => void;
  editModelOptions: (model: string, value: ModelOptions) => void;
  save: () => void;
  revert: () => void;
}) {
  const [advanced, setAdvanced] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  useSaveForm(form);
  return (
    <form
      ref={form}
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
                <ComboBox
                  {...control}
                  required={!connection}
                  disabled={busy}
                  options={connection?.models ?? []}
                  value={String(config.values.model)}
                  placeholder="Choose or enter a model ID"
                  onChange={(value) => edit("model", value)}
                />
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
          <details
            className="settings-advanced"
            onToggle={(event) => setAdvanced(event.currentTarget.open)}
          >
            <summary>Advanced model options</summary>
            {advanced && (
              <ModelOptionsEditor
                config={config}
                connection={connection}
                edit={editModelOptions}
              />
            )}
          </details>
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
          title={`Save preferences (${shortcutLabel.save})`}
          aria-keyshortcuts={shortcutKeys.save}
          disabled={!dirty || busy || running}
        >
          Save preferences
        </Button>
      </ActionBar>
    </form>
  );
}
