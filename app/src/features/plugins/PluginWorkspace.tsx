import { useEffect, useEffectEvent, useState, type ReactNode } from "react";
import { TriangleAlert } from "lucide-react";
import { useApplication } from "../../app/ApplicationProvider";
import { pluginsApi } from "../../api/plugins";
import type {
  PluginForeignWork,
  PluginPreview,
  PluginReceipt,
  PluginState,
} from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useObserved } from "../../state/useObserved";
import { sinceLabel } from "../assistant/assistantTasks";
import { useHandoff } from "../assistant/useAssistantTasks";
import { Button } from "../../ui/Button";
import { ActionControl } from "../../ui/ActionControl";
import { ActionBar } from "../../ui/ActionBar";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { ActionSlot } from "../../ui/ActionSlot";
import {
  AssistantTask,
  type AssistantResult,
  type AssistantTaskState,
} from "../../ui/AssistantTask";
import type { DisplayState } from "../../ui/displayStatus";
import { Message } from "../../ui/Feedback";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { ForeignWork } from "../../ui/ForeignWork";
import { Modal } from "../../ui/Modal";
import { selectionNames } from "../../ui/displayText";
import { PluginApplyContent } from "./PluginApplyContent";
import { pluginFilesLeft } from "./pluginTask";

const fileCount = (count: number, noun = "file") =>
  `${count} ${noun}${count === 1 ? "" : "s"}`;
/** What a receipt did, in words; its backend status codes stay internal. */
const receiptTitle = ({ mode, status, files }: PluginReceipt) => {
  const done = mode === "apply" ? "Applied" : "Restored";
  const action = mode === "apply" ? "Apply" : "Restore";
  const count = fileCount(files.length);
  return status === "partial"
    ? `Partly ${done.toLowerCase()} · ${count}`
    : status === "rolled_back"
      ? `${action} rolled back`
      : status === "recovered"
        ? `${done} ${count} after an interruption`
        : status === "conflict"
          ? `${action} interrupted · needs review`
          : `${done} ${count}`;
};
const fileName = (path: string) => path.split("/").pop() || path;
/** Actions whose own control shows their result. */
const controlled = (key: string) =>
  [
    "plugin_task",
    "preview_apply",
    "apply",
    "restore",
    "adopt",
    "start_over",
  ].includes(key) || key.startsWith("preview_restore:");

/** Where the assistant's task stands and each result it returns. */
function pluginTask(state: PluginState, waiting: boolean) {
  const { counts } = state;
  const left = pluginFilesLeft(state);
  const investigating = !state.scanned || counts.investigated < counts.files;
  const taskState: AssistantTaskState = waiting
    ? "waiting"
    : counts.ready
      ? "ready"
      : investigating || left
        ? "not_started"
        : counts.applied
          ? "applied"
          : "done";
  // Work left with no request out: the assistant stopped, or a game file
  // changed after it finished.
  const unfinished =
    left > 0 && (counts.investigated > 0 || counts.translated > 0)
      ? ` ${fileCount(left)} still ${left === 1 ? "needs" : "need"} your assistant; copy the task again to continue.`
      : "";
  const description =
    taskState === "waiting"
      ? "Results appear here as your assistant saves them. It continues through every plugin file on its own."
      : taskState === "ready"
        ? `${fileCount(counts.ready)} translated and checked, ready to apply.${unfinished}`
        : taskState === "applied"
          ? `${fileCount(counts.applied)} applied to the game.`
          : taskState === "done"
            ? counts.textFiles
              ? "Plugin text is checked; nothing needed changing."
              : counts.files
                ? "No plugin shows its Japanese text to players."
                : "No plugin holds Japanese text."
            : unfinished.trim() ||
              "Your assistant finds the text plugins show to players and translates it with the game's glossary, translated text and reference games. The app checks every change before you apply it.";
  const findings: DisplayState = !investigating
    ? "done"
    : waiting
      ? "waiting"
      : "not_started";
  const translation: DisplayState = !counts.textFiles
    ? investigating
      ? "not_started"
      : "skipped"
    : counts.translated < counts.textFiles
      ? waiting && !investigating
        ? "waiting"
        : "not_started"
      : counts.ready
        ? "ready"
        : counts.applied
          ? "applied"
          : "done";
  const results: AssistantResult[] = [
    {
      id: "findings",
      title: "Text players see",
      state: findings,
      detail: !state.scanned
        ? "Which plugin text players see."
        : investigating
          ? `${counts.investigated} of ${fileCount(counts.files)} checked`
          : counts.textFiles
            ? `Found in ${fileCount(counts.textFiles)}`
            : "None found",
    },
    {
      id: "translation",
      title: "Translated plugin text",
      state: translation,
      // Files with text are still being found while the assistant investigates.
      detail:
        investigating && !counts.translated
          ? "Translations for that text."
          : counts.textFiles
            ? `${counts.translated} of ${fileCount(counts.textFiles)} translated`
            : "Nothing to translate",
    },
  ];
  const unreadable = state.unreadable.length;
  if (unreadable)
    results.push({
      id: "unreadable",
      title: unreadable === 1 ? "Unreadable file" : "Unreadable files",
      state: "blocked",
      detail: `${selectionNames(state.unreadable.map((row) => fileName(row.path)))} ${unreadable === 1 ? "stays" : "stay"} unchanged: ${state.unreadable[0].issue}`,
    });
  return { taskState, description, results };
}

