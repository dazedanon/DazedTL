/** Check: text QA, which for MV/MZ is also the final check with the playtest. */
import type { ReactNode } from "react";
import { FieldRow } from "../../../../ui/FieldRow";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import { Notice } from "../../../../ui/Notice";
import { api } from "../../../../api/client";
import { jobTime } from "../model";
import { ActionControl } from "../../../../ui/ActionControl";
import { TextQaWork } from "../../TextQa";
import {
  runQaStep,
  saveQaVersion,
  type QaStepDetails,
  type QaStepName,
} from "../../qaSteps";
import { qaPhase, qaUnsaved } from "../../qaView";
import { PlaytestWork } from "../../Playtest";
import { playtestFailure, playtestWaiting } from "../../playtestView";

export function qaView(w: GuidedWorkspace): TaskView {
  const {
    state,
    project,
    baseline,
    qa,
    action,
    disabled,
    feedback,
    editText,
    copyTask,
    advance,
    fields,
    handoff,
    operationJob,
    whenFinished,
    save,
  } = w;
  const phase = qaPhase(qa);
  // The copied task's assistant is still at work, and runs QA again itself.
  const assisted = handoff("qa").waiting;
  // For MV/MZ the assistant also plays the game in this task.
  const playtest = state.engine === "MVMZ" ? state.readiness.playtest : null;
  // Problems the playtest found in translated text after QA finished, which
  // QA reviews when it runs again.
  const found = playtest ? playtestWaiting(playtest) : 0;
  const again = found > 0 && ["applied", "clean"].includes(phase);
  // The latest play: a playtest, or one with the assistant's fixes in place.
  const playing = [
    operationJob("release_playtest"),
    operationJob("playtest_fix"),
  ]
    .filter((job) => !!job)
    .sort((a, b) => jobTime(a) - jobTime(b))
    .at(-1);
  // An apply that failed and rolled back says so beside its retry; one from
  // before this task was prepared belongs to an earlier task.
  const applying = operationJob("qa_apply");
  const preparing = operationJob("qa_prepare");
  const applyFailed =
    phase === "ready" &&
    applying &&
    ["failed", "interrupted"].includes(applying.status) &&
    jobTime(applying) >= jobTime(preparing || {})
      ? applying.message || "The apply did not finish."
      : "";
  /** Runs one QA step; preparing goes on to copy the task. */
  const step = (
    key: string,
    name: QaStepName,
    details: QaStepDetails = {},
    success = "",
  ) =>
    action.run(
      async () => {
        await save();
        await runQaStep(project.id, name, details, whenFinished);
        if (name === "prepare")
          await window.dazedtl.copyText(
            (await api.guided.skill(project.id, "qa")).text,
          );
      },
      success,
      key,
    );
  const unsaved = qaUnsaved(qa, action);
  // "Paste it into your coding assistant" stops describing a next step once
  // the QA it handed over finishes, goes out of date or can't be read; a copy
  // of QA that had already finished keeps it as that click's acknowledgment.
  const copiedFinished =
    preparing?.status === "complete" &&
    preparing.result?.task === qa.task &&
    (preparing.result?.status as { stage?: string } | undefined)?.stage ===
      "complete";
  const staleCopy =
    ["outdated", "blocked"].includes(phase) ||
    (["applied", "clean"].includes(phase) && !copiedFinished);
  const start = (label: string, variant: "primary" | "default" = "primary") => (
    <ActionControl
      label={label}
      variant={variant}
      disabled={disabled || !baseline}
      disabledReason={baseline ? "" : "Set up the game first."}
      // The copy control that replaces this one once QA runs keeps its
      // outcome.
      {...feedback("copy:qa", "Preparing QA…")}
      {...(staleCopy && { notice: "" })}
      onClick={() =>
        step(
          "copy:qa",
          "prepare",
          {},
          "QA task copied. Paste it into your coding assistant.",
        )
      }
    />
  );
  const content: ReactNode = (
    <>
      {again && (
        <Notice>
          The playtest found {found.toLocaleString()}{" "}
          {found === 1 ? "problem" : "problems"} in translated text;{" "}
          {assisted ? "your assistant runs QA again for " : "QA reviews "}
          {found === 1 ? "it" : "them"}
          {assisted ? "." : " when it runs again."}
        </Notice>
      )}
      <TextQaWork
        qa={qa}
        waiting={assisted}
        disabled={disabled}
        feedback={feedback}
        applyFailed={applyFailed}
        run={step}
        restorable
        // The playtest's panel follows QA's, before its corrections.
        beside={
          playtest && (
            <PlaytestWork
              projectId={project.id}
              playtest={playtest}
              running={playing?.status === "running"}
              progress={
                playing?.status === "running" ? playing.message : undefined
              }
              // A refused fix is the assistant's to revise, not a failed play.
              failed={playtestFailure(
                playtest,
                operationJob("release_playtest"),
              )}
              idle="Your assistant plays the game while QA reviews it, and fixes what it finds."
              rerun="Your assistant plays it again before it finishes."
              compact
              stop={
                <ActionControl
                  label="Stop playtest"
                  variant="link"
                  disabled={action.busy}
                  {...feedback("playtest-stop", "Stopping…")}
                  onClick={() =>
                    action.run(() => api.stop(project.id), "", "playtest-stop")
                  }
                />
              }
            />
          )
        }
      >
        <FieldRow id="qa-focus" label="QA focus">
          {(props) => (
            <select
              {...props}
              value={fields.text.focus}
              disabled={disabled}
              onChange={(event) => editText("focus", event.target.value)}
            >
              {[
                ["release", "Full game text"],
                ["database", "Database"],
                ["dialogue", "Dialogue"],
                ["risky-codes", "Risky event codes"],
              ].map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </FieldRow>
      </TextQaWork>
    </>
  );
  const footer = unsaved ? (
    <ActionControl
      label="Save version"
      variant="primary"
      disabled={disabled || (action.key === "qa-save" && !!action.notice)}
      {...(action.key === "qa-save"
        ? feedback("qa-save", "Saving…")
        : { feedbackKey: action.key, error: action.error })}
      onClick={() =>
        action.run(
          async () => {
            await save();
            await saveQaVersion(project.id, whenFinished);
          },
          "Version saved.",
          "qa-save",
        )
      }
    />
  ) : phase === "not_started" ? (
    start("Start text QA")
  ) : phase === "outdated" || phase === "blocked" ? (
    // Preparing again sets aside a task the app can't read. The assistant
    // prepares again itself once its own fixes change the game's plugins.
    start(
      "Run QA again",
      assisted && qa.plugins_changed && phase === "outdated"
        ? "default"
        : "primary",
    )
  ) : phase === "applied" || phase === "clean" ? (
    // Text edited since, such as new translation, or the playtest's
    // findings can take another pass, which the assistant takes itself.
    start("Run QA again", again && !assisted ? "primary" : "default")
  ) : phase === "ready" ? (
    <ActionControl
      label={applyFailed ? "Try again" : "Apply corrections"}
      variant="primary"
      disabled={disabled}
      {...feedback("qa-apply", "Applying…")}
      onClick={() => step("qa-apply", "apply", {}, "Corrections applied.")}
    />
  ) : phase === "running" ? (
    copyTask(
      "qa",
      "Copy QA task",
      "default",
      "QA task copied. Paste it into your coding assistant.",
    )
  ) : undefined;
  return {
    content,
    action: footer,
    // Next leads once QA is done and its assistant is no longer at work,
    // such as playing the game again after QA's apply.
    next: advance(
      undefined,
      undefined,
      ["applied", "clean"].includes(phase) &&
        !again &&
        !assisted &&
        (!unsaved || (action.key === "qa-save" && !!action.notice))
        ? "primary"
        : "quiet",
    ),
    heading: {
      title: "Text QA",
      description: playtest
        ? "Your assistant reviews the game's text, plays the game and fixes what it finds; you answer only what it can't settle."
        : "Your assistant reviews the game's text and applies verified corrections; you answer only what it can't settle.",
    },
  };
}
