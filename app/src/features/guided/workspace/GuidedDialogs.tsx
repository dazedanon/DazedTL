import { api } from "../../../api/client";
import { ActionBar } from "../../../ui/ActionBar";
import { ActionList, ActionRow } from "../../../ui/ActionList";
import { Button } from "../../../ui/Button";
import { Message } from "../../../ui/Feedback";
import { DialogBody, DialogHeader } from "../../../ui/Dialog";
import { Modal } from "../../../ui/Modal";
import { EventTextPicker } from "../EventTextPicker";
import { EventTextReview } from "../EventTextReview";
import { RunHistorySheet } from "../RunHistorySheet";
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
    application,
    action,
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
    inspect,
    reapplyRun,
    openProject,
    runHistory,
    setRunHistory,
    translation,
  } = w;

  return (
    <>
      {runHistory && (
        <RunHistorySheet
          state={state}
          translation={translation}
          phase={runHistory}
          inspect={(job) => inspect(job)}
          close={() => setRunHistory(null)}
        />
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
          history={
            runHistory || !inspected?.logicalPhase
              ? undefined
              : () => {
                  setInspected(null);
                  setInspectionTarget(undefined);
                  setRunHistory(inspected.logicalPhase!);
                }
          }
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
          // The review replaces the inspector rather than stacking on it.
          reapply={async (item) => {
            await reapplyRun(item.id);
            setInspected(null);
            setInspectionTarget(undefined);
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
          size="md"
          className="guided-sheet"
          dismissible={!action.busy}
          onDismiss={() => setComparisonReview(false)}
        >
          <DialogHeader title="Review matching comparisons" />
          <DialogBody>
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
          </DialogBody>
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
          else openProject("history");
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
          later={() => setSubmission(null)}
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
          size="sm"
          dismissible={!action.busy}
          onDismiss={() => setResume(null)}
        >
          <DialogHeader
            title="Resume the saved run?"
            description={`${resume.model} · ${fileCount(resume.files?.length || 0)} · saved run settings`}
          />
          <DialogBody>
            <p>
              Continue its frozen files, context, and provider settings.
              Remaining requests may incur charges.
            </p>
          </DialogBody>
          <ActionBar
            feedback={
              <Message
                message={action.key === "run:resume" ? action.error : ""}
              />
            }
          >
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
          </ActionBar>
        </Modal>
      )}
    </>
  );
}
