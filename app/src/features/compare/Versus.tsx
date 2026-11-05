import { useRef, useState } from "react";
import { api } from "../../api/client";
import type { CompareRow } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { Feedback } from "../../ui/Feedback";
import { CheckField } from "../../ui/FieldRow";
import { PageBody } from "../../ui/PageLayout";
import { settingsSaved } from "../settings/settingsChanges";
import type { CompareContext } from "./Compare";
import { CompareGrid, type CompareColumn } from "./CompareGrid";
import { blindOrder, modelDetail, picks, working } from "./compareView";
import { LinesMenu, useSceneChoice } from "./LinesMenu";
import { ModelChips, sent, type ChosenModel } from "./ModelChoice";
import { useCompareRun } from "./useCompareRun";

type Marks = {
  marks: Record<string, number>;
  blind: boolean;
  revealed: boolean;
};

/**
 * Model vs model: two to four models translate the same lines side by side,
 * and a click on a translation picks the best of each line. Blind, the
 * models' names stay hidden, in an order of their own, until every line has
 * a pick or the user reveals them.
 */
export function Versus({ context }: { context: CompareContext }) {
  const application = useApplication();
  const [models, setModels] = useState<ChosenModel[] | null>(null);
  // The model Settings uses starts the list, once it is known.
  if (models === null && context.base) setModels([context.base]);
  const chosen = models ?? [];
  const scene = useSceneChoice(context.state.scenes);
  const [blind, setBlind] = useState(true);
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
  const run = useCompareRun(
    context,
    {
      kind: "versus",
      file: scene.file,
      lines: scene.lines,
      candidates: chosen.map(sent),
    },
    {
      blocked: !scene.file
        ? "This game has no lines to compare yet."
        : chosen.length < 2
          ? "Add another model to compare."
          : "",
      namesHidden: blind,
      started: async (job) => {
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
  // Picks start once every model's lines are in.
  const translated = !!translationId && !!shown && !working(shown.status);
  const mark: Marks | null =
    translated && translationId
      ? (saved[translationId] ?? {
          marks: shown.marks,
          blind: shown.blind,
          revealed: shown.revealed,
        })
      : null;
  const score = shown && mark ? picks(shown, mark.marks) : null;
  const finished = !!score && score.total > 0 && score.picked === score.total;
  const hidden = !!mark && mark.blind && !mark.revealed && !finished;
  const order =
    shown && mark?.blind
      ? blindOrder(shown.id, shown.candidates.length)
      : (shown?.candidates ?? chosen).map((_, index) => index);
  const winner =
    score && !hidden && score.winner !== null && shown
      ? shown.candidates[score.winner]
      : null;
  const columns: CompareColumn[] = order.map((position, place) => {
    const model = shown?.candidates[position];
    if (!model)
      return { position, title: chosen[position]?.model ?? "" } as const;
    return {
      position,
      title: hidden ? `Model ${place + 1}` : model.model,
      badge: winner === model && (
        <span className="compare-most">Most picked</span>
      ),
      detail: hidden
        ? undefined
        : [
            translated &&
              !model.error &&
              score &&
              score.picked > 0 &&
              `won ${score.won[position]}`,
            modelDetail(model, translated),
          ]
            .filter(Boolean)
            .join(" · "),
      error: model.error,
    };
  });
  const pick = (row: CompareRow, model: number | null) => {
    if (!translationId || !mark) return;
    const latest = newest.current[translationId] ?? mark;
    const next = { ...latest.marks };
    if (model === null) delete next[row.id];
    else next[row.id] = model;
    save(translationId, { ...latest, marks: next });
  };
  const tied =
    score && !hidden && score.tied.length && shown
      ? score.tied.map((position) => shown.candidates[position].model)
      : [];
  const progress = !score
    ? ""
    : finished
      ? `Every line picked${mark?.blind ? " · names revealed" : ""}`
      : `Click the best translation of each line · ${score.picked} of ${score.total} picked`;
  return (
    <>
      <PageBody className="compare-body">
        <div className="compare-setup">
          <div className="compare-setup-row">
            <ModelChips
              models={chosen}
              change={setModels}
              disabled={run.action.busy}
            />
            <LinesMenu
              scenes={context.state.scenes}
              file={scene.file}
              lines={scene.lines}
              change={scene.change}
              disabled={run.action.busy}
            />
          </div>
          <CheckField
            id="compare-blind"
            label="Blind: hide names until every line is picked"
            checked={mark ? mark.blind : blind}
            onChange={(checked) => {
              setBlind(checked);
              if (mark && translationId)
                save(translationId, {
                  ...mark,
                  blind: checked,
                  revealed: checked ? false : mark.revealed,
                });
            }}
          />
        </div>
        <CompareGrid
          label="Translations by model"
          comparison={shown}
          columns={columns}
          marks={mark?.marks}
          pick={translated ? pick : undefined}
          empty={run.empty(
            "Estimate the cost to see these lines side by side.",
          )}
        />
      </PageBody>
      <ActionBar
        feedback={
          marksAction.error ? (
            <Feedback error={marksAction.error} />
          ) : (
            <div className="feedback" role="status">
              {progress}
              {tied.length > 0 && ` · ${tied.join(" and ")} tied`}
            </div>
          )
        }
      >
        {hidden && (
          <Button
            onClick={() =>
              translationId &&
              mark &&
              save(translationId, { ...mark, revealed: true })
            }
          >
            Reveal now
          </Button>
        )}
        {run.control(!!winner)}
        {winner && shown && (
          <ActionControl
            variant={run.yields ? "primary" : undefined}
            label={`Use ${winner.model}`}
            title="Make it the connection and model Settings translates with, for every game."
            pending={adopt.busy}
            pendingText="Switching model…"
            error={adopt.error}
            notice={adopt.notice}
            onClick={() =>
              void adopt.run(async () => {
                await api.compare.use(
                  context.projectId,
                  shown.id,
                  winner.index,
                );
                settingsSaved();
              }, `Settings now translates with ${winner.model}.`)
            }
          />
        )}
      </ActionBar>
    </>
  );
}
