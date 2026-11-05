import type {
  CompareChoice,
  CompareKind,
  CompareModel,
  CompareScene,
  CompareOperation,
  Comparison,
  WorkspaceSnapshot,
} from "../../api/contracts.ts";
import { formatDuration } from "../../ui/workTime.ts";

/** What fits side by side on a laptop screen, as the backend allows. */
export const versusModels = 4;

/** What one tab compares now: its kind, the file's first lines and models. */
export type CompareChoices = {
  kind: CompareKind;
  file: string;
  /** The file's first lines; 0 for all of them. */
  lines: number;
  candidates: readonly CompareChoice[];
};

const unfinished = ["ready", "running", "waiting"];
export const working = (status: string) => unfinished.includes(status);

/** Whether a compared model was sent as `choice`, settings and all. */
export function sameChoice(model: CompareModel, choice: CompareChoice) {
  return (
    model.connectionId === choice.connection_id &&
    model.model === choice.model &&
    (model.effort ?? null) === (choice.effort ?? null) &&
    (model.glossary ?? null) === (choice.glossary ?? null) &&
    (model.instruction ?? null) === (choice.instruction ?? null)
  );
}

/** The saved comparisons of exactly these choices, newest first. */
export function matching(
  comparisons: readonly Comparison[],
  choices: CompareChoices,
) {
  return comparisons.filter(
    (item) =>
      item.kind === choices.kind &&
      item.file === choices.file &&
      item.lines === choices.lines &&
      item.candidates.length === choices.candidates.length &&
      item.candidates.every((model, index) =>
        sameChoice(model, choices.candidates[index]),
      ),
  );
}

/**
 * The comparison the footer acts on, the newest of these choices, and the
 * one whose lines show: the newest of them translated, so a new estimate
 * keeps the last results in view until it is translated too.
 */
export function current(
  comparisons: readonly Comparison[],
  choices: CompareChoices,
) {
  const found = matching(comparisons, choices);
  const latest: Comparison | undefined = found[0];
  const shown: Comparison | undefined =
    latest?.stage === "translation"
      ? latest
      : found.find((item) => item.stage === "translation") || latest;
  return { latest, shown };
}

/**
 * What translating a comparison's estimate costs, Live: the sum of the
 * models it priced, and those it leaves out for an error.
 */
export function estimateTotal(comparison: Comparison) {
  const priced = comparison.candidates.filter(
    (model) => model.estimate && !model.error,
  );
  return {
    cost: priced.reduce((sum, model) => sum + model.estimate!.cost, 0),
    priced: priced.length,
    left: comparison.candidates.filter((model) => !priced.includes(model)),
  };
}

/**
 * What a tab's footer offers for its choices' newest comparison: Translate
 * at the price an unused estimate found, the translation running, or an
 * estimate, again once these choices were translated or when the newest
 * estimate priced no model, with why. Whether an estimate was used comes
 * from the saved comparisons, which hold its translation once it starts.
 */
export function runStep(
  latest: Comparison | undefined,
  shown: Comparison | undefined,
):
  | { step: "translate"; cost: number; left: string[] }
  | { step: "translating"; cost: number }
  | { step: "estimate"; again: boolean; reason: string } {
  const total = latest && estimateTotal(latest);
  if (latest?.stage === "translation" && working(latest.status))
    return { step: "translating", cost: total!.cost };
  if (latest?.stage === "estimate" && latest.status === "complete") {
    if (total!.priced)
      return {
        step: "translate",
        cost: total!.cost,
        left: total!.left.map((model) => model.model),
      };
    return {
      step: "estimate",
      again: true,
      reason: "No model could be estimated. See each model’s error.",
    };
  }
  return {
    step: "estimate",
    again: latest?.stage === "translation" || !!shown?.translationId,
    reason: "",
  };
}

/**
 * Waits for the comparisons to be read again: each wait ends once a read
 * asked for at or after it has settled, so an action that changed them
 * finishes only once the page shows the change.
 */
export class Rereads {
  private asked = 0;
  private waits: { after: number; resolve: () => void }[] = [];
  /** Asks for another read: its number, which keys the read, and the wait
   * for it. */
  ask() {
    const after = ++this.asked;
    const done = new Promise<void>((resolve) =>
      this.waits.push({ after, resolve }),
    );
    return { after, done };
  }
  /** The read asked as `number` settled, with the comparisons or an error. */
  settled(number: number) {
    this.waits = this.waits.filter((wait) => {
      if (wait.after > number) return true;
      wait.resolve();
      return false;
    });
  }
}

