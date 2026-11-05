import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type {
  CompareState,
  Comparison,
  EffortLevel,
  Project,
} from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useOnChange } from "../../state/useOnChange";
import type { Observer } from "../../state/useAction";
import { useRead } from "../../state/useRead";
import { unavailableReason } from "../../ui/displayText";
import { Message } from "../../ui/Feedback";
import { Notice } from "../../ui/Notice";
import {
  PageBody,
  PageHeader,
  PageLayout,
  PageMessages,
} from "../../ui/PageLayout";
import { StackedTabPanels, Tabs } from "../../ui/Tabs";
import { onSettingsSaved } from "../settings/settingsChanges";
import { configured } from "./AddModels";
import { compareInputs, Rereads, shownKey } from "./compareView";
import type { ChosenModel } from "./ModelChoice";
import { Single } from "./Single";
import { Tune } from "./Tune";
import { Versus } from "./Versus";

const tabs = [
  { id: "single", label: "Single model" },
  { id: "versus", label: "Model vs model" },
  { id: "tune", label: "Tune settings" },
] as const;
type CompareTab = (typeof tabs)[number]["id"];

const actions = ["compare_estimate", "compare_translate"];

/** What every tab reads: the game's comparisons and the model it uses. */
export type CompareContext = {
  projectId: string;
  state: CompareState;
  /** Newest first, each with its operation's state as observed now. */
  comparisons: Comparison[];
  /** The connection and model Settings translates with. */
  base: ChosenModel | null;
  /** The thinking effort Settings sends that model. */
  baseEffort: EffortLevel | null;
  /** Reads the comparisons again, once shown, ending once they are read. */
  reload: () => Promise<void>;
  /** For an action that changes the comparisons: it finishes once the page
   * has read them again. */
  observer: Observer;
};

/** `key` while the page shows; hidden, the last key it read under. */
function useShownKey(shown: boolean, key: string) {
  const [last, setLast] = useState<string | null>(null);
  const next = shownKey(shown, key, last);
  if (next !== last) setLast(next);
  return next;
}

/**
 * Compare models: a few of this game's lines translated by several models,
 * by one, or by one with changed settings, to choose a model and its
 * settings before translating the game.
 */
export default function Compare({
  project,
  visible,
}: {
  project: Project;
  /** Whether the page shows; hidden, it keeps its place and reads nothing. */
  visible: boolean;
}) {
  const application = useApplication();
  const [tab, setTab] = useState<CompareTab>("versus");
  const operations = (
    application.snapshot?.application.project?.id === project.id
      ? (application.snapshot.compareOperations ?? [])
      : []
  ).filter((job) => actions.includes(job.action || ""));
  // Each start and end of an operation reads the comparisons again; their
  // progress in between comes from the observed operations.
  const ended = operations
    .map((job) => `${job.id}:${job.status}`)
    .sort()
    .join(",");
  const [rereads] = useState(() => new Rereads());
  const [reloads, setReloads] = useState(0);
  const reload = () => {
    const { after, done } = rereads.ask();
    setReloads(after);
    return done;
  };
  // A method change, a newly loaded Manual file or Start over changes the
  // lines too.
  const inputs = compareInputs(application.snapshot, project.id);
  // Hidden, or while its game folder is missing, the page waits to read
  // until it shows the game again.
  const missing = project.available === false;
  const shown = visible && !missing;
  const readKey = useShownKey(
    shown,
    JSON.stringify([project.id, reloads, ended, inputs]),
  );
  const read = useRead(readKey, () => api.compare.state(project.id));
  // The reload a settled read was asked as, which ends the waits for it.
  const settled =
    readKey === null || read.pending
      ? null
      : (JSON.parse(readKey) as [string, number])[1];
  useEffect(() => {
    if (settled !== null) rereads.settled(settled);
  }, [settled, rereads]);
  const [state, setState] = useState<CompareState>();
  useOnChange(read.value, (value) => {
    if (value) setState(value);
  });
  const [settingsReads, setSettingsReads] = useState(0);
  useEffect(() => onSettingsSaved(() => setSettingsReads((n) => n + 1)), []);
  const settings = useRead(
    useShownKey(shown, `settings:${settingsReads}`),
    () => api.settings(),
  );
  const active = settings.value?.connections.find(
    (item) => item.id === settings.value?.activeConnectionId,
  );
  const base =
    active && configured(active) && active.model
      ? {
          connection_id: active.id,
          model: active.model,
          connection: active.name,
        }
      : null;
  const baseEffort =
    (base && settings.value?.modelOptions[base.model]?.thinkingEffort) ?? null;
  const comparisons = (state?.comparisons ?? []).map((item) => {
    const job = operations.find(
      (operation) => operation.id === (item.translationId ?? item.id),
    );
    return job ? { ...item, status: job.status, message: job.message } : item;
  });
  const context: CompareContext | null = state
    ? {
        projectId: project.id,
        state,
        comparisons,
        base,
        baseEffort,
        reload,
        observer: { mark: () => 0, settle: reload },
      }
    : null;
  const error = read.error === undefined ? "" : messageOf(read.error);
  return (
    <PageLayout
      variant="editor"
      className="compare-page"
      aria-label="Compare models"
    >
      <PageHeader
        title="Compare models"
        description="Try models and settings on a few of this game's lines."
      />
      {missing ? (
        // As the other pages say it; Find game folder is on the Project page.
        <PageMessages>
          <Message message={unavailableReason(project)} />
        </PageMessages>
      ) : context && !state?.available ? (
        <PageBody>
          <Notice>{state?.reason}</Notice>
        </PageBody>
      ) : (
        <>
          <div className="frame-row">
            <Tabs
              id="compare"
              label="Compare"
              items={tabs}
              value={tab}
              onChange={setTab}
            />
          </div>
          <PageMessages>
            {error && !state && <Notice tone="warning">{error}</Notice>}
          </PageMessages>
          {!context ? (
            <PageBody>
              <p className="muted" role="status">
                {error ? "" : "Reading this game’s lines…"}
              </p>
            </PageBody>
          ) : (
            <StackedTabPanels
              id="compare"
              value={tab}
              panels={{
                single: <Single context={context} />,
                versus: <Versus context={context} />,
                tune: <Tune context={context} />,
              }}
            />
          )}
        </>
      )}
    </PageLayout>
  );
}
