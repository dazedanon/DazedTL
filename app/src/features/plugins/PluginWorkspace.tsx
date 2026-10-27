import { useEffect, useEffectEvent, useState, type ReactNode } from "react";
import { TriangleAlert } from "lucide-react";
import { useApplication } from "../../app/ApplicationProvider";
import { useLanguages } from "../../app/LanguagesProvider";
import { pluginsApi } from "../../api/plugins";
import type {
  PluginActionResult,
  PluginForeignWork,
  PluginPreview,
  PluginReceipt,
  PluginState,
} from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useObserved } from "../../state/useObserved";
import { type Handoff, sinceLabel } from "../assistant/assistantTasks";
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
import { plural, selectionNames } from "../../ui/displayText";
import {
  pluginFilesBlocked,
  pluginFilesLeft,
  pluginTaskState,
  recoveryRows,
} from "./pluginTask";

const fileCount = (count: number, noun = "file") => plural(count, noun);
const labelCount = (count: number) => fileCount(count, "label");
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
/** What holds the game's text: VX Ace's Ruby scripts or MV/MZ plugins. */
const nouns = (scripts = false) =>
  scripts
    ? { one: "script", file: "script", title: "Script" }
    : { one: "plugin", file: "plugin file", title: "Plugin" };
type Nouns = ReturnType<typeof nouns>;
/** Actions whose own control shows their result. */
const controlled = (key: string) =>
  [
    "plugin_task",
    "apply",
    "restore",
    "adopt",
    "start_over",
    "keep_unreadable",
  ].includes(key) ||
  key.startsWith("preview_restore:") ||
  key.startsWith("undo:");

/**
 * Each file left unchanged with why, one sentence per reason:
 * "OldTool.js stays unchanged. Plugin files must be UTF-8 text."
 */
function unchangedDetail(
  rows: { path: string; reason: string }[],
  kept = false,
) {
  const reasons = new Map<string, string[]>();
  for (const row of rows)
    reasons.set(row.reason, [...(reasons.get(row.reason) || []), row.path]);
  return [...reasons]
    .map(([reason, paths]) => {
      const names = selectionNames(paths.map(fileName));
      return kept
        ? `You kept ${names} unchanged. ${reason}`
        : `${names} ${paths.length === 1 ? "stays" : "stay"} unchanged. ${reason}`;
    })
    .join(" ");
}
const unreadableDetail = (rows: PluginState["unreadable"], kept: boolean) =>
  unchangedDetail(
    rows.map(({ path, issue }) => ({ path, reason: issue })),
    kept,
  );
/** What an apply that left checked files unchanged wrote, and why it left them. */
const partlyApplied = (
  { completed = 0, blocked = [] }: PluginActionResult,
  words: Nouns,
) => `${fileCount(completed, words.file)} applied. ${unchangedDetail(blocked)}`;

