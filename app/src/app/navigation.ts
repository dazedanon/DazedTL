import type {
  GuidedState,
  Screen,
  WorkspaceSnapshot,
} from "../api/contracts.ts";

export interface NavigationStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

type GuidedLocation = Pick<GuidedState, "step" | "task" | "contextDocument"> & {
  eventView: GuidedState["eventText"]["view"];
};
export type NavigationChange = Partial<GuidedLocation>;
type Preferences = NavigationChange & { positions?: GuidedState["positions"] };
const steps = new Set(["setup", "context", "translate", "check", "release"]);
// Stages that earlier versions saved, and the stage that holds their work now.
const legacySteps: Record<string, GuidedState["step"]> = {
  prepare: "setup",
  advanced: "translate",
  plugins: "translate",
  images: "translate",
  apply: "check",
  layout: "check",
  review: "release",
};
const legacyTasks: Record<string, string> = {
  backup: "setup",
  extract: "setup",
  format: "setup",
  baseline: "setup",
  "image-text": "images",
  "image-manager": "images",
  playtest: "fitting",
  tools: "fitting",
  // Check's Pending changes task was removed; its stage opens on fitting.
  apply: "fitting",
};
/**
 * Preferences saved by earlier stage layouts, in the current stages. Apply &
 * Fitting kept its view separately; its Check task replaces it.
 */
function migrate(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const { textView, ...saved } = value as Record<string, unknown>;
  const view = ["fitting", "qa"].includes(String(textView))
    ? String(textView)
    : "fitting";
  const task = (step: unknown, name: unknown) =>
    step === "apply" && name === "apply"
      ? view
      : typeof name === "string"
        ? legacyTasks[name] || name
        : name;
  const result: Record<string, unknown> = { ...saved };
  if (typeof saved.step === "string" && saved.step in legacySteps)
    result.step = legacySteps[saved.step];
  if ("task" in saved) result.task = task(saved.step, saved.task);
  if (saved.positions && typeof saved.positions === "object") {
    const positions: Record<string, unknown> = {};
    for (const [step, name] of Object.entries(saved.positions)) {
      const current = legacySteps[step] || step;
      // A stage's own saved task wins over one moved in from a retired stage.
      if (step === current || !(current in positions))
        positions[current] = task(step, name);
    }
    result.positions = positions;
  }
  return result;
}
const task = (value: unknown) =>
  value === null ||
  (typeof value === "string" && /^[a-z][a-z0-9-]{0,59}$/.test(value));

function valid(value: unknown): value is Preferences {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const p = value as Preferences;
  return (
    Object.keys(p).every((key) =>
      ["step", "task", "positions", "contextDocument", "eventView"].includes(
        key,
      ),
    ) &&
    (p.step === undefined || steps.has(p.step)) &&
    (p.task === undefined || task(p.task)) &&
    (p.contextDocument === undefined ||
      (typeof p.contextDocument === "string" &&
        p.contextDocument.length <= 2000)) &&
    (p.eventView === undefined ||
      ["audit", "sources", "advanced-run", "variables"].includes(
        p.eventView,
      )) &&
    (p.positions === undefined ||
      (!!p.positions &&
        typeof p.positions === "object" &&
        !Array.isArray(p.positions) &&
        Object.entries(p.positions).every(
          ([step, value]) => steps.has(step) && task(value),
        )))
  );
}

/** Presentation preferences only: never project ownership, drafts or execution state. */
export class Navigation {
  private owner: string | null | undefined;
  private screen: Screen | undefined;
  private preferences: Preferences = {};
  private storage?: NavigationStorage;
  constructor(storage?: NavigationStorage) {
    this.storage = storage;
  }

  private key(projectId: string) {
    return "dazedtl:guided-navigation:v1:" + projectId;
  }

  observe(snapshot: WorkspaceSnapshot): WorkspaceSnapshot {
    const owner = snapshot.application.project?.id || null;
    if (owner !== this.owner) {
      this.owner = owner;
      this.screen = undefined;
      this.preferences = {};
      if (owner) {
        try {
          const saved = migrate(
            JSON.parse(this.storage?.getItem(this.key(owner)) || "null"),
          );
          if (valid(saved)) this.preferences = saved;
        } catch {
          /* Invalid browser preferences fall back to the saved backend view. */
        }
      }
    }
    if (this.screen === undefined && !Object.keys(this.preferences).length)
      return snapshot;
    let guided = snapshot.guided;
    if (guided && guided.projectId === owner) {
      const { positions, eventView, contextDocument, ...location } =
        this.preferences;
      guided = {
        ...guided,
        ...location,
        positions: { ...guided.positions, ...positions },
        contextDocument:
          contextDocument &&
          (Object.hasOwn(guided.documents, contextDocument) ||
            Object.hasOwn(guided.drafts, contextDocument))
            ? contextDocument
            : guided.contextDocument,
        eventText: eventView
          ? { ...guided.eventText, view: eventView }
          : guided.eventText,
      };
    }
    return {
      ...snapshot,
      guided,
      application: {
        ...snapshot.application,
        screen: this.screen || snapshot.application.screen,
      },
    };
  }

  navigate(snapshot: WorkspaceSnapshot, screen: Screen) {
    if (
      !["project", "translation", "guided", "manual", "settings"].includes(
        screen,
      )
    )
      throw new Error("Choose an available screen.");
    if (
      ["translation", "guided", "manual"].includes(screen) &&
      !snapshot.application.project
    )
      throw new Error("Open a game project first.");
    this.screen = screen;
  }

  guided(
    snapshot: WorkspaceSnapshot,
    projectId: string,
    change: NavigationChange,
  ) {
    const state = snapshot.guided;
    if (projectId !== this.owner || state?.projectId !== projectId)
      throw new Error("Open this project's Translation workspace first.");
    const preferences = { ...this.preferences, ...change };
    if (change.step !== undefined)
      preferences.positions = {
        ...state.positions,
        ...preferences.positions,
        [change.step]: change.task ?? null,
      };
    if (!valid(preferences))
      throw new Error("Choose an available workflow view.");
    // Write the small preference before switching. A storage failure retains
    // the old view; game documents and recovery drafts never enter this record.
    this.storage?.setItem(this.key(projectId), JSON.stringify(preferences));
    this.preferences = preferences;
  }
}
