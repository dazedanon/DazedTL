import { api } from "../../../api/client";
import { ActionBar } from "../../../ui/ActionBar";
import { ActionList, ActionRow } from "../../../ui/ActionList";
import { Button } from "../../../ui/Button";
import { Message } from "../../../ui/Feedback";
import { Modal } from "../../../ui/Modal";
import { ActivityHistory } from "../ActivityHistory";
import { EventTextPicker } from "../EventTextPicker";
import { EventTextReview } from "../EventTextReview";
import { RunInspector } from "../RunInspector";
import { TranslationFlowDialog } from "../TranslationFlowDialog";
import { TranslationReview } from "../TranslationReview";
import { canResumeRun } from "../translationView";
import { actionKey, fileCount } from "./model";
import type { GuidedWorkspace } from "./useGuidedWorkspace";

/** History, inspection, source and comparison reviews, approvals and resume. */
export function GuidedDialogs({ w }: { w: GuidedWorkspace }) {
  const {
    project,
    state,
    translation,
    application,
    action,
    setPreview,
    setPreviewRequest,
    setInspectRelease,
    submission,
    setSubmission,
    resume,
    setResume,
    sourceReview,
    setSourceReview,
    comparisonReview,
    setComparisonReview,
    comparisonsAccepted,
    setComparisonsAccepted,
    history,
    setHistory,
    setInspected,
    inspectionTarget,
    setInspectionTarget,
    inspected,
    started,
    inspectorReturnFocus,
    baseline,
    save,
    translationFlow,
    disabled,
    saveSourcePicker,
    preparePreview,
    inspect,
  } = w;

  return (
    <>
      {history && (
        <Modal
          label="Run history"
          className="history-sheet"
          onDismiss={() => setHistory(null)}
        >
          <div className="request-inspector-heading">
            <h2>Run history</h2>
            <Button onClick={() => setHistory(null)}>Close</Button>
          </div>
          <ActivityHistory
            state={state}
            translation={translation}
            inspect={inspect}
            initialFilter={history}
          />
        </Modal>
      )}
      {(inspected || inspectionTarget?.file) && (
        <RunInspector
          key={`${project.id}:${inspected?.id || ""}:${inspectionTarget?.file || ""}`}
          projectId={project.id}
          job={inspected}
          target={inspectionTarget}
          returnFocus={inspectorReturnFocus}
          close={() => {
            setInspected(null);
            setInspectionTarget(undefined);
          }}
          history={() => {
            setInspected(null);
            setInspectionTarget(undefined);
            setHistory(history || "all");
          }}
          disabled={disabled || !baseline}
          applied={(() => {
            const startedJob =
              inspected &&
              started[actionKey("export_selected", { run_id: inspected.id })];
            return (
              state.operations.find((job) => job.id === startedJob?.id) ||
              startedJob ||
              undefined
            );
          })()}
          reapply={async (item) => {
            const options = { run_id: item.id };
            const result = await preparePreview("export_selected", options);
            setPreviewRequest({ name: "export_selected", options });
            setInspectRelease(false);
            setPreview(result);
          }}
          actions={
            inspected &&
            canResumeRun(inspected) && (
              <ActionList compact>
                <ActionRow
                  label={
                    <small>Continue Live with this run’s saved settings.</small>
                  }
                >
                  <Button
                    disabled={action.busy}
                    onClick={() => setResume(inspected)}
                  >
                    Review resume
                  </Button>
                </ActionRow>
              </ActionList>
            )
          }
        />
      )}
      {state.eventText.picker && (
        <EventTextPicker
          key={state.eventText.picker.key}
          projectId={project.id}
          state={state.eventText}
          initial={state.eventText.picker}
          save={saveSourcePicker}
          refresh={application.refresh}
        />
      )}
      {sourceReview && (
        <EventTextReview
          review={sourceReview}
          busy={action.busy}
          error={action.error}
          cancel={() => setSourceReview(null)}
          accept={(reason, accepted) =>
            action.run(
              async () => {
                await api.guided.eventTextReview(
                  project.id,
                  sourceReview.revision,
                  sourceReview.state.binding,
                  sourceReview.state.reportId,
                  reason,
                  accepted,
                );
                setSourceReview(null);
                application.navigateGuided(project.id, {
                  eventView: "advanced-run",
                });
              },
              "Source choices reviewed. Estimate this scope before paid review.",
              "event-text:confirm",
            )
          }
        />
      )}
      {comparisonReview && (
        <Modal
          label="Review comparison coverage"
          className="guided-sheet"
          dismissible={!action.busy}
          onDismiss={() => setComparisonReview(false)}
        >
          <header className="guided-sheet-heading">
            <h2>Review matching comparisons</h2>
          </header>
          <div className="guided-sheet-body">
            <p>
              Mappings are keyed by literal text, not variable ID. The engine
              updates every matching quoted literal in these selected code-111
              expressions. A saved mapping does not prove a logic string is safe
              to translate.
            </p>
            <p>
              {state.comparisons.matches} matched ·{" "}
              {state.comparisons.unmatched} unmatched literals will remain
              unchanged.
            </p>
            {state.comparisons.rows.map((row, index) => (
              <section className="event-text-source" key={index}>
                <strong>
                  {row.file} · {row.location}
                </strong>
                <p>
                  Variable IDs:{" "}
                  {row.variables.join(", ") ||
                    "Dynamic or unresolved - inspect the full expression"}
                </p>
                <p>
                  {row.literal} → {row.translation}
                </p>
              </section>
            ))}
            <label className="toggle">
              <input
                type="checkbox"
                checked={comparisonsAccepted}
                onChange={(event) =>
                  setComparisonsAccepted(event.target.checked)
                }
              />
              I checked every matched use, including internal references and
              logic, and accept these literal-based updates.
            </label>
          </div>
          <ActionBar feedback={<Message message={action.error} />}>
            <Button
              disabled={action.busy}
              onClick={() => setComparisonReview(false)}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!comparisonsAccepted || !state.comparisons.matches}
              pending={action.busy}
              onClick={() =>
                action.run(
                  async () => {
                    await save();
                    await api.guided.comparisonsReview(
                      project.id,
                      state.comparisons.fingerprint,
                      true,
                    );
                    setComparisonReview(false);
                  },
                  "Comparison coverage reviewed.",
                  "event-text:comparisons",
                )
              }
            >
              Confirm comparison coverage
            </Button>
          </ActionBar>
        </Modal>
      )}
      <TranslationFlowDialog
        projectId={project.id}
        flow={translationFlow}
        executionEnabled={state.provider.enabled}
        approvalCurrent={
          !translationFlow.state?.job?.approval ||
          state.runs.some(
            (run) =>
              run.approval?.token ===
              translationFlow.state?.job?.approval?.token,
          )
        }
        inspect={(id) => {
          translationFlow.dismiss();
          const run = state.runs.find((item) => item.id === id);
          if (run) inspect(run);
          else setHistory("all");
        }}
      />
      {submission?.approval && (
        <TranslationReview
          projectId={project.id}
          job={submission}
          busy={action.busy}
          pendingKey={action.key}
          disabled={disabled}
          executionEnabled={state.provider.enabled}
          approvalCurrent={state.runs.some(
            (run) => run.approval?.token === submission.approval!.token,
          )}
          error={action.key.startsWith("run:answer:") ? action.error : ""}
          close={() => setSubmission(null)}
          answer={(approved) =>
            action.run(
              async () => {
                await api.answer(
                  project.id,
                  submission.approval!.token,
                  approved,
                );
                setSubmission(null);
              },
              approved ? "" : "Submission declined.",
              "run:answer:" + approved,
            )
          }
        />
      )}
      {resume && (
        <Modal
          label="Resume saved run"
          dismissible={!action.busy}
          onDismiss={() => setResume(null)}
        >
          <h2>Resume the saved run?</h2>
          <p>
            {resume.model} · {fileCount(resume.files?.length || 0)} · saved run
            settings
          </p>
          <p>
            Continue its frozen files, context, and provider settings. Remaining
            requests may incur charges.
          </p>
          <Message message={action.key === "run:resume" ? action.error : ""} />
          <div className="actions">
            <Button disabled={action.busy} onClick={() => setResume(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              pending={action.busy}
              onClick={() =>
                action.run(
                  async () => {
                    await api.resume(project.id, resume.id);
                    setResume(null);
                  },
                  "",
                  "run:resume",
                )
              }
            >
              Resume saved run
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
