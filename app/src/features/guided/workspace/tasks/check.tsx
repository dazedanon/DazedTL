/** Check: the line width check, the glossary check and optional text QA. */
import type { ReactNode } from "react";
import { textLocation } from "../../textLocation";
import { ActionList, ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { FieldRow } from "../../../../ui/FieldRow";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import { HelpPopover } from "../../../../ui/HelpPopover";
import { fittingCodes, fittingSummary } from "../../FittingSettings";
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
import { savedTranslations } from "../../translationView";
import { GlossaryCheckWork } from "../../GlossaryCheck";
import { glossaryPhase } from "../../glossaryView";
import { PlaytestWork } from "../../Playtest";
import {
  playtestFailure,
  playtestPhase,
  playtestWaiting,
} from "../../playtestView";

export function fittingView(w: GuidedWorkspace): TaskView {
  const {
    state,
    values,
    setPanel,
    baseline,
    layoutFiles,
    editText,
    disabled,
    task,
    layoutOptions,
    fitting,
    fittingCurrent: scanCurrent,
    fittingEligible: eligible,
    reviewPending,
    advance,
    fileRow,
    fields,
  } = w;
  // Translated plugin command text (357) loses its line breaks, so a
  // project that translates it needs 357 in fitting to wrap it again.
  const codes = fittingCodes(fields.text.codes);
  const unwrapped357 =
    values.engine_options.CODE357 === true && !codes.includes(357);
  const [scope, rewrap] = fittingSummary(fields.text, fields.only_overflow);
  const skipped = fitting?.overflow_skipped || 0;
  // What would be rewrapped leads; skipped messages follow with why.
  const changes = [...(fitting?.previews || [])].sort(
    (a, b) => Number(!!a.overflow) - Number(!!b.overflow),
  );
  let content: ReactNode;
  content = (
    <>
      {unwrapped357 && (
        <Notice tone="warning">
          <span>
            Translated plugin command text (357) loses its line breaks and is
            not included in fitting.
          </span>
          <Button
            variant="link"
            disabled={disabled}
            onClick={() => editText("codes", [...codes, 357].join(","))}
          >
            Include 357
          </Button>
        </Notice>
      )}
      <ActionList>
        <ActionRow
          label={
            <>
              <strong>
                Line widths{" "}
                <HelpPopover label="Line widths">
                  Widths count characters. They do not measure rendered fonts or
                  substitutions. Text QA keeps its corrections within the
                  message rows.
                </HelpPopover>
              </strong>
              <small>
                Dialogue {values.widths.width} · portrait{" "}
                {values.widths.faceWidth} · list {values.widths.listWidth} ·
                notes {values.widths.noteWidth} · {values.widths.messageRows}{" "}
                message rows
              </small>
            </>
          }
        >
          <Button disabled={disabled} onClick={() => setPanel("widths")}>
            Edit line widths
          </Button>
        </ActionRow>
        {fileRow(layoutFiles)}
        <ActionRow
          label={
            <>
              <strong>Checked text</strong>
              <small>{scope}</small>
              <small>{rewrap}</small>
            </>
          }
        >
          <Button disabled={disabled} onClick={() => setPanel("fitting")}>
            Edit settings
          </Button>
        </ActionRow>
      </ActionList>
      {fitting && (
        <section className="text-fit-results" aria-label="Last check">
          <div className="check-results-heading">
            <h3>
              {eligible
                ? `${eligible} ${eligible === 1 ? "rewrap" : "rewraps"} found`
                : fields.only_overflow
                  ? "No line is wider than these widths"
                  : "Nothing to rewrap"}
              {!!skipped && ` · ${skipped} skipped`}
            </h3>
            {!scanCurrent && (
              <span className="muted">From before your setting changes</span>
            )}
            {/* With rewraps found the footer applies them; checking again
                stays beside the result. Otherwise the footer checks. */}
            {scanCurrent &&
              eligible > 0 &&
              task(
                "rewrap_preview",
                "Check again",
                layoutOptions,
                !baseline || !layoutFiles.length,
                "link",
              )}
          </div>
          {changes.length < fitting.changes_found && (
            <p className="muted">
              The first {changes.length.toLocaleString()} of{" "}
              {fitting.changes_found.toLocaleString()} are listed; Apply covers
              them all.
            </p>
          )}
          {!!changes.length && (
            <ul className="text-fit-changes">
              {changes.map((row, index) => (
                <li key={index}>
                  <div className="text-fit-change-heading">
                    <span>
                      {row.file_name} · {textLocation(row.locator)}
                    </span>
                    {row.rows !== undefined && (
                      <small>
                        {row.overflow
                          ? `Skipped · would need ${row.rows} rows`
                          : `${row.rows} ${row.rows === 1 ? "row" : "rows"}`}
                      </small>
                    )}
                  </div>
                  {!row.overflow && (
                    <dl className="text-fit-change">
                      <dt>Now</dt>
                      <dd>{row.before}</dd>
                      <dt>Rewrapped</dt>
                      <dd>{row.after}</dd>
                    </dl>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
  const run =
    scanCurrent && eligible > 0
      ? reviewPending({
          only: "rewraps",
          label: `Apply ${eligible} ${eligible === 1 ? "rewrap" : "rewraps"}`,
          blocked: !baseline || !layoutFiles.length,
        })
      : task(
          "rewrap_preview",
          "Check line widths",
          layoutOptions,
          !baseline || !layoutFiles.length || !fields.text.categories.length,
          scanCurrent ? "default" : "primary",
        );
  return {
    content,
    action: run,
    // A current scan that found nothing to fit completes the task.
    next: advance(
      undefined,
      undefined,
      scanCurrent && eligible === 0 ? "primary" : "quiet",
    ),
    // Fitting reads the game's current text, so it needs applied output.
    actionContext: !savedTranslations(state).applied.length && (
      <span>Apply translations first; the check reads the game’s text.</span>
    ),
    heading: {
      title: "Line width check",
      description:
        "Rewrap applied text that is wider than the saved line widths.",
    },
  };
}

export function glossaryCheckView(w: GuidedWorkspace): TaskView {
  const {
    project,
    state,
    baseline,
    action,
    disabled,
    feedback,
    task,
    advance,
    save,
    preparePreview,
    whenFinished,
    move,
  } = w;
  const glossary = state.readiness.glossary;
  const phase = glossaryPhase(glossary);
  // The check reads the game's own text, whichever profile or method
  // translated it.
  const check = (label: string, variant: "primary" | "default" | "link") =>
    task(
      "glossary_check",
      label,
      {},
      baseline ? false : "Set up the game first.",
      variant,
    );
  /** Puts the chosen fixes into the game, then checks again, so the list
   * shows what is left. */
  const apply = () =>
    action.run(
      async () => {
        await save();
        const started = await api.guided.glossary(project.id, "apply");
        const ended = await whenFinished(started.operation!.id);
        if (ended.status !== "complete")
          throw new Error(
            ended.message || "The fixes did not go into the game.",
          );
        const preview = await preparePreview("glossary_check", {});
        await whenFinished((await api.execute(project.id, preview.token)).id);
      },
      `${glossary.fixes === 1 ? "Fix" : "Fixes"} applied.`,
      "glossary-apply",
    );
  const footer =
    phase === "review" ? (
      <ActionControl
        label={
          glossary.fixes
            ? `Apply ${glossary.fixes.toLocaleString()} ${glossary.fixes === 1 ? "fix" : "fixes"}`
            : "Apply fixes"
        }
        variant="primary"
        disabled={disabled || !glossary.fixes}
        disabledReason={glossary.fixes ? "" : "Choose the fixes to apply."}
        {...feedback("glossary-apply", "Applying…")}
        onClick={apply}
      />
    ) : (
      check(
        phase === "none" ? "Check glossary terms" : "Check again",
        phase === "done" ? "default" : "primary",
      )
    );
  return {
    content: (
      <>
        <ActionList>
          <ActionRow
            title="Glossary"
            description="The game's own rows in Guidance; the base glossary's honorifics and interface terms only guide translation."
          >
            <Button
              disabled={disabled}
              onClick={() => void move("context", "guidance", "glossary")}
            >
              Edit glossary
            </Button>
          </ActionRow>
        </ActionList>
        <GlossaryCheckWork
          projectId={project.id}
          state={glossary}
          disabled={disabled}
          feedback={feedback}
          run={(key, work) => void action.run(work, "", key)}
          // With lines to settle the footer applies; checking again stays
          // beside the result.
          checkAgain={phase === "review" && check("Check again", "link")}
        />
      </>
    ),
    action: footer,
    next: advance(undefined, undefined, phase === "done" ? "primary" : "quiet"),
  };
}

export function qaView(w: GuidedWorkspace): TaskView {
  const {
    state,
    project,
    baseline,
    qa,
    qaJob,
    action,
    disabled,
    feedback,
    editText,
    copyTask,
    inspect,
    advance,
    fields,
    handoff,
    operationJob,
    whenFinished,
    save,
    setPanel,
  } = w;
  const phase = qaPhase(qa);
  // Problems the playtest found in translated text, which QA reviews when
  // it next prepares.
  const found = playtestWaiting(state.readiness.playtest);
  const again = found > 0 && ["applied", "clean"].includes(phase);
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
      {found > 0 && (
        <Notice>
          The playtest found {found.toLocaleString()}{" "}
          {found === 1 ? "problem" : "problems"} in translated text; QA reviews{" "}
          {found === 1 ? "it" : "them"}{" "}
          {phase === "running" ? "in its next round." : "when it runs again."}
        </Notice>
      )}
      <TextQaWork
        qa={qa}
        waiting={handoff("qa").waiting}
        disabled={disabled}
        feedback={feedback}
        applyFailed={applyFailed}
        run={step}
        onCoverage={() => setPanel("qa-coverage")}
        restorable
        report={
          qaJob && (
            <Button variant="link" onClick={() => inspect(qaJob)}>
              Report details
            </Button>
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
    // Preparing again sets aside a task the app can't read.
    start("Run QA again")
  ) : phase === "applied" || phase === "clean" ? (
    // Text edited since, such as new translation, or the playtest's
    // findings can take another pass.
    start("Run QA again", again ? "primary" : "default")
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
    next: advance(
      undefined,
      undefined,
      ["applied", "clean"].includes(phase) &&
        !again &&
        (!unsaved || (action.key === "qa-save" && !!action.notice))
        ? "primary"
        : "quiet",
    ),
    heading: {
      title: "Text QA",
      description:
        "Your assistant reviews the game's text and applies verified corrections; you answer only what it can't settle.",
    },
  };
}

export function playtestView(w: GuidedWorkspace): TaskView {
  const {
    project,
    state,
    action,
    disabled,
    feedback,
    advance,
    operationJob,
    save,
  } = w;
  const playtest = state.readiness.playtest;
  const job = operationJob("release_playtest");
  const running = job?.status === "running";
  const phase = playtestPhase(playtest, running);
  const content: ReactNode = (
    <PlaytestWork
      projectId={project.id}
      playtest={playtest}
      running={running}
      progress={running ? job?.message : undefined}
      failed={playtestFailure(playtest, job)}
    />
  );
  const footer = running ? (
    <ActionControl
      label="Stop playtest"
      disabled={action.busy}
      {...feedback("playtest-stop", "Stopping…")}
      onClick={() =>
        action.run(() => api.stop(project.id), "", "playtest-stop")
      }
    />
  ) : (
    <ActionControl
      label={phase === "not_started" ? "Run playtest" : "Run playtest again"}
      variant={phase === "done" ? "default" : "primary"}
      disabled={disabled}
      {...feedback("playtest", "Starting…")}
      onClick={() =>
        action.run(
          async () => {
            await save();
            await api.guided.playtest(project.id, "run");
          },
          "",
          "playtest",
        )
      }
    />
  );
  return {
    content,
    action: footer,
    next: advance(undefined, undefined, phase === "done" ? "primary" : "quiet"),
    heading: {
      title: "Playtest",
      description:
        "DazedTL plays the game to find crashes, Japanese left on screen and text that doesn't fit; problems in translated text go to Text QA.",
    },
  };
}