export function PluginWorkspace({
  projectId,
  observed,
  error,
  foreign,
  footerTarget,
  backControl,
  next,
  beforeAction,
  applyControl,
  disabled = false,
}: {
  projectId: string;
  observed?: PluginState | null;
  error?: string;
  /** Plugin work this game folder holds for another project. */
  foreign?: PluginForeignWork;
  footerTarget: HTMLElement | null;
  backControl?: ReactNode;
  /** The host's Continue control; it leads once the task's work is done. */
  next: (variant: "primary" | "quiet") => ReactNode;
  beforeAction: () => Promise<unknown>;
  /** Replaces Review & apply with the host's own review. */
  applyControl?: ReactNode;
  disabled?: boolean;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [copiedRequest, setCopiedRequest] = useState("");
  const [preview, setPreview] = useState<PluginPreview | null>(null);
  const [recovery, setRecovery] = useState(false);
  const handoff = useHandoff("plugins");
  const own = observed?.projectId === projectId ? observed : null;
  const plugins = useObserved(own, own, { hold: action.busy });
  const state = plugins.value;
  // The choice made for saved work stays settled until the snapshot shows it.
  const [settled, setSettled] = useState("");
  const foreignWork =
    foreign && foreign.binding !== settled ? foreign : undefined;
  const report = useEffectEvent((error: unknown) => action.report(error));
  const loadInitial = useEffectEvent((alive: () => boolean) => {
    if (state || foreignWork) return;
    void pluginsApi
      .state(projectId)
      .then((value) => {
        if (alive()) plugins.set(value);
      })
      .catch((error: unknown) => report(error));
  });
  useEffect(() => {
    let alive = true;
    loadInitial(() => alive);
    return () => {
      alive = false;
    };
  }, [projectId]);
  const busy = disabled || action.busy;
  const run = async (
    name: string,
    options: Record<string, unknown> = {},
    notice = "",
    actionKey = name,
  ) =>
    action.run(
      async () => {
        await beforeAction();
        const reply = await pluginsApi.action(projectId, name, options);
        if (reply.state) plugins.set(reply.state);
        if (reply.text) await window.dazedtl.copyText(reply.text);
        if (name === "plugin_task")
          setCopiedRequest(reply.text ? reply.state?.activeRequest || "" : "");
        if (reply.preview) setPreview(reply.preview);
        return reply;
      },
      notice,
      actionKey,
    );
  // A reply with nothing to hand out says why instead.
  const copyTask = async () => {
    const result = await run("plugin_task");
    if (result.ok)
      action.succeed(
        result.value.text
          ? "Task copied. Paste it into your assistant."
          : result.value.message || "",
        "plugin_task",
      );
  };
  const feedback = (key: string) => ({
    pending: action.busy && action.key === key,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  const choose = async (
    choice: "adopt" | "start_over",
    work: PluginForeignWork,
  ) => {
    const result = await action.run(
      async () => {
        const reply = await (choice === "adopt"
          ? pluginsApi.adopt(projectId, work.binding)
          : pluginsApi.startOver(projectId, work.binding));
        if (reply.state) plugins.set(reply.state);
        setSettled(work.binding);
        return reply;
      },
      "",
      choice,
    );
    if (result.ok) action.succeed(result.value.message || "", choice);
  };
  // Every state keeps the host's footer, so it never appears or vanishes.
  const footer = (summary: ReactNode, actions: ReactNode) => (
    <ActionSlot target={footerTarget}>
      <ActionBar
        feedback={
          <div className="plugin-footer-context">
            {backControl}
            {summary}
          </div>
        }
      >
        {actions}
      </ActionBar>
    </ActionSlot>
  );
  if (foreignWork) {
    return (
      <section className="plugin-workspace" aria-label="Plugin files workspace">
        <ForeignWork
          title="Plugin work from another project"
          work={foreignWork}
          counts={[
            [foreignWork.investigated, "files investigated"],
            [foreignWork.translated, "translated"],
            [foreignWork.applied, "applied"],
          ]}
          kept={["findings", "working copies"]}
          noun="files"
          next="Copy the plugin task again before applying more: tasks copied in the other project aren't accepted here."
          left={
            foreignWork.applied
              ? "Applied plugin files stay in the game but can't be restored here."
              : ""
          }
          adopt={
            <ActionControl
              label="Use saved progress"
              variant={foreignWork.blocked ? "default" : "primary"}
              disabled={busy || !!foreignWork.blocked}
              {...feedback("adopt")}
              onClick={() => choose("adopt", foreignWork)}
            />
          }
          startOver={
            <ActionControl
              label="Start over"
              disabled={busy}
              {...feedback("start_over")}
              onClick={() => choose("start_over", foreignWork)}
            />
          }
        />
        {footer(null, next("quiet"))}
      </section>
    );
  }
  if (!state)
    return (
      <>
        <Message message={error || "Loading saved plugin work…"} />
        {footer(null, next("quiet"))}
      </>
    );
  if (!state.supported)
    return (
      <section className="plugin-workspace">
        <Message message={state.limitation} />
        <p className="muted">
          Existing Ruby sources and native packing remain in the preserved
          workflow. This guarded workspace does not claim Ruby publication
          support.
        </p>
        {footer(null, next("primary"))}
      </section>
    );
  const counts = state.counts;
  const task = pluginTask(state, handoff.waiting);
  const copied = feedback("plugin_task");
  const finished = ["done", "applied"].includes(task.taskState);
  return (
    <section className="plugin-workspace" aria-label="Plugin files workspace">
      <AssistantTask
        state={task.taskState}
        progress={
          task.taskState === "waiting" ? sinceLabel(handoff.since) : undefined
        }
        help="Keep DazedTL open while your assistant works. It investigates every plugin file, translates the text players see and asks only about choices it can't settle. Copying the task again once it is done has your assistant recheck its decisions, for example after you find untranslated plugin text in the game."
        description={task.description}
        results={task.results}
      />
      <Message
        message={error || (controlled(action.key) ? "" : action.error)}
      />
      {state.originalIssue && (
        <div className="plugin-prerequisite">
          <TriangleAlert size={15} />
          <span>{state.originalIssue}</span>
        </div>
      )}
      {footer(
        ["apply", "restore", "adopt", "start_over"].includes(action.key) &&
          action.notice && (
            <span role="status" className="plugin-success">
              {action.notice}
            </span>
          ),
        <>
          {!!state.receipts.length && (
            <Button disabled={busy} onClick={() => setRecovery(true)}>
              Recovery
            </Button>
          )}
          <ActionControl
            label="Copy plugin task"
            variant={counts.ready || finished ? "default" : "primary"}
            disabled={busy}
            {...copied}
            // The copied notice lasts until the assistant moves to a newer request.
            notice={
              !copiedRequest || state.activeRequest === copiedRequest
                ? copied.notice
                : ""
            }
            onClick={copyTask}
          />
          {counts.ready > 0 &&
            (applyControl ?? (
              <ActionControl
                label="Review & apply"
                variant="primary"
                disabled={busy}
                {...feedback("preview_apply")}
                onClick={() => run("preview_apply")}
              />
            ))}
          {next(finished ? "primary" : "quiet")}
        </>,
      )}
      {recovery && (
        <Modal
          label="Plugin recovery"
          size="md"
          className="plugin-review-modal"
          onDismiss={() => setRecovery(false)}
        >
          <DialogHeader
            title="Plugin recovery"
            description="Restore plugin files from the backups saved when they were applied."
            onClose={() => setRecovery(false)}
          />
          <DialogBody className="plugin-review-body">
            <ActionList>
              {state.receipts
                .slice()
                .reverse()
                .map((receipt) => {
                  const problem = [
                    receipt.failure,
                    ...receipt.conflicts,
                    receipt.restoreIssue,
                  ]
                    .filter(Boolean)
                    .join(" · ");
                  return (
                    <ActionRow
                      key={receipt.id}
                      title={receiptTitle(receipt)}
                      description={
                        <>
                          {[
                            new Date(receipt.saved).toLocaleString(),
                            selectionNames(
                              receipt.files.map((file) =>
                                fileName(file.destination),
                              ),
                            ),
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                          {problem && (
                            <span className="plugin-receipt-problem">
                              {problem}
                            </span>
                          )}
                        </>
                      }
                    >
                      {receipt.restorable && (
                        <ActionControl
                          label="Review restore"
                          disabled={busy}
                          {...feedback("preview_restore:" + receipt.id)}
                          onClick={async () => {
                            const result = await run(
                              "preview_restore",
                              { receipt: receipt.id },
                              "",
                              "preview_restore:" + receipt.id,
                            );
                            if (result.ok) setRecovery(false);
                          }}
                        />
                      )}
                    </ActionRow>
                  );
                })}
            </ActionList>
          </DialogBody>
        </Modal>
      )}
      {preview && (
        <Modal
          label={
            preview.mode === "apply"
              ? "Apply plugin files"
              : "Restore plugin files"
          }
          size="md"
          className="plugin-review-modal"
          dismissible={!action.busy}
          onDismiss={() => setPreview(null)}
        >
          <DialogHeader
            title={`${preview.mode === "apply" ? "Apply" : "Restore"} ${fileCount(preview.files.length, "plugin file")}`}
            description={
              preview.blocked.length
                ? `${preview.blocked.length} blocked, awaiting or excluded`
                : undefined
            }
          />
          <DialogBody className="plugin-review-body">
            <PluginApplyContent preview={preview} />
            <Message
              message={action.key === preview.mode ? action.error : ""}
            />
          </DialogBody>
          <ActionBar feedback={null}>
            <Button disabled={action.busy} onClick={() => setPreview(null)}>
              Cancel
            </Button>
            <ActionControl
              variant="primary"
              label={`${preview.mode === "apply" ? "Apply" : "Restore"} ${fileCount(preview.files.length, "plugin file")}`}
              disabled={busy || !preview.files.length}
              {...feedback(preview.mode)}
              onClick={async () => {
                const result = await run(
                  preview.mode,
                  { token: preview.token },
                  preview.mode === "apply"
                    ? "Reviewed plugin files applied."
                    : "Reviewed plugin files restored.",
                );
                if (result.ok) setPreview(null);
              }}
            />
          </ActionBar>
        </Modal>
      )}
    </section>
  );
}
