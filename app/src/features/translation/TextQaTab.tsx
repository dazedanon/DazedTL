/**
 * Assistant-led text QA: the starting prompt runs it, and this tab shows
 * where it stands, the questions only the user can answer and what it
 * corrected, with Undo.
 */

import { useState, type ReactNode } from "react";
import type { QaState } from "../../api/contracts";
import { api } from "../../api/client";
import type { useAction } from "../../state/useAction";
import type { OperationEnd } from "../guided/qaSteps";
import {
  runQaStep,
  saveQaVersion,
  type QaStepDetails,
  type QaStepName,
} from "../guided/qaSteps";
import { QaCoverage, TextQaWork } from "../guided/TextQa";
import { qaPhase, qaUnsaved } from "../guided/qaView";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { PageBody } from "../../ui/PageLayout";

export function TextQaTab({
  projectId,
  qa,
  action,
  disabled,
  finished,
  copy,
}: {
  projectId: string;
  qa: QaState;
  action: ReturnType<typeof useAction>;
  disabled: boolean;
  finished: OperationEnd;
  /** The page's starting prompt, which runs QA. */
  copy: ReactNode;
}) {
  const [coverage, setCoverage] = useState(false);
  const phase = qaPhase(qa);
  const feedback = (key: string, pendingText = "Working…") => ({
    feedbackKey: key,
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  const step = (
    key: string,
    name: QaStepName,
    details: QaStepDetails = {},
    success = "",
  ) =>
    action.run(
      () => runQaStep(projectId, name, details, finished),
      success,
      key,
    );
  const unsaved = qaUnsaved(qa, action);
  return (
    <>
      <PageBody>
        <TextQaWork
          qa={qa}
          // The starting prompt hands QA to the assistant.
          waiting
          disabled={disabled}
          feedback={feedback}
          applyFailed=""
          run={step}
          onCoverage={() => setCoverage(true)}
          rerun="Copy the prompt to resume, and your assistant runs QA again."
        />
      </PageBody>
      <ActionBar feedback={null}>
        {unsaved ? (
          <ActionControl
            label="Save version"
            variant="default"
            disabled={disabled || (action.key === "qa-save" && !!action.notice)}
            {...(action.key === "qa-save"
              ? feedback("qa-save", "Saving…")
              : { feedbackKey: action.key, error: action.error })}
            onClick={() =>
              action.run(
                () => saveQaVersion(projectId, finished),
                "Version saved.",
                "qa-save",
              )
            }
          />
        ) : (
          phase === "ready" && (
            <ActionControl
              label="Apply corrections"
              disabled={disabled}
              {...feedback("qa-apply", "Applying…")}
              onClick={() =>
                step("qa-apply", "apply", {}, "Corrections applied.")
              }
            />
          )
        )}
        {copy}
      </ActionBar>
      {coverage && (
        <QaCoverage
          load={() => api.guided.qaReport(projectId)}
          markReviewed={(identities) =>
            api.guided.qaReviewed(projectId, identities)
          }
          onClose={() => setCoverage(false)}
        />
      )}
    </>
  );
}