/** A string's FNV-1a hash, the seed of a comparison's column order. */
function hash(text: string) {
  let value = 0x811c9dc5;
  for (let index = 0; index < text.length; index++) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 0x01000193);
  }
  return value >>> 0;
}

/**
 * The models' column order while names are hidden: shuffled once per
 * comparison, seeded by its ID, so it stays the same across renders,
 * revisits and restarts.
 */
export function blindOrder(id: string, count: number) {
  let seed = hash(id);
  // mulberry32: a small generator whose sequence the seed alone decides.
  const next = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value ^= value + Math.imul(value ^ (value >>> 7), 61 | value);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
  const order = Array.from({ length: count }, (_, index) => index);
  for (let index = count - 1; index > 0; index--) {
    const other = Math.floor(next() * (index + 1));
    [order[index], order[other]] = [order[other], order[index]];
  }
  return order;
}

/**
 * The best picks so far: how many rows each model won, how many rows have
 * a pick out of those any model translated, and the most picked model,
 * when one leads alone.
 */
export function picks(comparison: Comparison, marks: Record<string, number>) {
  const rows = comparison.rows.filter((row) =>
    row.translations.some((item) => item),
  );
  const won = comparison.candidates.map(() => 0);
  let picked = 0;
  for (const row of rows) {
    const choice = marks[row.id];
    const position = comparison.candidates.findIndex(
      (model) => model.index === choice,
    );
    if (position < 0 || !row.translations[position]) continue;
    won[position]++;
    picked++;
  }
  const most = Math.max(0, ...won);
  const leaders = won.flatMap((count, index) =>
    count === most && most > 0 ? [index] : [],
  );
  return {
    won,
    picked,
    total: rows.length,
    /** The position of the model that won the most rows, alone. */
    winner: leaders.length === 1 ? leaders[0] : null,
    /** Positions sharing the lead, when more than one does. */
    tied: leaders.length > 1 ? leaders : [],
  };
}

/**
 * Whether Model vs model hides a translation's model names: from the moment
 * it starts, while it is blind and not revealed, until every line has a
 * pick. `saved` holds the picks saved here ahead of the next read.
 */
export function namesHidden(
  comparison: Comparison | undefined,
  saved: { blind: boolean; revealed: boolean } | undefined,
  finished: boolean,
) {
  if (!comparison?.translationId) return false;
  const { blind, revealed } = saved ?? comparison;
  return blind && !revealed && !finished;
}

/** A translation's picks and Blind, from the moment it starts: those saved
 * here ahead of the next read, keyed by translation, or those read. */
export type CompareMarks = {
  marks: Record<string, number>;
  blind: boolean;
  revealed: boolean;
};
export function recordedMarks(
  comparison: Comparison | undefined,
  saved: Readonly<Record<string, CompareMarks>>,
): CompareMarks | null {
  if (!comparison?.translationId) return null;
  return (
    saved[comparison.translationId] ?? {
      marks: comparison.marks,
      blind: comparison.blind,
      revealed: comparison.revealed,
    }
  );
}

/** A model's error as its column shows it: while names are hidden, without
 * its words, which may name the model in any spelling. */
export const columnError = (model: CompareModel, hidden: boolean) =>
  model.error && hidden
    ? "This model didn’t finish. Why shows once the names are revealed."
    : model.error;

/** The Tune settings runs of one file's lines, oldest first, translated. */
export function tuneRuns(
  comparisons: readonly Comparison[],
  file: string,
  lines: number,
) {
  return comparisons
    .filter(
      (item) =>
        item.kind === "tune" &&
        item.file === file &&
        item.lines === lines &&
        item.stage === "translation",
    )
    .reverse();
}

/** The glossary's entries: its lines, leaving out headings and blanks. */
export function glossaryEntries(text: string) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

/**
 * How many entries a test glossary changes from the game's: each entry
 * edited, added or removed counts once.
 */
