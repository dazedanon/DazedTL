import { useMemo, type ReactNode } from "react";
import type {
  GuidedOptions,
  GuidedState,
  Job,
  Phase,
} from "../../api/contracts";
import { Button } from "../../ui/Button";
import { FileSelection } from "./FileSelection";
import {
  filePreviewRun,
  fileRun,
  fileMetricRun,
  fileStatus,
  groupedRequests,
  settledWithoutRequests,
} from "./translationView";
import type { RequestInspectionTarget } from "./ProcessPanel";
import { retainOtherScope } from "./selection";
import { StatusIcon } from "../../ui/StatusIcon";

export function TranslateWorkspace({
  state,
  phase,
  values,
  run,
  estimate,
  currentEstimate,
  disabled,
  locked,
  change,
  settings,
  options,
  history,
  inspect,
  inspectedFile,
  fileActions,
  children,
}: {
  state: GuidedState;
  phase: Phase;
  values: GuidedOptions;
  run?: Job;
  estimate?: Job | null;
  currentEstimate: boolean;
  disabled: boolean;
  locked: boolean;
  change: <K extends keyof GuidedOptions>(
    key: K,
    value: GuidedOptions[K],
  ) => void;
  settings: () => void;
  options: () => void;
  history: () => void;
  inspect: (job: Job | null, target: RequestInspectionTarget) => void;
  inspectedFile?: string;
  fileActions?: ReactNode;
  children?: ReactNode;
}) {
  const rows = useMemo(
    () =>
      state.files.filter(
        (row) => row.group === (phase === "database" ? "database" : "dialogue"),
      ),
    [state.files, phase],
  );
  const selected = new Set(values.selected);
  const scoped = rows.filter((row) => selected.has(row.name));
  const owner = (name: string) =>
    fileRun(state.runs, phase, name, state.sourceStatus.retired);
  const openFile = (name: string) => {
    const job = filePreviewRun(
      name,
      run,
      estimate,
      owner(name),
      currentEstimate,
    );
    const request = groupedRequests(job?.process?.requests || []).find(
      (row) => row.file === name,
    );
    inspect(job || null, { file: name, index: request?.index });
  };
  return (
    <div className="translation-workspace">
      <div className="translation-toolbar" aria-label="Translation setup">
        <span className="translation-model">
          <span className="muted">Model</span>
          <Button
            variant="link"
            disabled={locked}
            onClick={settings}
            title={`${state.provider.connection} · change in Settings`}
          >
            {state.provider.model || "Choose a model"}
          </Button>
        </span>
        <div
          className="guided-mode"
          role="group"
          aria-label="Translation method"
        >
          <Button
            disabled={disabled || locked || !state.provider.batchSupported}
            title={
              state.provider.batchSupported
                ? "Review Batch pricing before submitting"
                : state.provider.batchReason ||
                  "Unavailable for this connection"
            }
            aria-pressed={values.mode === "batch"}
            onClick={() => change("mode", "batch")}
          >
            Batch
          </Button>
          <Button
            disabled={disabled || locked}
            aria-pressed={values.mode === "translate"}
            onClick={() => change("mode", "translate")}
          >
            Live
          </Button>
        </div>
        <small className="translation-method-hint">
          {state.provider.batchSupported
            ? "Batch recommended · often 50% cheaper"
            : `Live · saves results as they arrive. ${state.provider.batchReason || "This connection does not support Batch."}`}
        </small>
        <div className="translation-tools">
          <Button variant="quiet" onClick={history}>
            Run history
          </Button>
          <Button variant="quiet" onClick={options}>
            Options
          </Button>
        </div>
      </div>
      <div className="translation-notices">{children}</div>
      <div className="translation-columns">
        <section
          className="translation-files"
          aria-label="Translation files"
          data-metrics={rows.some(
            (row) =>
              fileMetricRun(
                state.runs,
                phase,
                row.name,
                state.sourceStatus.retired,
              )?.process?.fileMetrics?.[row.name],
          )}
        >
          <FileSelection
            state={{ ...state, files: rows }}
            selected={scoped.map((row) => row.name)}
            disabled={disabled || locked}
            actions={fileActions}
            change={(names) =>
              change("selected", retainOtherScope(values.selected, rows, names))
            }
            inline={{
              preview: openFile,
              previewed: inspectedFile,
              columns: (
                <>
                  <span>Status</span>
                  <span className="translation-file-cost">Cost</span>
                  <span
                    className="translation-file-time"
                    title="Engine processing time; excludes Batch provider waiting"
                  >
                    Time
                  </span>
                  <span />
                </>
              ),
              details: (row) => {
                const fileOwner = owner(row.name),
                  status = fileStatus(
                    row.name,
                    fileOwner,
                    settledWithoutRequests(state, phase, row.name, fileOwner),
                  );
                const metricRun = fileMetricRun(
                    state.runs,
                    phase,
                    row.name,
                    state.sourceStatus.retired,
                  ),
                  metrics = metricRun?.process?.fileMetrics?.[row.name];
                return (
                  <>
                    <span className={`translation-file-status ${status.tone}`}>
                      <StatusIcon
                        status={status.pending ? "active" : status.icon}
                        size={14}
                      />
                      <span className="translation-status-text">
                        {status.label}
                      </span>
                    </span>
                    <span
                      className="translation-file-cost"
                      title={
                        metrics
                          ? "Engine-reported cost from the last run that changed this file"
                          : "Cost not recorded"
                      }
                    >
                      {metrics ? `$${metrics.cost.toFixed(4)}` : "-"}
                    </span>
                    <span
                      className="translation-file-time"
                      title={
                        metrics
                          ? `${metrics.seconds.toFixed(1)} seconds of engine processing${metricRun?.mode === "batch" ? "; excludes provider waiting" : ""}`
                          : "Time not recorded"
                      }
                    >
                      {metrics ? `${metrics.seconds.toFixed(1)}s` : "-"}
                    </span>
                  </>
                );
              },
            }}
          />
        </section>
      </div>
    </div>
  );
}