/** Where the assistant's task stands and each result it returns. */
function pluginTask(
  state: PluginState,
  handoff: Handoff,
  keep: ReactNode,
  source: string,
) {
  const { counts } = state;
  const words = nouns(state.scripts);
  const { waiting } = handoff;
  const left = pluginFilesLeft(state);
  const investigating = !state.scanned || counts.investigated < counts.files;
  const taskState: AssistantTaskState = pluginTaskState(state, handoff);
  const blocked = pluginFilesBlocked(state);
  const kept = state.unreadable.filter((row) => row.kept);
  // Files kept unchanged were never read, so "no plugin" means none read.
  const readable = kept.length ? "readable " : "";
  // A result redone because the game changed reads Outdated, not new.
  const idle: DisplayState =
    taskState === "outdated" ? "outdated" : "not_started";
  // Work left with no request out, beside files ready to apply or in
  // progress adopted from another project.
  const filesUnfinished =
    left > 0 && (counts.investigated > 0 || counts.translated > 0)
      ? ` ${fileCount(left)} still ${left === 1 ? "needs" : "need"} your assistant; copy the task again to continue.`
      : "";
  // Labels from Text QA's latest capture that only this task can shorten.
  const handed = state.labels.filter((row) => row.state !== "elsewhere");
  const labelsLeft = counts.labels;
  const unfinished =
    filesUnfinished +
    (!labelsLeft
      ? ""
      : filesUnfinished
        ? ` Text QA also found ${labelCount(labelsLeft)} too long for the screen.`
        : ` Text QA found ${labelCount(labelsLeft)} too long for the screen; copy the task so your assistant shortens ${labelsLeft === 1 ? "it" : "them"}.`);
  const description =
    taskState === "waiting"
      ? `Results appear here as your assistant saves them. It continues through every ${words.file} on its own.`
      : taskState === "ready"
        ? `${fileCount(counts.ready)} checked and ready to apply.${unfinished}`
        : taskState === "outdated"
          ? `${fileCount(left)} changed since your assistant finished. Copy the task again to update ${left === 1 ? "it" : "them"}.`
          : taskState === "blocked"
            ? `Every readable ${words.file} is done. Fix the unreadable ${blocked.length === 1 ? "file, or keep it" : "files, or keep them"} unchanged.`
            : taskState === "applied"
              ? `${fileCount(counts.applied)} applied to the game.`
              : taskState === "done"
                ? counts.textFiles
                  ? `${words.title} text is checked; nothing needed changing.`
                  : counts.files
                    ? `No ${readable}${words.one} shows its ${source} text to players.`
                    : `No ${readable}${words.one} holds ${source} text.`
                : unfinished.trim() ||
                  `Your assistant finds the text ${words.one}s show to players and translates it with the game's glossary, translated text and reference games. The app checks every change before you apply it.`;
  const findings: DisplayState = !investigating
    ? "done"
    : waiting
      ? "waiting"
      : idle;
  // Before any text is found there is no translation to be out of date.
  // A file whose translation is in the game, where only shortened labels
  // wait, reads applied here and ready in the labels row.
  const translation: DisplayState = !counts.textFiles
    ? investigating
      ? "not_started"
      : "skipped"
    : counts.translated < counts.textFiles
      ? waiting && !investigating
        ? "waiting"
        : idle
      : counts.ready > counts.shortened
        ? "ready"
        : counts.applied || counts.shortened
          ? "applied"
          : "done";
  const results: AssistantResult[] = [
    {
      id: "findings",
      title: "Text players see",
      state: findings,
      detail: !state.scanned
        ? `Which ${words.one} text players see.`
        : investigating
          ? `${counts.investigated} of ${fileCount(counts.files)} checked`
          : counts.textFiles
            ? `Found in ${fileCount(counts.textFiles)}`
            : "None found",
    },
    {
      id: "translation",
      title: `Translated ${words.one} text`,
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
  if (handed.length) {
    const count = (stands: string) =>
      handed.filter((row) => row.state === stands).length;
    const shortened = count("ready") + count("applied");
    const kept = count("kept");
    results.push({
      id: "labels",
      title: "Labels too long for the screen",
      state: labelsLeft
        ? waiting
          ? "waiting"
          : "not_started"
        : count("ready")
          ? "ready"
          : shortened
            ? "applied"
            : "done",
      detail: labelsLeft
        ? labelsLeft === handed.length
          ? `${labelCount(labelsLeft)} from Text QA`
          : `${labelsLeft} of ${labelCount(handed.length)} from Text QA left`
        : [
            shortened ? `${shortened} shortened` : "",
            kept ? `${kept} kept as ${kept === 1 ? "it is" : "they are"}` : "",
          ]
            .filter(Boolean)
            .join(", "),
    });
  }
  if (blocked.length)
    results.push({
      id: "unreadable",
      title: blocked.length === 1 ? "Unreadable file" : "Unreadable files",
      state: "blocked",
      detail: unreadableDetail(blocked, false),
      action: keep,
    });
  if (kept.length)
    results.push({
      id: "kept",
      title: kept.length === 1 ? "Unreadable file" : "Unreadable files",
      state: "skipped",
      detail: unreadableDetail(kept, true),
    });
  return { taskState, description, results, words };
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
  disabled?: boolean;
}) {
  const application = useApplication();
  const languages = useLanguages();
  const action = useAction({ observer: application });
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
  // The assistant's checks are the review: a list of files could not show
  // what changed. Once everything is in, the task itself reads Applied; a
  // file left unchanged keeps the control, which says why.
  const apply = async () => {
    const result = await run("apply");
    if (result.ok && result.value.blocked?.length)
      action.report(
        partlyApplied(result.value, nouns(state?.scripts)),
        "apply",
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
          title={`${nouns(state?.scripts).title} work from another project`}
          work={foreignWork}
          counts={[
            [foreignWork.investigated, "files investigated"],
            [foreignWork.translated, "translated"],
            [foreignWork.applied, "applied"],
          ]}
          kept={["findings", "working copies"]}
          noun="files"
          next={`Copy the ${nouns(state?.scripts).one} task again before applying more: tasks copied in the other project aren't accepted here.`}
          left={
            foreignWork.applied
              ? `Applied ${nouns(state?.scripts).file}s stay in the game but can't be restored here.`
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
        <Message message={error || "Loading saved work…"} />
        {footer(null, next("quiet"))}
      </>
    );
  if (!state.supported)
    return (
      <section className="plugin-workspace">
        <Message message={state.limitation} />
        {footer(null, next("primary"))}
      </section>
    );
  const counts = state.counts;
  const keep = (
    <ActionControl
      label="Keep unchanged"
      disabled={busy}
      {...feedback("keep_unreadable")}
      pendingText="Keeping…"
      onClick={() =>
        run("keep_unreadable", {
          paths: pluginFilesBlocked(state).map((row) => row.path),
        })
      }
    />
  );
  const task = pluginTask(state, handoff, keep, languages.source);
  const { words } = task;
  const copied = feedback("plugin_task");
  // Nothing is left for the assistant; an unreadable file needs a fix
  // outside the app.
  const finished = ["done", "applied", "blocked"].includes(task.taskState);
  return (
    <section className="plugin-workspace" aria-label="Plugin files workspace">
      <AssistantTask
        state={task.taskState}
        progress={
          task.taskState === "waiting" ? sinceLabel(handoff.since) : undefined
        }
        help={
          state.scripts
            ? "Keep DazedTL open while your assistant works. It investigates every script, translates the text players see and asks only about choices it can't settle. Copying the task again once it is done has your assistant recheck its decisions, for example after you find untranslated script text in the game."
            : "Keep DazedTL open while your assistant works. It investigates every plugin file, translates the text players see, shortens plugin labels Text QA found too long for the screen and asks only about choices it can't settle. Copying the task again once it is done has your assistant recheck its decisions, for example after you find untranslated plugin text in the game."
        }
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
        ["restore", "adopt", "start_over"].includes(action.key) &&
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
            label={`Copy ${words.one} task`}
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
          {counts.ready > 0 && (
            <ActionControl
              label="Apply to game"
              variant="primary"
              disabled={busy}
              pendingText="Applying…"
              {...feedback("apply")}
              onClick={apply}
            />
          )}
          {next(finished ? "primary" : "quiet")}
        </>,
      )}
      {recovery && (
        <Modal
          label={`${words.title} recovery`}
          size="md"
          className="plugin-review-modal"
          onDismiss={() => setRecovery(false)}
        >
          <DialogHeader
            title={`${words.title} recovery`}
            description={`Undo an application to put its ${words.file}s back as they were before it.`}
            onClose={() => setRecovery(false)}
          />
          <DialogBody className="plugin-review-body">
            <ActionList>
              {recoveryRows(state.receipts).map(({ application, latest }) => {
                const receipt = latest;
                // Taken out since, here or from Checkpoints.
                const undone = !!receipt.restores;
                const problem = [
                  receipt.failure,
                  ...receipt.conflicts,
                  receipt.restoreIssue,
                ]
                  .filter(Boolean)
                  .join(" · ");
                const saved = new Date(receipt.saved).toLocaleString();
                return (
                  <ActionRow
                    key={application.id}
                    title={receiptTitle(undone ? application : receipt)}
                    description={
                      <>
                        {[
                          undone ? `Undone ${saved}` : saved,
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
                    {undone ? null : receipt.restorable && receipt.undo ? (
                      <ActionControl
                        label="Undo"
                        pendingText="Undoing…"
                        disabled={busy}
                        {...feedback("undo:" + receipt.id)}
                        onClick={() =>
                          void run(
                            "undo",
                            { receipt: receipt.id },
                            "",
                            "undo:" + receipt.id,
                          )
                        }
                      />
                    ) : (
                      receipt.restorable && (
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
                      )
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
          label={`Restore ${words.file}s`}
          size="md"
          className="plugin-review-modal"
          dismissible={!action.busy}
          onDismiss={() => setPreview(null)}
        >
          <DialogHeader
            title={`Restore ${fileCount(preview.files.length, words.file)}`}
            description="Each file is checked again before its saved backup replaces it."
          />
          <DialogBody className="plugin-review-body">
            <div className="plugin-review-table">
              <table>
                <thead>
                  <tr>
                    <th>Game file</th>
                    <th>Text changes</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.files.map((file) => (
                    <tr key={file.path}>
                      <td>{file.destination}</td>
                      <td>{file.changes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!!preview.blocked.length && (
              <details open>
                <summary>Files left unchanged</summary>
                {preview.blocked.map((file) => (
                  <p key={file.path}>
                    <strong>{file.path}</strong> · {file.reason}
                  </p>
                ))}
              </details>
            )}
            <Message message={action.key === "restore" ? action.error : ""} />
          </DialogBody>
          <ActionBar feedback={null}>
            <Button disabled={action.busy} onClick={() => setPreview(null)}>
              Cancel
            </Button>
            <ActionControl
              variant="primary"
              label={`Restore ${fileCount(preview.files.length, words.file)}`}
              disabled={busy || !preview.files.length}
              {...feedback("restore")}
              onClick={async () => {
                const result = await run(
                  "restore",
                  { token: preview.token },
                  `Reviewed ${words.file}s restored.`,
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