export function glossaryChanges(before: string, after: string) {
  const left = glossaryEntries(before);
  const right = glossaryEntries(after);
  const unmatched = (from: string[], against: string[]) => {
    const pool = new Map<string, number>();
    for (const line of against) pool.set(line, (pool.get(line) ?? 0) + 1);
    return from.filter((line) => {
      const count = pool.get(line) ?? 0;
      if (count) pool.set(line, count - 1);
      return !count;
    }).length;
  };
  return Math.max(unmatched(left, right), unmatched(right, left));
}

/** The line counts a file offers: its first 10 and 25, where it has more, and all. */
export function lineCounts(scene: Pick<CompareScene, "lines">) {
  return [10, 25].filter((count) => count < scene.lines).concat(0);
}

/** A comparison's price, to the tenth of a cent, since its lines are few. */
export function formatCost(value: number) {
  if (value <= 0) return "$0.00";
  if (value < 0.001) return "<$0.001";
  if (value >= 1) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(3).replace(/0$/, "")}`;
}

/**
 * The comparison running for the game, whichever tab or choices it was
 * started from, and what the page says of it: what it does, where it is,
 * and that the game's other work waits for it, as they share one queue.
 */
export function runningComparison(operations: readonly CompareOperation[]) {
  const operation = operations.find((item) => working(item.status));
  if (!operation) return null;
  return {
    operation,
    /** What it does, without its message, which names the model it is at,
     * so a blind comparison's names stay hidden on every tab. */
    text:
      operation.action === "compare_translate"
        ? "Translating a comparison"
        : "Estimating a comparison",
    waits: "Other work on this game waits until it ends.",
  };
}

/**
 * A comparison's operation as its footer reports it: its state, with its
 * message only while that can't name a hidden model and isn't a stop's
 * explanation, which each model's column already gives.
 */
export function runStatus(
  comparison: Comparison,
  label: string,
  namesHidden: boolean,
) {
  return {
    label,
    status: comparison.status,
    message:
      namesHidden || comparison.status === "stopped" ? "" : comparison.message,
  };
}

/**
 * The requests Show request opens for a model: the first ones its
 * translation kept, and what it says when it kept fewer than it sent.
 */
export function keptRequests(model: CompareModel) {
  const kept = model.keptRequests ?? 0;
  const sent = model.requests ?? kept;
  return {
    kept,
    note:
      kept && sent > kept
        ? `Only the first ${kept.toLocaleString()} of its ${sent.toLocaleString()} requests are kept.`
        : "",
  };
}

/** A model's price under its name: the estimate's before it translates,
 * then what it cost and how long it took. */
export function modelDetail(model: CompareModel, translated: boolean) {
  if (translated && model.cost !== undefined)
    return [
      formatCost(model.cost),
      model.seconds !== undefined && formatDuration(model.seconds, true),
    ]
      .filter(Boolean)
      .join(" · ");
  return model.estimate ? `about ${formatCost(model.estimate.cost)}` : "";
}

/**
 * What a game's comparable lines come from, as the observed state shows it:
 * its method, its Guided preparation, the Manual file loaded, the newest
 * Assistant-led run, whose organize made the groups, and Start over. Each
 * change reads the comparisons again.
 */
export function compareInputs(
  snapshot: WorkspaceSnapshot | null | undefined,
  projectId: string,
) {
  const project = snapshot?.application.project;
  if (project?.id !== projectId) return "";
  const guided =
    snapshot?.guided?.projectId === projectId ? snapshot.guided : null;
  const translation =
    snapshot?.translation?.projectId === projectId
      ? snapshot.translation
      : null;
  const newest = (translation?.jobs ?? [])
    .filter((job) => job.kind === "translation")
    .sort((a, b) => b.created.localeCompare(a.created))[0]?.id;
  return JSON.stringify([
    project.method,
    project.source,
    guided?.preparation.complete ?? null,
    guided?.collectionError ?? null,
    translation?.manual?.loaded?.sha256 ?? null,
    translation?.manual?.loaded?.loaded ?? null,
    translation?.lifecycle.started_over?.at ?? null,
    newest ?? null,
  ]);
}

/**
 * The key a page's read follows: the newest while the page shows, and while
 * hidden the last one it read, so a hidden page starts no reads and reads
 * once when it shows again after a change.
 */
export const shownKey = (shown: boolean, key: string, last: string | null) =>
  shown ? key : last;
