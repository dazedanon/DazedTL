import type {
  CompareChoice,
  CompareKind,
  CompareModel,
  CompareScene,
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

/** A model's price under its name: the estimate's before it translates,
 * then what it cost and how long it took. */
export function modelDetail(model: CompareModel, translated: boolean) {
  if (translated && model.cost !== undefined)
    return [
      formatCost(model.cost),
      model.seconds !== undefined && formatDuration(model.seconds),
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
