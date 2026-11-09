import { useRef, useState } from "react";
import { ChevronDown, MoreHorizontal, Plus } from "lucide-react";
import { api } from "../../api/client";
import type { CompareModel, CompareRow } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useLanguages } from "../../app/LanguagesProvider";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { FadingNote } from "../../ui/FadingNote";
import { Feedback } from "../../ui/Feedback";
import { CheckField } from "../../ui/FieldRow";
import { Menu, MenuItem, MenuSeparator } from "../../ui/Menu";
import { PageBody } from "../../ui/PageLayout";
import { settingsSaved } from "../settings/settingsChanges";
import { AddModels } from "./AddModels";
import { ColumnSettings, GlossaryChoiceDialog } from "./ColumnSettings";
import type { CompareContext } from "./Compare";
import {
  CompareGrid,
  type CompareColumn,
  type Difference,
} from "./CompareGrid";
import { CompareRequest } from "./CompareRequest";
import {
  blindOrder,
  choiceKey,
  columnError,
  columnSummary,
  leftOut,
  modelDetail,
  namesHidden,
  nextStep,
  picks,
  recordedMarks,
  versusModels,
  working,
  type CompareMarks as Marks,
} from "./compareView";
import { LinesMenu, useSceneChoice } from "./LinesMenu";
import { sent, type ChosenModel } from "./ModelChoice";
import { useCompareRun } from "./useCompareRun";

/** A dialog the page has open over its columns. */
type Open =
  | { kind: "add" }
  | { kind: "model" | "settings"; column: number }
  | { kind: "request"; translationId: string; model: CompareModel }
  | { kind: "glossary"; comparisonId: string; model: CompareModel };

/**
 * Compare models' one workspace: the lines in rows and one column per
 * model, each with its own settings. One column shows one model's
 * translation; two to four side by side take a pick of the best of each
 * line, with the names hidden until every line is picked while Blind is on;
 * the same model twice with a changed setting shows that setting's effect.
 */
