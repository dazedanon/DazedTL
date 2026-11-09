import type {
  CompareChoice,
  CompareKind,
  CompareModel,
  CompareRow,
  CompareScene,
  CompareOperation,
  Comparison,
  Project,
  WorkspaceSnapshot,
} from "../../api/contracts.ts";
import { formatDuration } from "../../ui/workTime.ts";

/** What fits side by side on a laptop screen, as the backend allows. */
export const versusModels = 4;

/** What the page compares now: its kind, the file's first lines and its
 * columns' models with their settings. */
export type CompareChoices = {
  kind: CompareKind;
  file: string;
  /** The file's first lines; 0 for all of them. */
  lines: number;
  candidates: readonly CompareChoice[];
};

const unfinished = ["ready", "running", "waiting"];
export const working = (status: string) => unfinished.includes(status);

/**
 * A choice's identity, as the backend keeps it: what it sets, in a fixed
 * order, leaving out what it leaves to the game's settings.
 */
export function choiceKey(choice: CompareChoice) {
  return JSON.stringify(
    Object.entries(choice)
      .filter(([, value]) => value !== undefined && value !== null)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
  );
}

/** Whether a compared model was estimated from `choice`, settings and all. */
export const sameChoice = (model: CompareModel, choice: CompareChoice) =>
  choiceKey(model.choice) === choiceKey(choice);

/** What a tab's choices now are, whole, as an action keeps them. */
export const choicesKey = (choices: CompareChoices) =>
  JSON.stringify([
    choices.kind,
    choices.file,
    choices.lines,
    choices.candidates.map(choiceKey),
  ]);

type RunAction = "estimate" | "translate";

/** The key a footer's action runs under: what it does, for which choices. */
export const actionKey = (action: RunAction, choices: CompareChoices) =>
  JSON.stringify([action, choicesKey(choices)]);

/**
 * What a footer says of its last action for the choices now: whether
 * `action` is starting, whatever the choices became meanwhile, and its
 * error, which describes the choices it ran with, so any change to them,
 * Reset or other lines included, leaves it behind.
 */
export function actionFeedback(
  state: { busy: boolean; key: string; error: string },
  action: RunAction,
  choices: CompareChoices,
) {
  const [ran, ranWith] = state.key
    ? (JSON.parse(state.key) as [string, string])
    : ["", ""];
  return {
    pending: state.busy && ran === action,
    error: ran === action && ranWith === choicesKey(choices) ? state.error : "",
  };
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
 * models it priced, and those it leaves out for an error. A reused model
 * goes along at no cost.
 */
export function estimateTotal(comparison: Comparison) {
  const priced = comparison.candidates.filter(
    (model) => model.estimate && !model.error,
  );
  const reused = comparison.candidates.filter(
    (model) => model.reused && !model.error,
  );
  return {
    cost: priced.reduce((sum, model) => sum + model.estimate!.cost, 0),
    priced: priced.length + reused.length,
    /** The models it sends requests for. */
    sent: priced.length,
    left: comparison.candidates.filter(
      (model) => !priced.includes(model) && !reused.includes(model),
    ),
  };
}

/**
 * What the footer offers for the choices' newest comparison: Translate
 * at the price an unused estimate found, the translation running, or an
 * estimate, again once these choices were translated or when the newest
 * estimate priced no model, with why. Whether an estimate was used comes
 * from the saved comparisons, which hold its translation once it starts.
 */
export function runStep(
  latest: Comparison | undefined,
  shown: Comparison | undefined,
):
  | { step: "translate"; cost: number; sent: number; left: string[] }
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
        sent: total!.sent,
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

/** A string's FNV-1a hash, the seed of a line's order. */
function hash(text: string) {
  let value = 0x811c9dc5;
  for (let index = 0; index < text.length; index++) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 0x01000193);
  }
  return value >>> 0;
}

/**
 * The order a line shows its models' translations in while names are
 * hidden: shuffled for each line on its own, so a model's side on one line
 * tells nothing of its side on the next, and seeded by the comparison and
 * the line, so it stays the same across renders, revisits and restarts.
 * Models without a translation of the line come last, so its empty places
 * sit at its end.
 */
