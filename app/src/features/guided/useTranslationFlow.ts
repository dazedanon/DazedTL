import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type { GuidedState, Job, Phase, Preview } from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { estimateFollowup, preparationFollowup } from "./translationView";

export type TranslationFlowState = {
  phase: Phase; mode: "batch" | "translate"; files: string[];
  stage: "preparing" | "estimating" | "batch" | "review" | "empty" | "error" | "canceling";
  estimateId?: string; runId?: string; job?: Job; preview?: Preview;
  decision?: boolean;
  namesApproved?: boolean;
  error?: string;
};
type Session = { state: TranslationFlowState; advanced: boolean; canceled: boolean; finished: boolean; answeredApproval?: string };
type Options = { projectId: string; phase: Phase; mode: "batch" | "translate"; files: string[]; state: GuidedState;
  dirty: boolean; busy: boolean; save: () => Promise<void>; settle: () => Promise<unknown> | void };

/** One visible operation, driven by the existing observer and guarded actions. */
export function useTranslationFlow(options: Options) {
  const latest = useRef(options); latest.current = options;
  const current = useRef<Session | null>(null);
  const [state, setState] = useState<TranslationFlowState | null>(null);
  const action = useAction({ after: async () => {
    try { await latest.current.settle(); }
    catch (error) {
      const session = current.current;
      if (session) {
        session.finished = false; session.canceled = false;
        change(session, { stage: "error", error: messageOf(error) });
      }
      throw error;
    }
  } });
  const claimed = useRef(new Set<string>());
  useEffect(() => () => { if (current.current) current.current.canceled = true; current.current = null; }, []);
  function change(session: Session, patch: Partial<TranslationFlowState>) {
    if (current.current !== session) return;
    session.state = { ...session.state, ...patch }; setState(session.state);
  }
  function finish(session: Session) {
    if (current.current === session) { current.current = null; setState(null); }
  }
  async function abandon(session: Session) {
    const id = session.state.runId || session.state.estimateId;
    if (id) await api.guided.discardPreparation(options.projectId, id);
    session.finished = true;
  }
  const canceled = (session: Session) => session.canceled || current.current !== session;
  function perform(session: Session, task: () => Promise<void>, discardCanceled = true) {
    const pending = action.run(async () => {
      try {
        await task();
        if (session.canceled && discardCanceled) await abandon(session);
      } catch (error) {
        session.canceled = false;
        change(session, { stage: "error", error: messageOf(error) });
        throw error;
      }
    }, "", "translation-flow");
    void pending.then(result => { if (result.ok && session.finished) finish(session); });
    return pending;
  }
  function start(files = latest.current.files) {
    if (current.current || action.busy || latest.current.busy) return;
    const session: Session = { advanced: false, canceled: false, finished: false,
      state: { phase: latest.current.phase, mode: latest.current.mode, files: [...files], stage: "preparing" } };
    current.current = session; setState(session.state);
    void perform(session, async () => {
      await latest.current.save();
      if (canceled(session)) return;
      await api.phase(options.projectId, session.state.phase);
      if (canceled(session)) return;
      const preview = await api.preview(options.projectId, "start", undefined, { mode: "estimate" });
      if (canceled(session)) return;
      const estimate = await api.execute(options.projectId, preview.token);
      // Retain the ID even after cancellation so a late reply is discarded,
      // never followed into another preparation or paid submission.
      session.state.estimateId = estimate.id;
      if (!canceled(session)) change(session, { stage: "estimating", job: estimate });
    });
  }
  useEffect(() => {
    const session = current.current;
    if (!session || session.canceled || session.finished || action.busy) return;
    const value = session.state;
    if (value.stage === "estimating" && value.estimateId && !session.advanced) {
      const result = estimateFollowup(value.estimateId, options.state.estimates[value.phase], options.state.runs,
        options.dirty || value.phase !== options.phase || value.mode !== options.mode);
      if (result.kind === "waiting") {
        if (result.job && result.job !== value.job) change(session, { job: result.job });
        return;
      }
      session.advanced = true;
      if (result.kind === "failed" || result.kind === "stale") {
        change(session, { stage: "error", error: result.kind === "stale" ? "The selection or guidance changed. Prepare a fresh estimate." : result.job?.message || "The estimate could not finish." });
      } else if (result.kind === "empty" && value.phase !== "variables") {
        change(session, { stage: "empty", job: result.job! });
      } else {
        change(session, { stage: "batch", job: undefined });
        void perform(session, async () => {
          const preview = await api.preview(options.projectId, "start", undefined, { mode: value.mode });
          if (canceled(session)) return;
          if (value.mode === "translate") { change(session, { stage: "review", preview }); return; }
          const run = await api.execute(options.projectId, preview.token);
          session.state.runId = run.id; claimed.current.add(run.id);
          if (!canceled(session)) change(session, { stage: "batch" });
        });
      }
    } else if (value.stage === "batch" && value.runId) {
      const result = preparationFollowup(value.runId, options.state.runs, session.answeredApproval), job = result.job;
      if (result.kind === "review") change(session, { stage: "review", job, decision: undefined });
      else if (result.kind === "failed") change(session, { stage: "error", error: job?.message || "Request preparation did not finish.", job });
      else if (result.kind === "empty") change(session, { stage: "empty", job });
      else if (job && job !== value.job) change(session, { job });
    }
  }, [options.state.runs, options.state.estimates, options.dirty, options.phase, options.mode, action.busy, state]);
  function cancel() {
    const session = current.current;
    if (!session) return;
    // The approved name pass is retained paid work. Closing its preparation
    // view must not try to discard it or stop the continuing Batch collection.
    if (session.state.namesApproved) { finish(session); return; }
    if (session.state.stage === "error") { finish(session); return; }
    session.canceled = true; change(session, { stage: "canceling" });
    if (!action.busy) void perform(session, async () => {});
  }
  function answer(approved: boolean) {
    const session = current.current;
    if (!session || session.finished || action.busy) return;
    const value = session.state;
    change(session, { decision: approved });
    void perform(session, async () => {
      if (value.job?.approval) {
        const prompt = value.job.approval;
        await api.answer(options.projectId, prompt.token, approved);
        session.answeredApproval = prompt.token;
        if (approved && prompt.kind === "speakers") change(session, { stage: "batch", job: { ...value.job, approval: undefined }, namesApproved: true, decision: undefined });
        else session.finished = true;
      } else if (approved && value.preview) {
        const run = await api.execute(options.projectId, value.preview.token);
        session.state.runId = run.id;
        session.finished = true;
      } else await abandon(session);
    }, false);
  }
  function dismiss() { if (current.current) finish(current.current); }
  return { state, active: !!state || action.busy, busy: action.busy || !!current.current?.finished, claimed: claimed.current,
    start, cancel, answer, dismiss, retry: () => { const files = current.current?.state.files; dismiss(); start(files); } };
}