export function Workspace({ context }: { context: CompareContext }) {
  const application = useApplication();
  const languages = useLanguages();
  const [columns, setColumns] = useState<ChosenModel[] | null>(null);
  // The model Settings uses starts the page, once it is known.
  if (columns === null && context.base) setColumns([context.base]);
  const chosen = columns ?? [];
  const several = chosen.length > 1;
  const scene = useSceneChoice(context.state.scenes);
  const [blind, setBlind] = useState(true);
  const [marking, setMarking] = useState(false);
  const [open, setOpen] = useState<Open | null>(null);
  // Picks saved here stay ahead of the next read of the comparisons.
  const [saved, setSaved] = useState<Record<string, Marks>>({});
  const marksAction = useAction();
  const adopt = useAction({ observer: application });
  // The newest picks, which a second click before the next render builds on.
  const newest = useRef<Record<string, Marks>>({});
  const save = (translationId: string, next: Marks) => {
    newest.current[translationId] = next;
    setSaved((items) => ({ ...items, [translationId]: next }));
    marksAction.clear();
    api.compare
      .marks(
        context.projectId,
        translationId,
        next.marks,
        next.blind,
        next.revealed,
      )
      .catch((error: unknown) => marksAction.report(error, "marks"));
  };
  const candidates = chosen.map(sent);
  const keys = candidates.map(choiceKey);
  const run = useCompareRun(
    context,
    {
      kind: several ? "versus" : "single",
      file: scene.file,
      lines: scene.lines,
      candidates,
    },
    {
      blocked: !scene.file
        ? "This game has no lines to compare yet."
        : !chosen.length
          ? "Choose a model first."
          : new Set(keys).size < keys.length
            ? "Two columns send the same model and settings. Change one."
            : "",
      namesHidden: (comparison) =>
        namesHidden(
          comparison,
          recordedMarks(comparison, saved) ?? undefined,
          false,
        ),
      started: async (job) => {
        if (!several) return;
        const next = { marks: {}, blind, revealed: false };
        newest.current[job.id] = next;
        setSaved((items) => ({ ...items, [job.id]: next }));
        if (blind)
          await api.compare.marks(context.projectId, job.id, {}, true, false);
      },
    },
  );
  const { shown } = run;
  const translationId = shown?.translationId ?? null;
  // Whether its names show, from the moment it starts.
  const recorded = several ? recordedMarks(shown, saved) : null;
  // Picks start once every model's lines are in.
  const translated = !!translationId && !!shown && !working(shown.status);
  const mark = translated ? recorded : null;
  const score = shown && mark ? picks(shown, mark.marks) : null;
  const finished = !!score && score.total > 0 && score.picked === score.total;
  // Names stay hidden while the lines come in too.
  const hidden = several && namesHidden(shown, recorded ?? undefined, finished);
  const order =
    shown && several && (recorded?.blind ?? hidden)
      ? blindOrder(shown.id, shown.candidates.length)
      : chosen.map((_, index) => index);
  const next = translated && shown ? nextStep(shown, score) : null;
  const winner = several && !hidden ? next?.use?.model : undefined;
  const busy = run.action.busy;
  const edit = (index: number, change: ChosenModel | null) =>
    setColumns((items) =>
      (items ?? []).flatMap((item, place) =>
        place !== index ? [item] : change ? [change] : [],
      ),
    );
  const use = (model: CompareModel, glossary?: "game" | "test") => {
    if (!shown) return;
    if (model.glossaryChanged && !glossary) {
      setOpen({ kind: "glossary", comparisonId: shown.id, model });
      return;
    }
    void adopt.run(async () => {
      try {
        await api.compare.use(
          context.projectId,
          shown.id,
          model.index,
          glossary,
        );
      } catch (error) {
        // A glossary saved in Context since the last read asks next time.
        await context.reload();
        throw error;
      }
      settingsSaved();
    }, `Settings now translates with ${model.model}.`);
  };
  const columnsShown: CompareColumn[] = order.map((position, place) => {
    const model = shown?.candidates[position];
    const column = chosen[position];
    if (hidden)
      return {
        position,
        title: `Model ${place + 1}`,
        ...(model && leftOut(model)
          ? { warning: columnError(model, true) }
          : { error: model && columnError(model, true) }),
      };
    const wins =
      translated && model && !model.error && score && score.picked > 0
        ? `won ${score.won[position]}`
        : "";
    return {
      position,
      title: (
        <Button
          variant="link"
          className="compare-column-model"
          aria-label={`${column.model} on ${column.connection}. Choose another model`}
          disabled={busy}
          onClick={() => setOpen({ kind: "model", column: position })}
        >
          {column.model}
          <ChevronDown size={13} aria-hidden="true" />
        </Button>
      ),
      actions: (
        <Menu
          variant="quiet"
          className="compare-column-menu"
          label={`${column.model} column`}
          aria-label={`More for ${column.model}`}
          title="More"
          disabled={busy}
          trigger={<MoreHorizontal size={16} aria-hidden="true" />}
        >
          <MenuItem
            onSelect={() => setOpen({ kind: "settings", column: position })}
          >
            Change settings
          </MenuItem>
          {chosen.length < versusModels && (
            <MenuItem
              onSelect={() => {
                setColumns((items) => [
                  ...(items ?? []).slice(0, position + 1),
                  column,
                  ...(items ?? []).slice(position + 1),
                ]);
                // A copy differs once its settings do.
                setOpen({ kind: "settings", column: position + 1 });
              }}
            >
              Duplicate
            </MenuItem>
          )}
          {translationId && !!model?.keptRequests && (
            <MenuItem
              onSelect={() =>
                setOpen({ kind: "request", translationId, model })
              }
            >
              Show requests
            </MenuItem>
          )}
          {model?.finished && !run.running && (
            <MenuItem onSelect={() => use(model)}>Use this model</MenuItem>
          )}
          {several && (
            <>
              <MenuSeparator />
              <MenuItem onSelect={() => edit(position, null)}>Remove</MenuItem>
            </>
          )}
        </Menu>
      ),
      badge: winner === model && model && (
        <span className="compare-most">Most picked</span>
      ),
      subtitle: (
        <>
          {column.connection} ·{" "}
          <Button
            variant="link"
            className="compare-column-settings"
            disabled={busy}
            onClick={() => setOpen({ kind: "settings", column: position })}
          >
            {columnSummary(sent(column))}
          </Button>
        </>
      ),
      detail:
        model &&
        [wins, modelDetail(model, !!translationId)].filter(Boolean).join(" · "),
      ...(model && leftOut(model)
        ? { warning: model.error }
        : { error: model?.error }),
    };
  });
  const pick = (row: CompareRow, model: number | null) => {
    if (!translationId || !mark) return;
    const latest = newest.current[translationId] ?? mark;
    const marks = { ...latest.marks };
    if (model === null) delete marks[row.id];
    else marks[row.id] = model;
    save(translationId, { ...latest, marks });
  };
  // Mark differences: the words each column changed from the first shown.
  const difference = (
    row: CompareRow,
    position: number,
  ): Difference | undefined => {
    const first = row.translations[order[0]];
    const mine = row.translations[position];
    if (position === order[0] || !first || !mine) return undefined;
    return { other: first.text, side: "after" };
  };
  const tied =
    score && !hidden && score.tied.length && shown
      ? score.tied.map((position) => shown.candidates[position].model)
      : [];
  const progress =
    !several || !score?.total || run.running
      ? ""
      : finished
        ? `Every line picked${tied.length ? ` · ${tied.join(" and ")} tied` : ""}`
        : `Click the best translation of each line · ${score.picked} of ${score.total} picked`;
  const useModel = next?.use && (several ? !hidden && winner : true);
  const opened = open && "column" in open ? chosen[open.column] : undefined;
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
              disabled={busy}
            />
            {several && (
              <div className="compare-setup-options">
                <span className="compare-setup-option">
                  <CheckField
                    id="compare-blind"
                    label="Hide names until every line is picked"
                    checked={recorded ? recorded.blind : blind}
                    onChange={(checked) => {
                      setBlind(checked);
                      if (recorded && translationId)
                        save(translationId, {
                          ...(newest.current[translationId] ?? recorded),
                          blind: checked,
                          revealed: checked ? false : recorded.revealed,
                        });
                    }}
                  />
                  {hidden && translationId && recorded && (
                    <Button
                      variant="link"
                      onClick={() =>
                        save(translationId, {
                          ...(newest.current[translationId] ?? recorded),
                          revealed: true,
                        })
                      }
                    >
                      Reveal now
                    </Button>
                  )}
                </span>
                {!!score?.total && (
                  <CheckField
                    id="compare-differences"
                    label="Mark differences"
                    checked={marking}
                    onChange={setMarking}
                  />
                )}
              </div>
            )}
          </div>
        </div>
        <CompareGrid
          label="Translations by model"
          comparison={shown}
          columns={columnsShown}
          add={
            chosen.length < versusModels && (
              <span className="compare-grid-add-header">
                <Button
                  variant="link"
                  disabled={busy}
                  onClick={() => setOpen({ kind: "add" })}
                >
                  <Plus size={14} aria-hidden="true" />
                  Add model
                </Button>
                <span className="compare-grid-detail">
                  Up to {versusModels}
                </span>
              </span>
            )
          }
          marks={mark?.marks}
          pick={several && translated ? pick : undefined}
          difference={several && translated && marking ? difference : undefined}
          empty={run.empty(
            several
              ? "Estimate the cost to see these lines side by side."
              : `Estimate the cost to see these lines in ${languages.target}.`,
          )}
        />
      </PageBody>
      <ActionBar
        feedback={
          marksAction.error || adopt.error ? (
            <Feedback error={marksAction.error || adopt.error} />
          ) : adopt.notice ? (
            // Done once Settings switched, so it fades.
            <FadingNote onGone={adopt.clear}>
              <Feedback notice={adopt.notice} />
            </FadingNote>
          ) : (
            <div className="feedback" role="status">
              {progress}
            </div>
          )
        }
      >
        {run.footer({
          again: !!next?.again,
          use: useModel && next?.use && (
            <ActionControl
              variant="primary"
              label={next.use.label}
              title="Make it the connection, model and settings this game translates with."
              pending={adopt.busy}
              pendingText="Switching model…"
              onClick={() => use(next.use!.model)}
            />
          ),
        })}
      </ActionBar>
      {open?.kind === "add" && (
        <AddModels
          mode="many"
          chosen={chosen}
          room={versusModels - chosen.length}
          add={(added) => setColumns((items) => [...(items ?? []), ...added])}
          close={() => setOpen(null)}
        />
      )}
      {open?.kind === "model" && opened && (
        <AddModels
          mode="one"
          chosen={[opened]}
          add={([model]) =>
            // Efforts differ by model, so a new one starts from its own.
            edit(open.column, {
              ...model,
              ...(opened.glossary !== undefined && {
                glossary: opened.glossary,
                glossary_revision: opened.glossary_revision,
              }),
              ...(opened.instruction && { instruction: opened.instruction }),
            })
          }
          close={() => setOpen(null)}
        />
      )}
      {open?.kind === "settings" && opened && (
        <ColumnSettings
          column={opened}
          game={{
            glossary: context.state.glossary,
            glossaryRevision: context.state.glossaryRevision,
            effort: context.gameEffort(opened.model),
          }}
          save={(column) => edit(open.column, column)}
          close={() => setOpen(null)}
        />
      )}
      {open?.kind === "request" && (
        <CompareRequest
          projectId={context.projectId}
          translationId={open.translationId}
          model={open.model}
          close={() => setOpen(null)}
        />
      )}
      {open?.kind === "glossary" &&
        open.model.choice.glossary !== undefined && (
          <GlossaryChoiceDialog
            game={context.state.glossary}
            test={open.model.choice.glossary}
            choose={(glossary) => {
              setOpen(null);
              use(open.model, glossary);
            }}
            cancel={() => setOpen(null)}
          />
        )}
    </>
  );
}
