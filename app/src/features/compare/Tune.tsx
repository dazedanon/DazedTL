import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { api } from "../../api/client";
import type {
  CompareChoice,
  CompareRow,
  Comparison,
  EffortLevel,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useLanguages } from "../../app/LanguagesProvider";
import { useAction } from "../../state/useAction";
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { lineDiff } from "../../ui/lineDiff";
import { Menu, MenuItem, MenuSeparator } from "../../ui/Menu";
import { Modal } from "../../ui/Modal";
import { PageBody, PageMessages } from "../../ui/PageLayout";
import { SegmentedControl } from "../../ui/SegmentedControl";
import { useTabPanelShown } from "../../ui/Tabs";
import { TextDiff } from "../../ui/TextDiff";
import { settingsSaved } from "../settings/settingsChanges";
import type { CompareContext } from "./Compare";
import { CompareGrid, type Difference } from "./CompareGrid";
import {
  glossaryChanges,
  glossaryEntries,
  modelDetail,
  runName,
  tuneRuns,
} from "./compareView";
import { LinesMenu, useSceneChoice } from "./LinesMenu";
import { ModelLink, type ChosenModel } from "./ModelChoice";
import { useCompareRun } from "./useCompareRun";

type Settings = {
  model: ChosenModel;
  effort: EffortLevel | null;
  /** The whole glossary this test sends; null keeps the game's. */
  glossary: string | null;
  /** The revision of the game's glossary that one was edited from, which
   * tells Use these settings whether Context saved over it since. */
  glossaryRevision: string | null;
  /** Guidance this test adds to the game's. */
  instruction: string;
};

/** The game's settings, which a test starts from and Reset returns to. */
const start = (context: CompareContext): Settings | null =>
  context.base && {
    model: context.base,
    effort: context.baseEffort,
    glossary: null,
    glossaryRevision: null,
    instruction: "",
  };

/** What a run changed from the game's settings, in a few words. */
function settingsOf(item: Comparison) {
  const { choice } = item.candidates[0];
  return [
    choice.model,
    choice.effort ? `${choice.effort} effort` : "",
    choice.glossary !== undefined ? "test glossary" : "",
    choice.instruction ? "instruction" : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** A setting's row: its label, marked once the test changes it. */
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
      <span className="field-label" id={id}>
        {label}
        {changed && (
          <span
            className="compare-changed"
            role="img"
            aria-label="Changed for this test"
          />
        )}
      </span>
      <div className="field-control" role="group" aria-labelledby={id}>
        {children}
      </div>
    </div>
  );
}

/** Edits the glossary this test sends, starting from the game's. */
function GlossaryDialog({
  text,
  save,
  close,
}: {
  text: string;
  save: (text: string) => void;
  close: () => void;
}) {
  const [draft, setDraft] = useState(text);
  return (
    <Modal label="Glossary for this test" size="md" onDismiss={close}>
      <DialogHeader
        title="Glossary for this test"
        description="Only this test sends it. Use these settings saves it as the game’s glossary."
        onClose={close}
      />
      <DialogBody>
        <textarea
          className="compare-glossary-editor"
          aria-label="Glossary"
          spellCheck={false}
          value={draft}
          data-autofocus
          onChange={(event) => setDraft(event.target.value)}
        />
      </DialogBody>
      <ActionBar feedback={null}>
        <Button onClick={close}>Cancel</Button>
        <Button
          variant="primary"
          onClick={() => {
            save(draft);
            close();
          }}
        >
          Save for this test
        </Button>
      </ActionBar>
    </Modal>
  );
}

/**
 * Asks which glossary Use these settings keeps when the game's changed in
 * Context after this test's edit, as Save asks about a document changed on
 * disk (DocumentsChangedDialog).
 */
