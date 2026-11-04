import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { api } from "../../api/client";
import type {
  CompareChoice,
  CompareRow,
  EffortLevel,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useLanguages } from "../../app/LanguagesProvider";
import { useAction } from "../../state/useAction";
import { useRead } from "../../state/useRead";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Menu, MenuItem, MenuSeparator } from "../../ui/Menu";
import { Modal } from "../../ui/Modal";
import { PageBody } from "../../ui/PageLayout";
import { SegmentedControl } from "../../ui/SegmentedControl";
import { useTabPanelShown } from "../../ui/Tabs";
import { settingsSaved } from "../settings/settingsChanges";
import type { CompareContext } from "./Compare";
import { CompareGrid } from "./CompareGrid";
import {
  glossaryChanges,
  glossaryEntries,
  modelDetail,
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
  /** Guidance this test adds to the game's. */
  instruction: string;
};

/** The game's settings, which a test starts from and Reset returns to. */
const start = (context: CompareContext): Settings | null =>
  context.base && {
    model: context.base,
    effort: context.baseEffort,
    glossary: null,
    instruction: "",
  };

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
 * Tune settings: one model's translation of the lines with its thinking
 * effort, glossary or an instruction changed for the test, marking what
 * changed since an earlier run of the same lines.
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
    ...(changed.glossary && { glossary }),
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
  // The lines show this test's run, else the last run of these lines.
  const shown =
    run.shown?.stage === "translation" ? run.shown : (runs.at(-1) ?? run.shown);
  const number = shown ? runs.indexOf(shown) + 1 : 0;
  const [chosenSince, setSince] = useState<string | null>();
  const earlier = runs.slice(0, Math.max(0, number - 1));
  const since =
    chosenSince === null
      ? undefined
      : (earlier.find((item) => item.id === chosenSince) ?? earlier.at(-1));
  const texts = new Map(
    (since?.rows ?? []).map((row) => [row.id, row.translations[0]?.text]),
  );
  const before = (row: CompareRow) => texts.get(row.id);
  const result = shown?.candidates[0];
  const translated = !!shown?.translationId && result?.cost !== undefined;
  const current = translated && shown === run.shown;
  const [editing, setEditing] = useState(false);
  const adopt = useAction({ observer: application });
  const edit = (change: Partial<Settings>) =>
    setSettings((value) => value && { ...value, ...change });
  const count = glossaryEntries(glossary).length;
  const edits = changed.glossary ? glossaryChanges(gameGlossary, glossary) : 0;
  const disabled = run.action.busy;
  const detail = shown && (
    <>
      {[
        number > 0 && `Run ${number}`,
        result && modelDetail(result, !!shown.translationId),
      ]
        .filter(Boolean)
        .join(" · ")}
      {earlier.length > 0 && (
        <>
          {" · "}
          <Menu
            variant="link"
            label="Mark changes since"
            align="start"
            trigger={
              <>
                {since
                  ? `changes since run ${runs.indexOf(since) + 1}`
                  : "no changes marked"}
                <ChevronDown size={13} aria-hidden="true" />
              </>
            }
          >
            {[...earlier].reverse().map((item) => {
              const model = item.candidates[0];
              return (
                <MenuItem
                  key={item.id}
                  current={item === since}
                  description={[
                    model.model,
                    model.effort ? `${model.effort} effort` : "",
                    model.glossary !== undefined ? "test glossary" : "",
                    model.instruction ? "instruction" : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  onSelect={() => setSince(item.id)}
                >
                  Changes since run {runs.indexOf(item) + 1}
                </MenuItem>
              );
            })}
            <MenuSeparator />
            <MenuItem current={!since} onSelect={() => setSince(null)}>
              Mark no changes
            </MenuItem>
          </Menu>
        </>
      )}
    </>
  );
  return (
    <>
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
            comparison={shown}
            columns={[
              {
                position: 0,
                title: languages.target,
                detail,
                error: result?.error,
              },
            ]}
            before={since ? before : undefined}
            empty={run.empty(
              "Estimate the cost to see these lines translated.",
            )}
          />
        </div>
      </PageBody>
      <ActionBar feedback={null}>
        <ActionControl
          label="Use these settings"
          title="Make this model Settings' model for every game, and save its effort, glossary and instruction as this game's."
          disabled={!current}
          disabledReason={
            translated && !current ? "Translate with these settings first." : ""
          }
          pending={adopt.busy}
          pendingText="Saving the settings…"
          error={adopt.error}
          notice={adopt.notice}
          onClick={() =>
            void adopt.run(async () => {
              await api.compare.use(context.projectId, shown.id, 0);
              settingsSaved();
              context.reload();
              // They are the game's settings now, which the next test
              // starts from.
              edit({ glossary: null, instruction: "" });
            }, "Saved as the game’s settings.")
          }
        />
        {run.control}
      </ActionBar>
      {editing && (
        <GlossaryDialog
          text={glossary}
          save={(text) =>
            edit({ glossary: text === gameGlossary ? null : text })
          }
          close={() => setEditing(false)}
        />
      )}
    </>
  );
}
