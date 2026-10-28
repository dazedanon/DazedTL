import { useRef } from "react";
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
import { LanguageFields } from "../project/GameLanguages";
import { ActionBar } from "../../ui/ActionBar";
import { Feedback } from "../../ui/Feedback";
import { Button } from "../../ui/Button";

/**
 * What new translations start with: the languages new games translate
 * between and per-model request options. The model itself is chosen on the connection panel.
 */
export default function TranslationDefaults({
  config,
  connection,
  dirty,
  busy,
  running,
  error,
  notice,
  advanced,
  setAdvanced,
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
  /** Whether Advanced model options is open; Settings keeps it across tabs. */
  advanced: boolean;
  setAdvanced: (open: boolean) => void;
  edit: (key: keyof PreferenceValues, value: string) => void;
  editModelOptions: (model: string, value: ModelOptions) => void;
  save: () => void;
  revert: () => void;
}) {
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
          <LanguageFields
            id="default-languages"
            source={config.values.sourceLanguage}
            target={String(config.values.language)}
            sourceHelp="New games start with these languages; each game's own are in its Set up."
            onSource={(value) => edit("sourceLanguage", value)}
            onTarget={(value) => edit("language", value)}
          />
          <details
            className="settings-advanced"
            open={advanced}
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
                ? "Save defaults after the current run finishes."
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
          title={`Save defaults (${shortcutLabel.save})`}
          aria-keyshortcuts={shortcutKeys.save}
          disabled={!dirty || busy || running}
        >
          Save defaults
        </Button>
      </ActionBar>
    </form>
  );
}
