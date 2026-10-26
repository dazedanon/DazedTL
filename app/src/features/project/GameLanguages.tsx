/** A game's languages: the source and target fields Settings and Set up
 * share, and Set up's row that shows the game's pair and changes it until
 * the game has work (backend/dazedtl/projects/languages.py). */
import { useState } from "react";
import { api } from "../../api/client";
import {
  SOURCE_LANGUAGES,
  type GameLanguages as Languages,
  type SourceLanguage,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { pairLabel } from "../../app/languages";
import { useLanguages } from "../../app/LanguagesProvider";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Message } from "../../ui/Feedback";
import { FieldRow } from "../../ui/FieldRow";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";

/** The source language list and the target language field. */
export function LanguageFields({
  id,
  source,
  target,
  sourceHelp,
  onSource,
  onTarget,
}: {
  id: string;
  source: string;
  target: string;
  sourceHelp?: string;
  onSource: (value: SourceLanguage) => void;
  onTarget: (value: string) => void;
}) {
  return (
    <>
      <FieldRow id={`${id}-source`} label="Source language" help={sourceHelp}>
        {(control) => (
          <select
            {...control}
            className="short-control"
            value={source}
            onChange={(event) => onSource(event.target.value as SourceLanguage)}
          >
            {SOURCE_LANGUAGES.map((language) => (
              <option key={language} value={language}>
                {language}
              </option>
            ))}
          </select>
        )}
      </FieldRow>
      <FieldRow id={`${id}-target`} label="Target language">
        {(control) => (
          <input
            {...control}
            required
            value={target}
            onChange={(event) => onTarget(event.target.value)}
          />
        )}
      </FieldRow>
    </>
  );
}

/**
 * Set up's row for the game's languages. Given where the user measures Line
 * widths, it points there for a target written in Chinese or Japanese
 * characters, since the stock widths are measured on English text and fit
 * it too wide; Assistant-led's assistant measures them itself.
 */
export function GameLanguagesRow({
  projectId,
  disabled,
  measure,
}: {
  projectId: string;
  disabled: boolean;
  /** Opens the Line widths measurement. */
  measure?: () => void;
}) {
  const languages = useLanguages();
  const [changing, setChanging] = useState(false);
  return (
    <>
      <ActionList>
        <ActionRow title="Languages" description={pairLabel(languages)}>
          <Button disabled={disabled} onClick={() => setChanging(true)}>
            Change…
          </Button>
        </ActionRow>
      </ActionList>
      {languages.characters && measure && (
        <Notice>
          <span>
            The stock Line widths are measured on English text and fit{" "}
            {languages.target} about 15% too wide. Measure them in the running
            game before you apply translations.
          </span>
          <Button variant="link" onClick={measure}>
            Open Line widths
          </Button>
        </Notice>
      )}
      {changing && (
        <LanguagesDialog
          projectId={projectId}
          languages={languages}
          close={() => setChanging(false)}
        />
      )}
    </>
  );
}

function LanguagesDialog({
  projectId,
  languages,
  close,
}: {
  projectId: string;
  languages: Languages;
  close: () => void;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const [source, setSource] = useState<SourceLanguage>(languages.source);
  const [target, setTarget] = useState(languages.target);
  const unchanged =
    source === languages.source && target.trim() === languages.target;
  const edit =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      action.clear();
      set(value);
    };
  return (
    <Modal
      label="Change languages"
      size="sm"
      dismissible={!action.busy}
      onDismiss={close}
    >
      <DialogHeader title="Change this game's languages?" />
      <DialogBody>
        <p>
          Every run on this game translates these languages, so they can change
          only until its first run.
        </p>
        <LanguageFields
          id="game-languages"
          source={source}
          target={target}
          onSource={edit(setSource)}
          onTarget={edit(setTarget)}
        />
      </DialogBody>
      <ActionBar feedback={<Message message={action.error} />}>
        <Button data-autofocus disabled={action.busy} onClick={close}>
          Cancel
        </Button>
        <Button
          variant="primary"
          pending={action.busy}
          disabled={unchanged || !target.trim()}
          onClick={() =>
            void action.run(async () => {
              await api.languages(projectId, source, target);
              close();
            })
          }
        >
          Save languages
        </Button>
      </ActionBar>
    </Modal>
  );
}
