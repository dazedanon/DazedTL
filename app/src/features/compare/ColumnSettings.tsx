import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { EffortLevel } from "../../api/contracts";
import { useRead } from "../../state/useRead";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { lineDiff } from "../../ui/lineDiff";
import { Modal } from "../../ui/Modal";
import { SegmentedControl } from "../../ui/SegmentedControl";
import { TextDiff } from "../../ui/TextDiff";
import { glossaryChanges, glossaryEntries } from "./compareView";
import type { ChosenModel } from "./ModelChoice";

/** A setting's row: its label, marked once the column changes it. */
function Setting({
  id,
  label,
  changed,
  children,
}: {
  id: string;
  label: string;
  changed: boolean;
  children: ReactNode;
}) {
  return (
    <div className="field-row">
      <span className="field-label compare-setting-label" id={id}>
        {label}
        {changed && (
          <span
            className="compare-changed"
            role="img"
            aria-label="Changed for this column"
          />
        )}
      </span>
      <div className="field-control" role="group" aria-labelledby={id}>
        {children}
      </div>
    </div>
  );
}

/**
 * Column settings: what one column sends besides its model, starting from
 * the game's: the thinking effort, a test glossary and an instruction added
 * to the game's guidance. Only comparisons send them until Use saves them.
 */
export function ColumnSettings({
  column,
  game,
  save,
  close,
}: {
  column: ChosenModel;
  game: {
    glossary: string;
    glossaryRevision: string;
    /** The effort Settings sends this column's model. */
    effort: EffortLevel | null;
  };
  save: (column: ChosenModel) => void;
  close: () => void;
}) {
  const [effort, setEffort] = useState(column.effort);
  const [glossary, setGlossary] = useState(column.glossary ?? game.glossary);
  const [instruction, setInstruction] = useState(column.instruction ?? "");
  const efforts = useRead(
    JSON.stringify([column.connection_id, column.model]),
    () => api.compare.model(column.connection_id, column.model),
  );
  const options = efforts.value?.efforts;
  const changed = {
    effort: effort !== undefined,
    glossary: glossary !== game.glossary,
    instruction: !!instruction.trim(),
  };
  const count = glossaryEntries(glossary).length;
  const edits = changed.glossary ? glossaryChanges(game.glossary, glossary) : 0;
  // The game's effort is no change, so the column keeps following Settings.
  const pick = (value: EffortLevel | null) =>
    setEffort(value === game.effort ? undefined : value);
  const shown = effort === undefined ? game.effort : effort;
  return (
    <Modal label="Column settings" size="md" onDismiss={close}>
      <DialogHeader
        title="Column settings"
        description={`${column.model} on ${column.connection}. Only comparisons send these; Use saves them as the game’s.`}
        onClose={close}
      />
      <DialogBody>
        <Setting
          id="column-effort"
          label="Thinking effort"
          changed={changed.effort}
        >
          {!options ? (
            <span className="muted compare-setting-value">
              {efforts.error ? "Unavailable" : "Loading…"}
            </span>
          ) : options.length < 2 ? (
            <span className="muted compare-setting-value">
              {options[0]?.label ?? "Not offered for this model"}
            </span>
          ) : options.length > 4 ? (
            // More levels than fit beside the label read as a list.
            <select
              aria-labelledby="column-effort"
              value={shown ?? ""}
              onChange={(event) =>
                pick((event.target.value || null) as EffortLevel | null)
              }
            >
              {options.map((item) => (
                <option key={item.value ?? ""} value={item.value ?? ""}>
                  {item.label}
                </option>
              ))}
            </select>
          ) : (
            <SegmentedControl
              label="Thinking effort"
              value={shown ?? "default"}
              options={options.map((item) => ({
                value: item.value ?? "default",
                label: item.value ? item.label : "Default",
                title: item.value ? undefined : item.label,
              }))}
              onChange={(value) =>
                pick(value === "default" ? null : (value as EffortLevel))
              }
            />
          )}
        </Setting>
        <Setting
          id="column-instruction"
          label="Instruction"
          changed={changed.instruction}
        >
          <textarea
            aria-labelledby="column-instruction"
            rows={3}
            placeholder="Guidance this column adds to the game’s, such as how a character speaks"
            value={instruction}
            data-autofocus
            onChange={(event) => setInstruction(event.target.value)}
          />
        </Setting>
        <Setting
          id="column-glossary"
          label="Glossary"
          changed={changed.glossary}
        >
          <textarea
            className="compare-glossary-editor"
            aria-labelledby="column-glossary"
            aria-describedby="column-glossary-count"
            spellCheck={false}
            value={glossary}
            onChange={(event) => setGlossary(event.target.value)}
          />
          <small id="column-glossary-count" className="muted">
            {count.toLocaleString()} {count === 1 ? "entry" : "entries"}
            {edits > 0 && ` · ${edits} changed for this column`}
          </small>
        </Setting>
      </DialogBody>
      <ActionBar
        feedback={
          <Button
            variant="link"
            className="compare-settings-reset"
            disabled={!Object.values(changed).some(Boolean)}
            onClick={() => {
              setEffort(undefined);
              setGlossary(game.glossary);
              setInstruction("");
            }}
          >
            Reset to the game’s
          </Button>
        }
      >
        <Button onClick={close}>Cancel</Button>
        <Button
          variant="primary"
          onClick={() => {
            const {
              effort: _effort,
              glossary: _glossary,
              glossary_revision: _revision,
              instruction: _instruction,
              ...model
            } = column;
            save({
              ...model,
              ...(effort !== undefined && { effort }),
              ...(changed.glossary && {
                glossary,
                // An edit of an edit keeps what the first started from.
                glossary_revision:
                  column.glossary_revision ?? game.glossaryRevision,
              }),
              ...(changed.instruction && { instruction: instruction.trim() }),
            });
            close();
          }}
        >
          Save
        </Button>
      </ActionBar>
    </Modal>
  );
}

/**
 * Asks which glossary Use keeps when the game's changed in Context after
 * this column's glossary edit, as Save asks about a document changed on
 * disk (DocumentsChangedDialog).
 */
export function GlossaryChoiceDialog({
  game,
  test,
  choose,
  cancel,
}: {
  game: string;
  test: string;
  choose: (glossary: "game" | "test") => void;
  cancel: () => void;
}) {
  return (
    <Modal label="Glossary changed in Context" size="sm" onDismiss={cancel}>
      <DialogHeader title="Keep the game’s glossary or this column’s?" />
      <DialogBody>
        <p>The game’s glossary changed in Context after this column’s edit.</p>
        <section>
          <p className="muted">
            This column’s glossary (+) compared with the game’s (−):
          </p>
          <TextDiff
            diff={lineDiff(game, test)}
            label="This column’s glossary compared with the game’s"
          />
        </section>
        <p className="muted">
          Keeping this column’s replaces the game’s glossary. Keeping the game’s
          saves the model and instruction without this column’s glossary.
        </p>
      </DialogBody>
      <ActionBar feedback={null}>
        <Button data-autofocus onClick={cancel}>
          Cancel
        </Button>
        <Button onClick={() => choose("game")}>Keep the game’s</Button>
        <Button variant="primary" onClick={() => choose("test")}>
          Keep this column’s
        </Button>
      </ActionBar>
    </Modal>
  );
}
