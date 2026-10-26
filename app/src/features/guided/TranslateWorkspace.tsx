import { useMemo, type ReactNode } from "react";
import type {
  GuidedOptions,
  GuidedState,
  Job,
  Phase,
} from "../../api/contracts";
import { useLanguages } from "../../app/LanguagesProvider";
import { Button } from "../../ui/Button";
import { FileSelection } from "./FileSelection";
import {
  activeRun,
  countedPhase,
  filePreviewRun,
  fileLines,
  fileWork,
  translationFileStatus,
} from "./translationView";
import type { RequestInspectionTarget } from "./ProcessPanel";
import { retainOtherScope } from "./selection";
import { StatusMark } from "../../ui/StatusMark";
import { SegmentedControl } from "../../ui/SegmentedControl";
import { ModelMenu } from "../settings/ModelMenu";
import type { SettingsSection } from "../settings/Settings";

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
  settings: (section?: SettingsSection) => void;
  options: () => void;
  history: () => void;
  inspect: (job: Job | null, target: RequestInspectionTarget) => void;
  inspectedFile?: string;
  fileActions?: ReactNode;
  children?: ReactNode;
}) {
  const languages = useLanguages();
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
  // The runs each row shows, read once per row.
  const works = useMemo(
    () =>
      new Map(
        rows.map((row) => [
          row.name,
          fileWork(state.runs, phase, row.name, state.sourceStatus.retired),
        ]),
      ),
    [rows, state.runs, phase, state.sourceStatus.retired],
  );
  const counted = countedPhase(phase);
  const openFile = (name: string) => {
    const job = filePreviewRun(
      name,
      run,
      estimate,
      works.get(name)?.owner,
      currentEstimate,
    );
    const lines = counted ? state.sourceStatus.lines?.[name] : undefined;
    inspect(job || null, {
      file: name,
      index: job?.process?.files?.[name]?.first,
      left: lines && lines.lines - lines.translated,
    });
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
            manage={() => settings("api")}
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
                works.get(row.name)?.changed?.process?.fileMetrics?.[row.name],
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
                    title={
                      counted
                        ? `Lines translated of the lines in each file that hold ${languages.source}`
                        : "Lines saved of the lines the latest run prepared"
                    }
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
                const work = works.get(row.name)!;
                const status = translationFileStatus(
                  state,
                  phase,
                  row.name,
                  work.run,
                  languages.source,
                );
                const metricRun = work.changed,
                  metrics = metricRun?.process?.fileMetrics?.[row.name];
                const lines = fileLines(state, phase, row.name, work);
                return (
                  <>
                    <span
                      className="translation-file-lines"
                      title={
                        lines.running
                          ? counted
                            ? "Lines saved so far; the file's count returns once the run is done with it"
                            : "Lines saved so far; the total is known when the run ends"
                          : lines.total
                            ? counted
                              ? `Lines translated of the lines in this file that hold ${languages.source}`
                              : "Lines saved of the lines the latest run prepared"
                            : lines.counting
                              ? "DazedTL is counting this file's lines"
                              : lines.done
                                ? "Lines saved before the latest run ended; it did not reach the rest of the file"
                                : lines.total === 0
                                  ? "Nothing to translate in this file"
                                  : counted
                                    ? "This file could not be read as game data"
                                    : "Line counts appear once a run prepares this file"
                      }
                    >
                      {lines.running || (!lines.total && lines.done)
                        ? `${lines.done.toLocaleString()} so far`
                        : lines.total
                          ? `${lines.done.toLocaleString()} / ${lines.total.toLocaleString()}`
                          : lines.counting
                            ? "Counting…"
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
