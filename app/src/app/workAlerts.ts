import type {
  AssistantTaskKind,
  Job,
  TranslationJob,
  WorkspaceSnapshot,
} from "../api/contracts.ts";
import {
  assistantSources,
  assistantTaskTitles,
  copiedTaskStandings,
} from "../features/assistant/assistantTasks.ts";
import {
  historyMode,
  historyOutcome,
  historyPhase,
} from "../features/guided/historyView.ts";
import {
  attemptJobs,
  awaitingQuote,
  estimateOutdated,
} from "../features/translation/apiRun.ts";
import { assistantRunState } from "../features/translation/assistantPhases.ts";
import { displayLabels } from "../ui/displayStatus.ts";
import { sentence } from "../ui/displayText.ts";

/** Work that ends sooner than this ended while the user was watching. */
export const WATCHED_MS = 10_000;

/** Something to come back to the window for, in one open game. */
export interface WorkAlert {
  /** The game's name. */
  title: string;
  /** What happened, what needs the user first. */
  lines: string[];
}

type Phase = "working" | "waiting" | "ended";

/** App work the user started and may be waiting on. */
interface Work {
  id: string;
  phase: Phase;
  created?: string;
  /** "Set up · Finished", or for a run, what it waits for. */
  text: string;
  /** Waiting is the user's turn; work another line covers says nothing. */
  silentWait?: boolean;
}

/** A Guided run or estimate in the words History uses. */
function guidedRun(job: Job): Work {
  const outcome = historyOutcome(job).label;
  return {
    id: job.id,
    // Waiting runs wait for a cost or name approval.
    phase:
      job.status === "waiting"
        ? "waiting"
        : ["ready", "running"].includes(job.status)
          ? "working"
          : "ended",
    created: job.created,
    text:
      job.mode === "estimate"
        ? `${historyPhase(job)} · ${outcome}`
        : `${historyPhase(job)} · ${historyMode(job)} · ${outcome}`,
  };
}

/**
 * A step or app-held run. A held run waits at its provider while "waiting"
 * and for the user's approval while "ready", which the estimate line says.
 */
function operation(job: {
  id: string;
  label?: string;
  status: string;
  created?: string;
}): Work {
  return {
    id: job.id,
    phase: ["running", "waiting"].includes(job.status)
      ? "working"
      : job.status === "ready"
        ? "waiting"
        : "ended",
    created: job.created,
    text: `${job.label || "Work"} · ${
      job.status === "complete" ? "Finished" : sentence(job.status)
    }`,
    silentWait: true,
  };
}

/**
 * The open game's work that the user starts and then waits for. In Guided
 * that is every run and step; an Assistant-led game's helper steps are its
 * assistant's, so only API runs and Start over count there.
 */
function userWork(snapshot: WorkspaceSnapshot, projectId: string): Work[] {
  const method = snapshot.application.project?.method;
  const translation =
    snapshot.translation?.projectId === projectId ? snapshot.translation : null;
  const jobs: TranslationJob[] = translation?.jobs || [];
  if (method === "len")
    return jobs
      .filter((job) =>
        job.kind === "translation"
          ? job.mode !== "agent"
          : job.action === "start_over",
      )
      .map(operation);
  if (method !== "guided") return [];
  const guided =
    snapshot.guided?.projectId === projectId ? snapshot.guided : null;
  const runs = new Map<string, Job>();
  for (const job of [
    guided?.run,
    ...(guided?.runs || []),
    ...Object.values(guided?.estimates || {}).map((value) => value?.job),
    ...Object.values(guided?.phaseRuns || {}),
  ])
    if (job) runs.set(job.id, job);
  return [
    ...jobs.map(operation),
    ...(guided?.operations || []).map(operation),
    ...[...runs.values()].map(guidedRun),
  ];
}

