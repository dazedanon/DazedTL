import { useEffect, useEffectEvent, useState, type ReactNode } from "react";
import { FileCode2, Search, TriangleAlert } from "lucide-react";
import { useApplication } from "../../app/ApplicationProvider";
import { pluginsApi } from "../../api/plugins";
import type {
  PluginList,
  PluginPreview,
  PluginState,
  PluginView,
} from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { useObserved } from "../../state/useObserved";
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";
import { Button } from "../../ui/Button";
import { ActionControl } from "../../ui/ActionControl";
import { ActionBar } from "../../ui/ActionBar";
import { ActionSlot } from "../../ui/ActionSlot";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";

const fileCount = (count: number, noun = "file") =>
  `${count} ${noun}${count === 1 ? "" : "s"}`;

export const pluginStatus = (status: string) =>
  ({
    not_investigated: "Not investigated",
    awaiting_report: "Awaiting saved report",
    current: "Current findings",
    partial: "Partial results",
    selected: "Included",
    working_copy: "Working copy",
    needs_revision: "Needs revision",
    not_needed: "Not needed",
    ready: "Ready",
    stale: "Stale source",
    unresolved: "Needs investigation",
    applied: "Applied to game",
    latent: "Inactive / default text",
    available: "Available",
    unchanged: "No changes",
  })[status] || status;
const checks: Record<string, string> = {
  boundaries: "Approved text locations only",
  protectedLookups: "Original lookup values protected",
  structure: "Keys, ordering, types and serialization",
  syntax: "JavaScript / JSON syntax",
  decodedTargets: "Decoded targets match saved results",
  controlTokens: "Interpolation and control codes",
  residual: "Approved scope residual check",
};