function GlossaryChoiceDialog({
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
      <DialogHeader title="Keep the game’s glossary or this test’s?" />
      <DialogBody>
        <p>The game’s glossary changed in Context after this test’s edit.</p>
        <section>
          <p className="muted">
            This test’s glossary (+) compared with the game’s (−):
          </p>
          <TextDiff
            diff={lineDiff(game, test)}
            label="This test’s glossary compared with the game’s"
          />
        </section>
        <p className="muted">
          Keeping this test’s replaces the game’s glossary. Keeping the game’s
          saves the model and instruction without this test’s glossary.
        </p>
      </DialogBody>
      <ActionBar feedback={null}>
        <Button data-autofocus onClick={cancel}>
          Cancel
        </Button>
        <Button onClick={() => choose("game")}>Keep the game’s</Button>
        <Button variant="primary" onClick={() => choose("test")}>
          Keep this test’s
        </Button>
      </ActionBar>
    </Modal>
  );
}

/**
 * Tune settings: one model's translation of the lines with its thinking
 * effort, glossary or an instruction changed for the test, marking what
 * the words that changed between two runs of the same lines it shows side
 * by side.
 */
export function Tune({ context }: { context: CompareContext }) {
  const application = useApplication();
  const languages = useLanguages();
  const scene = useSceneChoice(context.state.scenes);
  const { base } = context;
  const [settings, setSettings] = useState<Settings | null>(null);
  if (settings === null && base) setSettings(start(context));
  // A hidden tab reads nothing until it first shows.
  const panelShown = useTabPanelShown();
  const [seen, setSeen] = useState(false);
  if (panelShown && !seen) setSeen(true);
  const efforts = useRead(
    settings && seen
      ? JSON.stringify([settings.model.connection_id, settings.model.model])
      : null,
    () =>
      api.compare.model(settings!.model.connection_id, settings!.model.model),
  );
  const options = efforts.value?.efforts;
  // An effort the chosen model doesn't take sends its default instead.
  const effort =
    settings &&
    options &&
    !options.some((item) => item.value === settings.effort)
      ? null
      : (settings?.effort ?? null);
  const gameGlossary = context.state.glossary;
  const glossary = settings?.glossary ?? gameGlossary;
  const instruction = settings?.instruction.trim() ?? "";
  const changed = {
    model:
      !!settings &&
      !!base &&
      (settings.model.connection_id !== base.connection_id ||
        settings.model.model !== base.model),
    effort: !!base && effort !== context.baseEffort,
    glossary: glossary !== gameGlossary,
    instruction: !!instruction,
  };
  const candidate: CompareChoice | null = settings && {
    connection_id: settings.model.connection_id,
    model: settings.model.model,
    effort,
    ...(changed.glossary && {
      glossary,
      glossary_revision:
        settings.glossaryRevision ?? context.state.glossaryRevision,
    }),
    ...(instruction && { instruction }),
  };
  const run = useCompareRun(
    context,
    {
      kind: "tune",
      file: scene.file,
      lines: scene.lines,
      candidates: candidate ? [candidate] : [],
    },
    {
      blocked: !scene.file
        ? "This game has no lines to compare yet."
        : !candidate
          ? "Choose a model first."
          : "",
    },
  );
  const runs = tuneRuns(context.comparisons, scene.file, scene.lines);
  // The newest run shows on the right, this test's once it is translated,
  // beside the run before it, until the user picks other runs.
  const latest =
    run.shown?.stage === "translation" ? run.shown : (runs.at(-1) ?? run.shown);
  const [chosen, setChosen] = useState<{
    left?: string | null;
    right?: string;
  }>({});
  useOnChange(latest?.id, () => setChosen({}));
  const shown = runs.find((item) => item.id === chosen.right) ?? latest;
  const position = shown ? runs.indexOf(shown) : -1;
  const left =
    chosen.left === null
      ? undefined
      : (runs.find((item) => item.id === chosen.left && item !== shown) ??
        (position > 0 ? runs[position - 1] : undefined));
  const name = (item: Comparison) => runName(runs, item);
  const pickRun = (
    side: "left" | "right",
    value: Comparison | undefined,
    choose: (id: string | null) => void,
  ) =>
    runs.length > 1 ? (
      <Menu
        variant="link"
        label={side === "left" ? "Compare with" : "Show run"}
        align="start"
        trigger={
          <>
            {value ? name(value) : "Compare with a run"}
            <ChevronDown size={13} aria-hidden="true" />
          </>
        }
      >
        {[...runs].reverse().map((item) => (
          <MenuItem
            key={item.id}
            current={item === value}
            description={settingsOf(item)}
            disabled={side === "left" ? item === shown : item === left}
            onSelect={() => choose(item.id)}
          >
            {name(item)}
          </MenuItem>
        ))}
        {side === "left" && (
          <>
            <MenuSeparator />
            <MenuItem current={!value} onSelect={() => choose(null)}>
              Show one run
            </MenuItem>
          </>
        )}
      </Menu>
    ) : value ? (
      name(value)
    ) : (
      languages.target
    );
  const pair = left && shown ? [left, shown] : shown ? [shown] : [];
  const grid: Comparison | undefined =
    left && shown
      ? {
          ...shown,
          candidates: [left.candidates[0], shown.candidates[0]],
          rows: shown.rows.map((row) => {
            const earlier = left.rows.find((item) => item.id === row.id);
            return {
              ...row,
              translations: [
                earlier?.translations[0] ?? null,
                row.translations[0] ?? null,
              ],
              problems: [earlier?.problems[0] ?? [], row.problems[0] ?? []],
            };
          }),
        }
      : shown;
  const difference = (
    row: CompareRow,
    column: number,
  ): Difference | undefined => {
    const [before, after] = row.translations;
    if (!left || !before || !after) return undefined;
    return column === 0
      ? { other: after.text, side: "before" }
      : { other: before.text, side: "after" };
  };
  const result = shown?.candidates[0];
  const translated = !!result?.finished;
  const current = translated && shown === run.shown;
  const [editing, setEditing] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const adopt = useAction({ observer: application });
  const edit = (change: Partial<Settings>) =>
    setSettings((value) => value && { ...value, ...change });
  const use = (id: string, glossary?: "game" | "test") =>
    void adopt.run(async () => {
      try {
        await api.compare.use(context.projectId, id, 0, glossary);
      } catch (error) {
        // A glossary saved in Context since the last read asks next time.
        await context.reload();
        throw error;
      }
      settingsSaved();
      await context.reload();
      // They are the game's settings now, which the next test starts from.
      edit({ glossary: null, glossaryRevision: null, instruction: "" });
    }, `Settings now translates with ${result?.model}.`);
  const count = glossaryEntries(glossary).length;
  const edits = changed.glossary ? glossaryChanges(gameGlossary, glossary) : 0;
  const disabled = run.action.busy;
  const detail = (item: Comparison) =>
    [modelDetail(item.candidates[0], !!item.translationId), settingsOf(item)]
      .filter(Boolean)
      .join(" · ");
  return (
    <>
      <PageMessages>{run.notice}</PageMessages>
      <PageBody className="compare-body">
        <div className="compare-setup">
          <div className="compare-setup-row">
            <LinesMenu
              scenes={context.state.scenes}
              file={scene.file}
              lines={scene.lines}
              change={scene.change}
              disabled={disabled}
            />
          </div>
        </div>
        <div className="compare-tune">
          <div className="compare-tune-settings">
            <div className="compare-tune-head">
              <span className="muted">Starts from the game’s settings</span>
              <Button
                variant="link"
                disabled={
                  disabled || !base || !Object.values(changed).some(Boolean)
                }
                onClick={() => setSettings(start(context))}
              >
                Reset
              </Button>
            </div>
            <Setting id="tune-model" label="Model" changed={changed.model}>
              <ModelLink
                label=""
                model={settings?.model}
                change={(model) => edit({ model })}
                disabled={disabled}
              />
            </Setting>
            <Setting
              id="tune-effort"
              label="Thinking effort"
              changed={changed.effort}
            >
              {!options ? (
                <span className="muted compare-tune-value">
                  {efforts.error ? "Unavailable" : "Loading…"}
                </span>
              ) : options.length < 2 ? (
                <span className="muted compare-tune-value">
                  {options[0]?.label ?? "Not offered for this model"}
                </span>
              ) : options.length > 4 ? (
                // More levels than fit beside the label read as a list.
                <select
                  aria-labelledby="tune-effort"
                  value={effort ?? ""}
                  disabled={disabled}
                  onChange={(event) =>
                    edit({
                      effort: (event.target.value ||
                        null) as EffortLevel | null,
                    })
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
                  value={effort ?? "default"}
                  disabled={disabled}
                  options={options.map((item) => ({
                    value: item.value ?? "default",
                    label: item.value ? item.label : "Default",
                    title: item.value ? undefined : item.label,
                  }))}
                  onChange={(value) =>
                    edit({
                      effort:
                        value === "default" ? null : (value as EffortLevel),
                    })
                  }
                />
              )}
            </Setting>
            <Setting
              id="tune-glossary"
              label="Glossary"
              changed={changed.glossary}
            >
              <Button
                variant="link"
                className="compare-tune-value"
                disabled={disabled}
                onClick={() => setEditing(true)}
              >
                {count.toLocaleString()} {count === 1 ? "entry" : "entries"}
                {edits > 0 && ` · ${edits} changed for this test`}
              </Button>
            </Setting>
            <Setting
              id="tune-instruction"
              label="Instruction"
              changed={changed.instruction}
            >
              <textarea
                aria-labelledby="tune-instruction"
                rows={3}
                placeholder="Guidance this test adds to the game’s, such as how a character speaks"
                value={settings?.instruction ?? ""}
                disabled={disabled}
                onChange={(event) => edit({ instruction: event.target.value })}
              />
            </Setting>
          </div>
          <CompareGrid
            label="Translation with these settings"
            comparison={grid}
            columns={pair.map((item, index) => ({
              position: index,
              title:
                index === 0 && pair.length > 1
                  ? pickRun("left", item, (id) =>
                      setChosen((value) => ({ ...value, left: id })),
                    )
                  : pickRun("right", item, (id) =>
                      setChosen((value) => ({
                        ...value,
                        right: id ?? undefined,
                      })),
                    ),
              detail: (
                <>
                  {detail(item)}
                  {pair.length === 1 && runs.length > 1 && (
                    <>
                      {" · "}
                      {pickRun("left", undefined, (id) =>
                        setChosen((value) => ({ ...value, left: id })),
                      )}
                    </>
                  )}
                </>
              ),
              error: item.candidates[0]?.error,
            }))}
            difference={left ? difference : undefined}
            empty={run.empty(
              "Estimate the cost to see these lines translated.",
            )}
          />
        </div>
      </PageBody>
      <ActionBar feedback={null}>
        {translated && (
          <ActionControl
            label="Use these settings"
            title="Make this model and its thinking effort what Settings translates with, for every game, and save the glossary and instruction as this game's."
            disabled={!current || !!run.waiting}
            disabledReason={
              run.waiting || "Translate with these settings first."
            }
            pending={adopt.busy}
            pendingText="Saving the settings…"
            error={adopt.error}
            notice={adopt.notice}
            onClick={() =>
              result?.glossaryChanged ? setChoosing(true) : use(shown.id)
            }
          />
        )}
        {run.control()}
      </ActionBar>
      {choosing && shown && result?.choice.glossary !== undefined && (
        <GlossaryChoiceDialog
          game={gameGlossary}
          test={result.choice.glossary}
          choose={(glossary) => {
            setChoosing(false);
            use(shown.id, glossary);
          }}
          cancel={() => setChoosing(false)}
        />
      )}
      {editing && (
        <GlossaryDialog
          text={glossary}
          save={(text) =>
            edit(
              text === gameGlossary
                ? { glossary: null, glossaryRevision: null }
                : {
                    glossary: text,
                    // An edit of an edit keeps what the first started from.
                    glossaryRevision:
                      settings?.glossaryRevision ??
                      context.state.glossaryRevision,
                  },
            )
          }
          close={() => setEditing(false)}
        />
      )}
    </>
  );
}