/** What waits on the user while nobody in the app works on it, by key. */
function needs(snapshot: WorkspaceSnapshot, projectId: string) {
  const found = new Map<string, string>();
  const translation =
    snapshot.translation?.projectId === projectId ? snapshot.translation : null;
  if (snapshot.application.project?.method === "len" && translation) {
    const progress = translation.progress;
    const state = assistantRunState(progress, true);
    if (state === "blocked")
      found.set(
        `blocked:${progress!.blocker}`,
        `Your assistant needs you: ${progress!.blocker}`,
      );
    if (state === "done")
      found.set("done", "Your assistant finished the translation");
    for (const job of attemptJobs(translation))
      if (job.kind === "translation" && awaitingQuote(job))
        if (!estimateOutdated(job))
          found.set(
            `quote:${job.id}`,
            "An API estimate waits for your approval",
          );
  }
  const qa =
    snapshot.guided?.projectId === projectId
      ? snapshot.guided.readiness.qa
      : null;
  if (qa?.current && !qa.applied)
    for (const question of qa.questions)
      if (!question.choice) found.set(`qa:${question.id}`, "");
  return found;
}

/**
 * Watches one window's observations for moments the user would come back
 * for: work they started that took a while ending or waiting for approval,
 * a copied task coming back from their assistant, text QA's questions, and
 * an Assistant-led run that is blocked, finished or waiting for approval.
 * The first observation of a game only sets where things stand.
 */
export class WorkAlerts {
  private project: string | null = null;
  /** User work in progress or waiting, with when it started working. */
  private work = new Map<string, { phase: Phase; since: number }>();
  private needs = new Set<string>();
  private copied = new Map<AssistantTaskKind, string>();

  observe(snapshot: WorkspaceSnapshot, now: number): WorkAlert | null {
    const project = snapshot.application.project;
    const id = project?.available ? project.id : null;
    const fresh = id !== this.project;
    this.project = id;
    if (fresh) {
      this.work.clear();
      this.needs.clear();
      this.copied.clear();
    }
    if (!id || !project) return null;
    const first: string[] = [];
    const last: string[] = [];

    const work = new Map<string, { phase: Phase; since: number }>();
    for (const item of userWork(snapshot, id)) {
      const before = this.work.get(item.id);
      const watched =
        before?.phase === "working" && now - before.since >= WATCHED_MS;
      if (item.phase === "ended") {
        if (watched) last.push(item.text);
        continue;
      }
      if (item.phase === "waiting" && watched && !item.silentWait)
        first.push(item.text);
      const created = Date.parse(item.created || "");
      work.set(item.id, {
        phase: item.phase,
        // Work running when a game is first observed started when it was
        // made; work resumed after an approval starts again.
        since: !before
          ? fresh && !Number.isNaN(created)
            ? Math.min(now, created)
            : now
          : before.phase === "waiting" && item.phase === "working"
            ? now
            : before.since,
      });
    }
    this.work = work;

    const found = needs(snapshot, id);
    const questions = [...found.keys()].filter(
      (key) => key.startsWith("qa:") && !this.needs.has(key),
    ).length;
    if (!fresh) {
      for (const [key, text] of found)
        if (text && !this.needs.has(key)) first.push(text);
      if (questions)
        first.push(
          `Text QA has ${questions.toLocaleString()} new ${
            questions === 1 ? "question" : "questions"
          } for you`,
        );
    }
    this.needs = new Set(found.keys());

    const copied = new Map<AssistantTaskKind, string>();
    for (const task of copiedTaskStandings(assistantSources(snapshot)!)) {
      if (task.state === "waiting") {
        copied.set(task.kind, task.copiedAt);
        continue;
      }
      // Text QA's questions have their own line.
      if (
        this.copied.get(task.kind) !== task.copiedAt ||
        task.state === "idle" ||
        (task.kind === "qa" && task.state === "needs_review")
      )
        continue;
      const title = assistantTaskTitles[task.kind];
      if (task.state === "finished")
        last.push(`Your assistant finished ${title}`);
      else first.push(`${title} · ${task.detail || displayLabels[task.state]}`);
    }
    this.copied = copied;

    const lines = [...first, ...last];
    return lines.length ? { title: project.name, lines } : null;
  }
}