export function PluginWorkspace({
  projectId,
  observed,
  error,
  footerTarget,
  backControl,
  continueControl,
  beforeAction,
  disabled = false,
}: {
  projectId: string;
  observed?: PluginState | null;
  error?: string;
  footerTarget: HTMLElement | null;
  backControl?: ReactNode;
  continueControl: ReactNode;
  beforeAction: () => Promise<unknown>;
  disabled?: boolean;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [copiedRequest, setCopiedRequest] = useState("");
  const [list, setList] = useState<PluginList | null>(null);
  const [preview, setPreview] = useState<PluginPreview | null>(null);
  const [manual, setManual] = useState<{
      paths: string[];
      ids?: string[];
    } | null>(null),
    [reason, setReason] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [inspecting, setInspecting] = useState(false),
    [showFiles, setShowFiles] = useState(false);
  const draft = useDraft<PluginView>("plugins-view:" + projectId, {
    autosave: true,
    initial: {
      saved: observed?.view || {
        mode: "scope",
        query: "",
        filter: "all",
        selectedOnly: false,
        currentFile: "",
        offset: 0,
      },
    },
    report: action.report,
    persist: async (view) => {
      const current = plugins.latest();
      if (!current) throw Error("Plugin state is loading.");
      plugins.set(await pluginsApi.update(projectId, current.revision, view));
    },
  });
  const own = observed?.projectId === projectId ? observed : null;
  const plugins = useObserved(own, own, {
    hold: draft.dirty || draft.committing || action.busy,
    onAdopt: (next, previous) => {
      if (next.revision !== previous?.revision) draft.session.adopt(next.view);
    },
  });
  const state = plugins.value;
  const view = draft.value || state?.view;
  const report = useEffectEvent((error: unknown, key = "") =>
    action.report(error, key),
  );
  const loadInitial = useEffectEvent((alive: () => boolean) => {
    if (state) return;
    void pluginsApi
      .state(projectId)
      .then((next) => {
        if (!alive()) return;
        plugins.set(next);
        draft.session.adopt(next.view);
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
  const files = useRead(
    state && view
      ? JSON.stringify([
          projectId,
          state.observationRevision,
          view.query,
          view.filter,
          view.selectedOnly,
          view.offset,
        ])
      : null,
    (signal) =>
      pluginsApi.list(
        projectId,
        {
          query: view!.query,
          filter: view!.filter,
          selected_only: view!.selectedOnly,
          offset: view!.offset,
          limit: 100,
        },
        () => !signal.aborted,
      ),
  );
  // The current page stays visible while the next one loads.
  useOnChange(files.value, (value) => {
    if (value) setList(value);
  });
  const loading = files.pending;
  useEffect(() => {
    if (files.error !== undefined) report(files.error, "list");
  }, [files.error]);
  const selected = useRead(
    view?.currentFile
      ? JSON.stringify([
          projectId,
          view.currentFile,
          state?.observationRevision,
        ])
      : null,
    (signal) =>
      pluginsApi.detail(projectId, view!.currentFile, () => !signal.aborted),
  );
  const detail = selected.value ?? null;
  useEffect(() => {
    if (selected.error !== undefined) report(selected.error, "detail");
  }, [selected.error]);
  const edit = (patch: Partial<PluginView>) =>
    draft.session.edit((current) => ({ ...current, ...patch }));
  const busy = disabled || action.busy || draft.committing;
  const run = async (
    name: string,
    options: Record<string, unknown> = {},
    notice = "",
    actionKey = name,
  ) =>
    action.run(
      async () => {
        await beforeAction();
        let reply: Awaited<ReturnType<typeof pluginsApi.action>> = {};
        await draft.session.commit(async (current) => {
          reply = await pluginsApi.action(projectId, name, options);
          if (reply.state) plugins.set(reply.state);
          if (reply.text) {
            await window.dazedtl.copyText(reply.text);
            setCopiedRequest(reply.state?.activeRequest || "");
          }
          if (reply.preview) setPreview(reply.preview);
          return { saved: reply.state?.view || current };
        });
        return reply;
      },
      notice,
      actionKey,
    );
  const feedback = (key: string) => ({
    pending: action.busy && action.key === key,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  const chooseFile = async (
    path: string,
    selected: boolean,
    latentOnly: boolean,
  ) => {
    if (selected && latentOnly) {
      setReason("");
      setManual({ paths: [path] });
      return;
    }
    await run(
      "select_files",
      { paths: [path], selected },
      selected ? "File scope retained." : "File excluded.",
    );
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
  if (!state || !view)
    return (
      <>
        <Message message={error || "Loading saved plugin work…"} />
        {footer(null, continueControl)}
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
        {footer(null, continueControl)}
      </section>
    );
  const counts = state.counts;
  const selectedHidden = Math.max(
    0,
    counts.selectedFiles - (list?.selectedMatched || 0),
  );
  const investigated = ["current", "partial"].includes(state.findings.status);
  const actionKeys = ["plugin_task", "preview_apply", "apply", "restore"];
  const inspect = (path: string) => {
    edit({ currentFile: path });
    setInspecting(true);
  };
  const taskText =
    state.activeRequest === state.requestPaths.investigation &&
    state.findings.status === "awaiting_report"
      ? "Task ready. Paste it into your agent; it will investigate and continue into translation."
      : state.activeRequest === state.requestPaths.translation &&
          state.editing.status === "awaiting_report"
        ? "Working copies are prepared. Your agent’s saved results appear here after validation."
        : counts.ready
          ? `${fileCount(counts.ready)} checked and ready to apply.`
          : counts.applied
            ? `${fileCount(counts.applied)} applied to the game.`
            : "Investigate plugin text, translate confirmed display text, and check the results in one agent task.";
  return (
    <section className="plugin-workspace" aria-label="Plugin text workspace">
      <ActionList>
        <ActionRow
          label={
            <>
              <strong>Translate plugin text</strong>
              <small>{taskText}</small>
            </>
          }
        >
          <ActionControl
            label="Copy plugin task"
            variant={counts.ready ? "default" : "primary"}
            disabled={busy}
            {...feedback("plugin_task")}
            notice={
              state.activeRequest === copiedRequest
                ? feedback("plugin_task").notice
                : ""
            }
            onClick={() =>
              run(
                "plugin_task",
                {},
                "Task copied. Paste it into your agent; saved progress appears here.",
              )
            }
          />
        </ActionRow>
      </ActionList>
      <Message
        message={
          error ||
          (!actionKeys.includes(action.key) && !inspecting ? action.error : "")
        }
      />
      {state.originalIssue && (
        <div className="plugin-prerequisite">
          <TriangleAlert size={15} />
          <span>{state.originalIssue}</span>
        </div>
      )}
      {investigated && state.findings.status === "partial" && (
        <p className="muted">
          Some investigation remains unresolved. Your agent can continue from
          the same task after resolving the reported issues.
        </p>
      )}
      {!!counts.files && (
        <section className="plugin-files" aria-label="Plugin files">
          <div className="plugin-files-heading">
            <Button
              variant="quiet"
              aria-expanded={showFiles}
              aria-controls="plugin-file-list"
              onClick={() => setShowFiles(!showFiles)}
            >
              {showFiles ? "Hide files" : "Show files & text"}
            </Button>
            <span className="muted">
              {counts.files} files found
              {counts.latent
                ? ` · ${counts.latent} inactive / default locations`
                : ""}
            </span>
          </div>
          {showFiles && (
            <div id="plugin-file-list">
              <div className="plugin-filters">
                <label className="plugin-search">
                  <Search size={15} />
                  <input
                    aria-label="Search plugins"
                    placeholder="Search plugin or file…"
                    value={view.query}
                    onChange={(event) =>
                      edit({ query: event.target.value, offset: 0 })
                    }
                  />
                </label>
                <select
                  aria-label="Plugin status"
                  value={view.filter}
                  onChange={(event) =>
                    edit({ filter: event.target.value, offset: 0 })
                  }
                >
                  {[
                    "all",
                    "ready",
                    "selected",
                    "needs_revision",
                    "latent",
                    "unresolved",
                    "stale",
                    "applied",
                    "not_investigated",
                    "not_needed",
                  ].map((status) => (
                    <option key={status} value={status}>
                      {status === "all" ? "All files" : pluginStatus(status)}
                    </option>
                  ))}
                </select>
                <label className="plugin-selected-filter">
                  <input
                    type="checkbox"
                    checked={view.selectedOnly}
                    onChange={(event) =>
                      edit({ selectedOnly: event.target.checked, offset: 0 })
                    }
                  />
                  Included only
                </label>
              </div>
              <div className="plugin-table-scroll" aria-busy={loading}>
                <table className="plugin-table">
                  <thead>
                    <tr>
                      <th>Plugin / file</th>
                      <th>Text</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list?.items.map((row) => (
                      <tr key={row.path}>
                        <td>
                          <button
                            className="plugin-file"
                            onClick={() => inspect(row.path)}
                          >
                            <FileCode2 size={14} />
                            <span>
                              {row.plugin}
                              <small>{row.path}</small>
                            </span>
                          </button>
                        </td>
                        <td>
                          {row.selected
                            ? `${row.selected} included`
                            : "None included"}
                          {row.uncertain > 0 && (
                            <small className="plugin-warning">
                              {row.uncertain} uncertain
                            </small>
                          )}
                        </td>
                        <td
                          className={`plugin-status plugin-status-${row.status}`}
                        >
                          <span>{pluginStatus(row.status)}</span>
                          {row.manual > 0 && <small>Adjusted by you</small>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!list?.items.length && (
                  <p className="plugin-empty">
                    {loading
                      ? "Loading files…"
                      : "No files match these filters."}
                  </p>
                )}
              </div>
              <div className="plugin-table-count">
                <span>
                  {list?.total.toLocaleString() || 0} matching files
                  {selectedHidden
                    ? ` · ${selectedHidden} included files hidden`
                    : ""}
                </span>
                {(view.offset > 0 || (list?.total || 0) > 100) && (
                  <>
                    <Button
                      disabled={!view.offset}
                      onClick={() =>
                        edit({ offset: Math.max(0, view.offset - 100) })
                      }
                    >
                      Previous
                    </Button>
                    <span>
                      {Math.floor(view.offset / 100) + 1} /{" "}
                      {Math.ceil((list?.total || 0) / 100)}
                    </span>
                    <Button
                      disabled={view.offset + 100 >= (list?.total || 0)}
                      onClick={() => edit({ offset: view.offset + 100 })}
                    >
                      Next
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}
        </section>
      )}
      {footer(
        <div className="plugin-footer-summary">
          <span>
            {counts.ready
              ? `${fileCount(counts.ready)} ready to apply`
              : counts.selected
                ? `${counts.selected} text ${counts.selected === 1 ? "location" : "locations"} in ${fileCount(counts.selectedFiles)} included`
                : counts.applied
                  ? `${fileCount(counts.applied)} applied`
                  : "No plugin translations ready"}
          </span>
          {["apply", "restore"].includes(action.key) && action.notice && (
            <span role="status" className="plugin-success">
              {action.notice}
            </span>
          )}
        </div>,
        <>
          {!!state.receipts.length && (
            <Button disabled={busy} onClick={() => setRecovery(true)}>
              Recovery
            </Button>
          )}
          {counts.ready > 0 && (
            <ActionControl
              label="Review & apply"
              variant="primary"
              disabled={busy}
              {...feedback("preview_apply")}
              onClick={() => run("preview_apply")}
            />
          )}
          {continueControl}
        </>,
      )}
      {inspecting && (
        <Modal
          label="Plugin text details"
          className="plugin-review-modal"
          onDismiss={() => setInspecting(false)}
          dismissible={!action.busy}
        >
          <header>
            <h2>{detail?.plugin || "Plugin text"}</h2>
            <p className="plugin-path">{view.currentFile}</p>
          </header>
          <div className="plugin-review-body">
            <Message
              message={
                ![...actionKeys, "select", "select_files"].includes(action.key)
                  ? action.error
                  : ""
              }
            />
            {!detail ? (
              action.key === "detail" && action.error ? null : (
                <p role="status">Loading text and findings…</p>
              )
            ) : (
              <>
                <div className="plugin-detail-status">
                  <span
                    className={`plugin-status plugin-status-${detail.status}`}
                  >
                    {pluginStatus(detail.status)}
                  </span>
                  <ActionControl
                    label={
                      detail.selected
                        ? "Exclude file"
                        : detail.recommended
                          ? "Include confirmed text"
                          : "Include inactive text"
                    }
                    variant="quiet"
                    disabled={
                      busy ||
                      (!detail.selected &&
                        !detail.recommended &&
                        !detail.latent)
                    }
                    {...feedback("select_files")}
                    onClick={() =>
                      chooseFile(
                        detail.path,
                        !detail.selected,
                        !detail.recommended && !!detail.latent,
                      )
                    }
                  />
                </div>
                {detail.reason && <Message message={detail.reason} />}
                {detail.resultEvidence && <p>{detail.resultEvidence}</p>}
                <Message
                  message={action.key === "select" ? action.error : ""}
                />
                {action.key === "select" && action.notice && (
                  <p role="status" className="plugin-success">
                    {action.notice}
                  </p>
                )}
                {detail.items.map((item) => (
                  <article className="plugin-occurrence" key={item.id}>
                    <div className="plugin-occurrence-heading">
                      <label>
                        <input
                          aria-label={`Include occurrence ${item.id}`}
                          type="checkbox"
                          checked={item.selected}
                          disabled={
                            busy ||
                            item.protected ||
                            !item.finding?.safe ||
                            !["visible", "latent"].includes(
                              item.finding.disposition,
                            )
                          }
                          onChange={(event) => {
                            if (event.target.checked && item.latent) {
                              setReason("");
                              setManual({ paths: [], ids: [item.id] });
                            } else
                              void run(
                                "select",
                                {
                                  ids: [item.id],
                                  selected: event.target.checked,
                                },
                                "Text choice retained.",
                              );
                          }}
                        />
                        <strong>
                          {item.protected
                            ? "Protected"
                            : !item.finding ||
                                item.finding.disposition === "unresolved" ||
                                (["visible", "latent"].includes(
                                  item.finding.disposition,
                                ) &&
                                  !item.finding.safe)
                              ? "Needs investigation"
                              : item.latent
                                ? "Inactive / default text"
                                : item.finding.disposition === "visible"
                                  ? "Display text"
                                  : "Not player-visible"}
                        </strong>
                      </label>
                      <span className="muted">Line {item.line}</span>
                    </div>
                    <p>
                      <span lang="ja">{item.value}</span>
                      {item.target && (
                        <>
                          {" "}
                          → <span>{item.target}</span>
                        </>
                      )}
                    </p>
                    {item.finding && <p>{item.finding.reason}</p>}
                    <details>
                      <summary>
                        Evidence{item.target ? " & changes" : ""}
                      </summary>
                      {item.finding && (
                        <p className="muted">{item.finding.evidence}</p>
                      )}
                      <small className="plugin-path">
                        {item.id}
                        {item.logical.length
                          ? ` · ${JSON.stringify(item.logical)}`
                          : ""}
                      </small>
                      {detail.working && (
                        <div className="plugin-diff">
                          <div>
                            <small>Original</small>
                            <pre>{item.before}</pre>
                          </div>
                          <div>
                            <small>Translation</small>
                            <pre>{item.after}</pre>
                          </div>
                        </div>
                      )}
                    </details>
                  </article>
                ))}
                {detail.total > detail.items.length && (
                  <p className="muted">
                    Showing {detail.items.length} of {detail.total} text
                    locations. The translation task includes every eligible
                    included location.
                  </p>
                )}
                {detail.working && (
                  <details>
                    <summary>Validation checks</summary>
                    <dl className="plugin-checks">
                      {Object.entries(checks).map(([key, label]) => (
                        <div key={key}>
                          <dt>{label}</dt>
                          <dd
                            className={
                              detail.checks[key] ? "plugin-success" : "muted"
                            }
                          >
                            {detail.checks[key] ? "Passed" : "Pending"}
                          </dd>
                        </div>
                      ))}
                      <div>
                        <dt>In-game appearance</dt>
                        <dd>Not verified</dd>
                      </div>
                    </dl>
                  </details>
                )}
              </>
            )}
          </div>
          <footer>
            <Button onClick={() => setInspecting(false)} disabled={action.busy}>
              Close
            </Button>
          </footer>
        </Modal>
      )}
      {manual && (
        <Modal
          label="Include latent plugin text"
          className="plugin-review-modal"
          onDismiss={() => setManual(null)}
          dismissible={!action.busy}
        >
          <header>
            <h2>Include inactive or default-only text</h2>
          </header>
          <div className="plugin-review-body">
            <p>
              These safe display locations are excluded by default. Your scope
              choice is retained with a reason.
            </p>
            <label>
              Reason
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <Message
              message={
                action.key === "select" || action.key === "select_files"
                  ? action.error
                  : ""
              }
            />
          </div>
          <footer>
            <Button disabled={action.busy} onClick={() => setManual(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={action.busy || !reason.trim()}
              onClick={async () => {
                const result = await run(
                  manual.ids ? "select" : "select_files",
                  { ...manual, selected: true, includeLatent: true, reason },
                  "Manual scope retained.",
                );
                if (result.ok) setManual(null);
              }}
            >
              Include safe latent text
            </Button>
          </footer>
        </Modal>
      )}
      {recovery && (
        <Modal
          label="Plugin recovery"
          className="plugin-review-modal"
          onDismiss={() => setRecovery(false)}
        >
          <header>
            <h2>Plugin Apply & recovery</h2>
          </header>
          <div className="plugin-review-body">
            {state.receipts
              .slice()
              .reverse()
              .map((receipt) => (
                <article className="plugin-receipt" key={receipt.id}>
                  <strong>
                    {receipt.mode} · {receipt.status} · {receipt.files.length}{" "}
                    files
                  </strong>
                  <p className="muted">{receipt.saved}</p>
                  {receipt.failure && <Message message={receipt.failure} />}
                  <p>{receipt.conflicts.join(" · ")}</p>
                  <ActionControl
                    label="Review restore"
                    disabled={
                      busy || receipt.mode !== "apply" || !receipt.files.length
                    }
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
                </article>
              ))}
          </div>
          <footer>
            <Button onClick={() => setRecovery(false)}>Close</Button>
          </footer>
        </Modal>
      )}
      {preview && (
        <Modal
          label={
            preview.mode === "apply"
              ? "Apply plugin files"
              : "Restore plugin files"
          }
          className="plugin-review-modal"
          dismissible={!action.busy}
          onDismiss={() => setPreview(null)}
        >
          <header>
            <h2>
              {preview.mode === "apply" ? "Apply" : "Restore"}{" "}
              {fileCount(preview.files.length, "plugin file")}
            </h2>
            <p className="muted">
              {preview.files.length} included · {preview.blocked.length} blocked
              / awaiting and excluded
            </p>
          </header>
          <div className="plugin-review-body">
            <p>
              {preview.mode === "apply"
                ? "Replace these game files with the checked translations. Each file is checked again first, and a backup is saved for recovery."
                : "Restore these game files from their saved backups. Each file is checked again first."}
            </p>
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
            <Message
              message={action.key === preview.mode ? action.error : ""}
            />
          </div>
          <footer>
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
          </footer>
        </Modal>
      )}
    </section>
  );
}
