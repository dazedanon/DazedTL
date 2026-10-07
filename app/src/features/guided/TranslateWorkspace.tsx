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
  activeRun,
  filePreviewRun,
  fileRun,
  fileLines,
  fileMetricRun,
  fileStatus,
  groupedRequests,
  settledWithoutRequests,
} from "./translationView";
import type { RequestInspectionTarget } from "./ProcessPanel";
import { retainOtherScope } from "./selection";
import { StatusMark } from "../../ui/StatusMark";
import { SegmentedControl } from "../../ui/SegmentedControl";
import { ModelMenu } from "../settings/ModelMenu";

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
  const changedFiles = new Set(state.sourceStatus.changed);
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
        <SegmentedControl
          label="Translation method"
          value={values.mode === "batch" ? "batch" : "translate"}
          disabled={disabled || locked}
          onChange={(mode) => change("mode", mode)}
          options={[
            {
              value: "batch",
              label: "Batch",
              disabled: !state.provider.batchSupported,
              title: state.provider.batchSupported
                ? "Review Batch pricing before submitting"
                : state.provider.batchReason ||
                  "Unavailable for this connection",
            },
            { value: "translate", label: "Live" },
          ]}
        />
        <small className="translation-method-hint">
          {state.provider.batchSupported
            ? "Batch recommended · often 50% cheaper"
            : `Live · saves results as they arrive. ${state.provider.batchReason || "This connection does not support Batch."}`}
        </small>
        {/* The model follows the method controls, so the note that a model
            was saved grows into free space instead of moving them. */}
        <span className="translation-model">
          <span className="muted">Model</span>
          <ModelMenu
            model={state.provider.model}
            connection={state.provider.connection}
            disabled={locked}
            manage={settings}
          />
        </span>
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
          // A Live run records cost and time as files finish, so its
          // columns appear when it starts rather than shifting mid-run.
          data-metrics={
            (activeRun(run) && run?.mode !== "batch") ||
            rows.some(
              (row) =>
                fileMetricRun(
                  state.runs,
                  phase,
                  row.name,
                  state.sourceStatus.retired,
                )?.process?.fileMetrics?.[row.name],
            )
          }
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
                  <span
                    className="translation-file-lines"
                    title="Lines saved of the lines the latest run prepared"
                  >
                    Lines
                  </span>
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
                const lines = fileLines(state, phase, row.name);
                return (
                  <>
                    <span
                      className="translation-file-lines"
                      title={
                        lines.running
                          ? "Lines saved so far; the total is known when the run ends"
                          : lines.total
                            ? "Lines saved of the lines the latest run prepared"
                            : lines.done
                              ? "Lines saved before the latest run ended; it did not reach the rest of the file"
                              : "Line counts appear once a run prepares this file"
                      }
                    >
                      {lines.running || (!lines.total && lines.done)
                        ? `${lines.done.toLocaleString()} so far`
                        : lines.total
                          ? `${lines.done.toLocaleString()} / ${lines.total.toLocaleString()}`
                          : "-"}
                    </span>
                    {/* A file changed in the game needs reloading before
                        new work, whatever its last run left. */}
                    <span
                      className="translation-file-status"
                      title={
                        changedFiles.has(row.name) && !status.pending
                          ? "Changed in the game since its working copy was made."
                          : status.detail || undefined
                      }
                    >
                      <StatusMark
                        state={
                          changedFiles.has(row.name) && !status.pending
                            ? "outdated"
                            : status.state
                        }
                        size={14}
                      />
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