export function lineOrder(comparison: Comparison, row: CompareRow) {
  let seed = hash(`${comparison.id}\n${row.id}`);
  // mulberry32: a small generator whose sequence the seed alone decides.
  const next = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value ^= value + Math.imul(value ^ (value >>> 7), 61 | value);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
  const order = comparison.candidates.map((_, index) => index);
  for (let index = order.length - 1; index > 0; index--) {
    const other = Math.floor(next() * (index + 1));
    [order[index], order[other]] = [order[other], order[index]];
  }
  const has = (position: number) => !!row.translations[position];
  return [...order.filter(has), ...order.filter((place) => !has(place))];
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
 * Whether a comparison of several models hides their names: from the moment
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

/** A translation's picks and whether its names are hidden. */
export type CompareMarks = {
  marks: Record<string, number>;
  blind: boolean;
  revealed: boolean;
};

/** A translation's picks and Blind, from the moment it starts: those saved
 * here ahead of the next read, keyed by translation, or those read. */
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

/** Whether a model was left out of a comparison before anything was sent,
 * such as for having no price, which its column says as a warning with the
 * fix rather than as a failure. */
export const leftOut = (model: CompareModel) =>
  !!model.error && !model.estimate && !model.reused && model.cost === undefined;

const counted = (count: number, one: string, many: string) =>
  count === 1 ? `A model ${one}` : `${count} models ${many}`;

/**
 * What the one header over hidden names says of the models without lines,
 * counted, so it never tells which: those stopped, those left out before
 * anything was sent, as a warning, and those that failed, without their
 * error's words, which may name the model in any spelling.
 */
export function hiddenNotes(comparison: Comparison) {
  const stopped = comparison.candidates.filter((model) => model.stopped);
  const rest = comparison.candidates.filter(
    (model) => model.error && !model.stopped,
  );
  const left = rest.filter(leftOut).length;
  const failed = rest.length - left;
  const why = "Why shows once the names are revealed.";
  return {
    detail: stopped.length
      ? counted(
          stopped.length,
          "stopped before it finished",
          "stopped before they finished",
        )
      : undefined,
    warning: left
      ? `${counted(left, "was left out: it couldn’t be estimated.", "were left out: they couldn’t be estimated.")} ${why}`
      : undefined,
    error: failed
      ? `${counted(failed, "didn’t finish.", "didn’t finish.")} ${why}`
      : undefined,
  };
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

const actions = ["compare_estimate", "compare_translate"];

/** Whether an operation is a comparison's, which Compare shows. */
export const isComparison = (action: string | null | undefined) =>
  actions.includes(action || "");

/** An operation as another page's operation row shows it: a comparison
 * reads "Running a comparison on Compare models", never with its message,
 * which names the model it is at, so a blind comparison's stay hidden. */
export const shownOperation = <
  T extends { action?: string | null; message: string },
>(
  job: T,
): T =>
  isComparison(job.action)
    ? { ...job, message: "a comparison on Compare models" }
    : job;

/** What a running comparison does, without its message, which names the
 * model it is at, so a blind comparison's names stay hidden on every page. */
export const comparisonText = (action: string | null | undefined) =>
  action === "compare_translate"
    ? "Translating a comparison"
    : "Estimating a comparison";

/** The open game's comparison operations, as the observed state follows
 * them. */
export function compareOperations(
  snapshot: WorkspaceSnapshot | null | undefined,
  projectId: string,
) {
  return (
    snapshot?.application.project?.id === projectId
      ? (snapshot.compareOperations ?? [])
      : []
  ).filter((job) => isComparison(job.action));
}

/**
 * The comparison running for the game, whichever choices it was started
 * from, and what a page that can't show its own status says of it: what it
 * does, and that other work waits for it, as the app runs one at a time.
 */
export function runningComparison(operations: readonly CompareOperation[]) {
  const operation = operations.find((item) => working(item.status));
  if (!operation) return null;
  return {
    operation,
    text: comparisonText(operation.action),
    waits: "Most other work waits until it ends.",
  };
}

const plural = (count: number, word: string) =>
  `${count.toLocaleString()} ${word}${count === 1 ? "" : "s"}`;

/**
 * The footer's one status line while a comparison runs, which takes the
 * place of Estimate and Translate beside its Stop: what it does with the
 * choices on screen when it is theirs (`own`), the comparison it runs from
 * a page whose choices changed since otherwise. It never names a model, so
 * a blind comparison's names stay hidden.
 */
export function runningStatus(
  action: CompareOperation["action"],
  own: Comparison | undefined,
  /** Whether its names are hidden: then how many models it sends would
   * tell which columns it reuses. */
  hidden = false,
) {
  const doing = action === "compare_translate" ? "Translating" : "Estimating";
  if (!own) return `${doing} an earlier set of models…`;
  // A translation sends only the models it neither reuses nor left out.
  const models =
    action === "compare_translate"
      ? own.candidates.filter((model) => !model.reused && !leftOut(model))
          .length
      : own.candidates.length;
  const lines = own.rows.length ? plural(own.rows.length, "line") : "the lines";
  if (hidden) return `${doing} ${lines}…`;
  if (!models) return "Bringing back the earlier lines…";
  return `${doing} ${lines} with ${plural(models, "model")}…`;
}

/** Whether the sidebar offers Compare for the open game: while its folder
 * is there, or while its comparison runs, which with the folder missing
 * only Compare can stop. */
export const compareOffered = (
  project: Pick<Project, "id" | "available">,
  snapshot: WorkspaceSnapshot | null | undefined,
) =>
  !!project.available ||
  !!runningComparison(compareOperations(snapshot, project.id));

/** Whether the footer reports its latest comparison's run beside Estimate:
 * once it failed; a stop shows once, in the columns of the models it
 * stopped, and while one runs the footer's status line says so instead. */
export const reportsRun = (latest: Comparison | undefined) =>
  !!latest &&
  !["complete", "stopped"].includes(latest.status) &&
  !working(latest.status);

export type RunningComparison = NonNullable<
  ReturnType<typeof runningComparison>
>;

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
 * then what it cost and how long it took; a reused one says so, since an
 * earlier run paid for its lines. */
export function modelDetail(model: CompareModel, translated: boolean) {
  if (translated && model.cost !== undefined)
    return [
      formatCost(model.cost),
      model.seconds !== undefined && formatDuration(model.seconds, true),
      model.reused && "reused",
    ]
      .filter(Boolean)
      .join(" · ");
  if (model.reused) return "Reused, no new cost";
  return model.estimate ? `about ${formatCost(model.estimate.cost)}` : "";
}

/** What a column sends besides its model, in a few words: the game's
 * settings, or what it changed. */
export function columnSummary(choice: CompareChoice) {
  const changed = [
    choice.effort !== undefined &&
      `${choice.effort ? choice.effort[0].toUpperCase() + choice.effort.slice(1) : "Default"} effort`,
    choice.glossary !== undefined && "test glossary",
    choice.instruction && "instruction",
  ].filter(Boolean) as string[];
  if (!changed.length) return "Game’s settings";
  const text = changed.join(" · ");
  return text[0].toUpperCase() + text.slice(1);
}

/**
 * What the footer offers once the choices' lines are translated: Use, as
 * the one primary, for one column that finished, or for several once every
 * line has a pick and one model leads; nothing while picking or tied. A
 * model that failed or stopped offers Estimate again, which reuses the
 * finished ones.
 */
export function nextStep(
  comparison: Comparison,
  score: ReturnType<typeof picks> | null,
) {
  const models = comparison.candidates;
  const winner =
    models.length === 1
      ? models[0]
      : score && score.total > 0 && score.picked === score.total
        ? score.winner === null
          ? undefined
          : models[score.winner]
        : undefined;
  return {
    use:
      winner?.finished && !working(comparison.status)
        ? {
            model: winner,
            label: models.length === 1 ? "Use this model" : "Use most picked",
          }
        : null,
    again:
      !working(comparison.status) &&
      models.some((model) => !model.finished && !leftOut(model)),
  };
}

/**
 * What a game's comparable lines and Tune's guidance come from, as the
 * observed state shows it: its method, its Guided preparation, the Manual
 * file loaded, the newest Assistant-led run, whose organize made the groups,
 * Start over, and the glossary and game context Context saves. Each change
 * reads the comparisons again.
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
    ...[guided?.documents, translation?.documents].flatMap((documents) => [
      documents?.glossary?.revision ?? null,
      documents?.game?.revision ?? null,
    ]),
  ]);
}

/**
 * The key a page's read follows: the newest while the page shows, and while
 * hidden the last one it read, so a hidden page starts no reads and reads
 * once when it shows again after a change.
 */
export const shownKey = (shown: boolean, key: string, last: string | null) =>
  shown ? key : last;
