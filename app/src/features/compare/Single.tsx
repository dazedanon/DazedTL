import { useState } from "react";
import { api } from "../../api/client";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { PageBody, PageMessages } from "../../ui/PageLayout";
import { settingsSaved } from "../settings/settingsChanges";
import type { CompareContext } from "./Compare";
import { CompareGrid } from "./CompareGrid";
import { CompareRequest } from "./CompareRequest";
import { modelDetail } from "./compareView";
import { LinesMenu, useSceneChoice } from "./LinesMenu";
import { ModelLink, sent, type ChosenModel } from "./ModelChoice";
import { useCompareRun } from "./useCompareRun";
import { useLanguages } from "../../app/LanguagesProvider";

/** Single model: one model's translation of the lines, beside the source. */
export function Single({ context }: { context: CompareContext }) {
  const application = useApplication();
  const languages = useLanguages();
  const [model, setModel] = useState<ChosenModel | null>(null);
  if (model === null && context.base) setModel(context.base);
  const scene = useSceneChoice(context.state.scenes);
  const run = useCompareRun(
    context,
    {
      kind: "single",
      file: scene.file,
      lines: scene.lines,
      candidates: model ? [sent(model)] : [],
    },
    {
      blocked: !scene.file
        ? "This game has no lines to compare yet."
        : !model
          ? "Choose a model first."
          : "",
    },
  );
  const { shown } = run;
  const result = shown?.candidates[0];
  const translated = !!result?.finished;
  const adopt = useAction({ observer: application });
  const [inspecting, setInspecting] = useState(false);
  return (
    <>
      <PageMessages>{run.notice}</PageMessages>
      <PageBody className="compare-body">
        <div className="compare-setup">
          <div className="compare-setup-row">
            <ModelLink
              model={model ?? undefined}
              change={setModel}
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
        </div>
        <CompareGrid
          label="Translation"
          comparison={shown}
          columns={[
            {
              position: 0,
              title: languages.target,
              detail: result && modelDetail(result, !!shown?.translationId),
              error: result?.error,
            },
          ]}
          empty={run.empty("Estimate the cost to see these lines translated.")}
        />
      </PageBody>
      <ActionBar
        feedback={
          !!shown?.translationId &&
          !!result?.keptRequests && (
            <Button variant="quiet" onClick={() => setInspecting(true)}>
              Show request
            </Button>
          )
        }
      >
        {translated && (
          <ActionControl
            label="Use this model"
            title="Make it the connection and model Settings translates with, for every game."
            disabled={!!run.waiting}
            disabledReason={run.waiting}
            pending={adopt.busy}
            pendingText="Switching model…"
            error={adopt.error}
            notice={adopt.notice}
            onClick={() =>
              void adopt.run(async () => {
                await api.compare.use(
                  context.projectId,
                  shown.id,
                  result.index,
                );
                settingsSaved();
              }, `Settings now translates with ${result?.model}.`)
            }
          />
        )}
        {run.control()}
      </ActionBar>
      {inspecting && shown?.translationId && result && (
        <CompareRequest
          projectId={context.projectId}
          translationId={shown.translationId}
          model={result}
          close={() => setInspecting(false)}
        />
      )}
    </>
  );
}
