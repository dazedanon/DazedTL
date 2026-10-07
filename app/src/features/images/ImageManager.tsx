import { PathText } from "../../ui/PathText";
import { FileName } from "../../ui/FileName";
import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ChevronDown,
  Image as ImageIcon,
  MoreHorizontal,
  Search,
} from "lucide-react";
import { displayMarks, imageDisplay } from "../../ui/displayStatus";
import { StatusIcon } from "../../ui/StatusIcon";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import type {
  ImageActionResult,
  ImageAsset,
  ImageDraft,
  ImageManagerState,
  ImagePreview,
} from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { Button } from "../../ui/Button";
import { Menu, MenuItem, MenuSeparator } from "../../ui/Menu";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { useOwnedFeedback } from "../../ui/FeedbackOwners";
import { ActionSlot } from "../../ui/ActionSlot";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { Message } from "../../ui/Feedback";
import {
  imageDraft,
  imageStatus,
  toggleImage,
  virtualRows,
} from "./imageSelection";
import { ThumbnailQueue, useImageGrid, useThumbnail } from "./useImageGrid";
import { ImageCompare } from "./ImageCompare";
import { ImageApply } from "./ImageApply";
import { ImageFolders } from "./ImageFolders";
import { useObserved } from "../../state/useObserved";
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";
import { AssistantTask } from "../../ui/AssistantTask";
import { useHandoff } from "../assistant/useAssistantTasks";

export interface ImageManagerProps {
  projectId: string;
  onOpenEditor: (assetIds: string[]) => void;
  observed?: ImageManagerState | null;
  /**
   * Replaces Review & apply with the host's own review, such as Guided's
   * pending changes, given the selection it would apply.
   */
  applyControl?: (selection: {
    ids: string[];
    ready: number;
    primary: boolean;
    blocked: boolean;
  }) => ReactNode;
  /** The host page's footer slot, which this manager's ActionBar fills. */
  footer: {
    target: HTMLElement | null;
    back?: ReactNode;
    next: (variant: "primary" | "quiet") => ReactNode;
  };
}

export function ImageManager(props: ImageManagerProps) {
  // A revisit starts from the observed state; only a missing one is read.
  const own =
    props.observed?.projectId === props.projectId ? props.observed : null;
  const [start, setStart] = useState(own);
  if (own && start?.projectId !== props.projectId) setStart(own);
  const observed = start?.projectId === props.projectId ? start : null;
  const loaded = useRead(observed ? null : props.projectId, () =>
    imagesApi.state(props.projectId),
  );
  const initial = observed || loaded.value;
  const error = loaded.error === undefined ? "" : messageOf(loaded.error);
  if (!initial || initial.projectId !== props.projectId)
    return (
      <section className="image-manager image-manager-loading">
        <ActionSlot target={props.footer.target}>
          <ActionBar
            feedback={
              <div className="image-footer-context">{props.footer.back}</div>
            }
          >
            {props.footer.next("quiet")}
          </ActionBar>
        </ActionSlot>
        <Message message={error} />
        <p role="status">
          {error
            ? "Image Manager could not load."
            : "Loading saved image work…"}
        </p>
        {error && <Button onClick={loaded.retry}>Retry</Button>}
      </section>
    );
  return <Manager key={props.projectId} {...props} initial={initial} />;
}

function Tile({
  asset,
  selected,
  size,
  queue,
  onSelect,
  onCompare,
}: {
  asset: ImageAsset;
  selected: boolean;
  size: number;
  queue: ThumbnailQueue;
  onSelect: (checked: boolean) => void;
  onCompare: () => void;
}) {
  const pixels = useThumbnail(queue, asset, size);
  const display = imageDisplay(asset);
  // Of the images not started, recommended ones and editable copies are the
  // ones to work on next, so their mark takes the accent.
  const next =
    display === "not_started" &&
    (asset.classification === "recommended" || asset.editable);
  return (
    <article
      className="image-tile"
      data-selected={selected}
      data-state={asset.state}
    >
      <label className="image-tile-select">
        <input
          aria-label={`Select ${asset.filename}`}
          type="checkbox"
          checked={selected}
          onChange={(event) => onSelect(event.target.checked)}
        />
      </label>
      <button
        type="button"
        className="image-tile-preview"
        aria-label={`Compare ${asset.filename}`}
        // Encryption is supported throughout; it is noted, not marked, since a
        // game encrypts all of its images or none.
        title={`${asset.path}\n${imageStatus(asset)}${asset.encrypted ? " · Encrypted" : ""}`}
        onClick={onCompare}
      >
        {pixels ? (
          <img
            src={pixels.url}
            alt=""
            width={pixels.width}
            height={pixels.height}
          />
        ) : (
          <ImageIcon size={24} aria-hidden="true" />
        )}
        <span
          className="image-tile-status"
          data-next={next || undefined}
          aria-label={imageStatus(asset)}
        >
          <StatusIcon status={displayMarks[display]} size={14} />
        </span>
      </button>
      <FileName
        className="image-tile-name"
        name={asset.filename}
        title={asset.path}
      />
    </article>
  );
}

function Manager({
  projectId,
  onOpenEditor,
  initial,
  observed,
  applyControl,
  footer: host,
}: ImageManagerProps & { initial: ImageManagerState }) {
  const [listRevision, setListRevision] = useState(0);
  const [compare, setCompare] = useState<ImageAsset | null>(null);
  const [preview, setPreview] = useState<ImagePreview | null>(null);
  const [folderDialog, setFolderDialog] = useState(false);
  const [imageRoot, setImageRoot] = useState(initial.profile.imageRoot || "");
  const action = useAction();
  const draft = useDraft<ImageDraft>("images:" + projectId, {
    autosave: true,
    initial: { saved: imageDraft(initial) },
    report: action.report,
    persist: async (changes) => {
      const current = images.latest();
      const selectionChanged =
        current.selection.join("\n") !== changes.selection.join("\n");
      images.set(await imagesApi.update(projectId, current.revision, changes));
      if (selectionChanged) setListRevision((value) => value + 1);
    },
  });
  const images = useObserved(
    observed?.projectId === projectId ? observed : null,
    initial,
    {
      hold: draft.dirty || action.busy,
      // Unsaved choices keep their revision; progress and folders stay live.
      merge: (current, next) => ({
        ...current,
        counts: next.counts,
        job: next.job,
        folders: next.folders,
        warnings: next.warnings,
      }),
      onAdopt: (next, previous) => {
        if (next.revision !== previous.revision)
          draft.session.adopt(imageDraft(next));
      },
    },
  );
  const state = images.value;
  // Inventory and report changes reload the visible page and comparison.
  useOnChange(
    JSON.stringify([
      state.inventoryRevision,
      state.observationRevision,
      state.counts.indexed,
      state.editing.lastReport,
      state.discovery.lastReport,
    ]),
    () => setListRevision((value) => value + 1),
  );
  const value = draft.value || imageDraft(state);
  const manual = value.view.workflowMode === "manual";
  const reportCompare = useEffectEvent((error: unknown) =>
    action.report(error, "compare"),
  );
  useEffect(() => {
    if (!value.view.currentImage) return;
    let alive = true;
    void imagesApi
      .list(
        projectId,
        { asset_id: value.view.currentImage, limit: 1 },
        () => alive,
      )
      .then((result) => {
        if (alive && result.items[0]) setCompare(result.items[0]);
      })
      .catch((error: unknown) => {
        if (alive) reportCompare(error);
      });
    return () => {
      alive = false;
    };
  }, [projectId, value.view.currentImage, listRevision]);
  const selection = useMemo(() => new Set(value.selection), [value.selection]);
  const queue = useMemo(() => new ThumbnailQueue(projectId), [projectId]);
  useEffect(() => () => queue.dispose(), [queue]);
  const viewport = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 1000, height: 600 });
  const [scroll, setScroll] = useState(value.view.scroll);
  const savedScroll = useEffectEvent(() => value.view.scroll);
  useLayoutEffect(() => {
    const element = viewport.current;
    if (!element) return;
    element.scrollTop = savedScroll();
    const observer = new ResizeObserver(([entry]) =>
      setDimensions({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const columns = Math.max(
    1,
    Math.floor((dimensions.width - 16) / (value.view.tileSize + 8)),
  );
  const rowHeight = Math.round(value.view.tileSize * 0.68) + 32;
  const [total, setTotal] = useState(state.counts.indexed);
  const range = virtualRows(
    total,
    columns,
    rowHeight,
    scroll,
    dimensions.height,
  );
  const grid = useImageGrid(
    projectId,
    value.view,
    state.inventoryRevision,
    listRevision,
    range.start,
    range.end,
  );
  useOnChange(grid.total, setTotal);
  const change = (patch: Partial<ImageDraft>) =>
    draft.session.edit((current) => ({ ...current, ...patch }));
  const changeView = (patch: Partial<ImageDraft["view"]>, reset = false) => {
    if (reset) {
      setScroll(0);
      if (viewport.current) viewport.current.scrollTop = 0;
    }
    draft.session.edit((current) => ({
      ...current,
      view: { ...current.view, ...patch, ...(reset ? { scroll: 0 } : {}) },
    }));
  };
  const perform = async (
    name: string,
    options: Record<string, unknown> = {},
    notice = "",
  ) => {
    // Only a task that reached the clipboard says it was copied.
    let copied = false;
    const result = await action.run(
      async () => {
        await draft.session.commit(async () => {
          const reply: ImageActionResult = await imagesApi.action(
            projectId,
            name,
            options,
          );
          images.set(reply.state);
          setListRevision((value) => value + 1);
          if (reply.text) {
            await window.dazedtl.copyText(reply.text);
            copied = true;
          }
          if (reply.preview) setPreview(reply.preview);
          if (name === "apply" || name === "restore") setPreview(null);
          return { saved: imageDraft(reply.state) };
        });
      },
      notice,
      name,
    );
    if (result.ok && copied)
      action.succeed(
        "Task copied. Paste into your coding assistant to begin or resume.",
        name,
      );
  };
  const scanNewInventory = useEffectEvent(() => {
    if (
      state.profile.supported &&
      !state.inventoryRevision &&
      !state.counts.indexed &&
      !state.job
    )
      void perform("scan");
  });
  // A project's first visit indexes its images once.
  const initialScan = useRef(false);
  useEffect(() => {
    if (initialScan.current) return;
    initialScan.current = true;
    scanNewInventory();
  }, []);
  const saveFolder = () =>
    action.run(
      async () => {
        await draft.session.commit(async () => {
          images.set(
            await imagesApi.update(projectId, images.latest().revision, {
              imageRoot: imageRoot.trim(),
            }),
          );
          const reply = await imagesApi.action(projectId, "scan");
          images.set(reply.state);
          setListRevision((value) => value + 1);
          setFolderDialog(false);
          return { saved: imageDraft(reply.state) };
        });
      },
      "Image folder saved. Indexing loose PNGs.",
      "image-folder",
    );
  const openCompare = (asset: ImageAsset) => {
    setCompare(asset);
    changeView({ currentImage: asset.id });
    action.clear();
  };
  const counts = state.counts;
  const hidden = Math.max(0, value.selection.length - grid.selectedMatched);
  const folderSearch = !!value.view.folder && !!value.view.query.trim();
  const selectedReady = draft.dirty ? 0 : counts.selectedReady || 0;
  const selectedBlocked = draft.dirty ? 0 : counts.selectedBlocked || 0;
  const selectedNotPrepared = draft.dirty ? 0 : counts.selectedNotPrepared || 0;
  const scopeOptions = {
    scope: value.discoveryScope,
    folders:
      value.discoveryScope === "folders" && value.view.folder
        ? [value.view.folder]
        : [],
    ...(value.discoveryScope === "selected"
      ? { asset_ids: value.selection }
      : {}),
  };
  const scopeMissing =
    value.discoveryScope === "selected"
      ? !value.selection.length
      : value.discoveryScope === "folders" && !value.view.folder;
  const jobRunning =
    !!state.job &&
    ["pending", "running", "stopping"].includes(state.job.status);
  const lastReport = state.editing.lastReport || state.discovery.lastReport;
  const editingTask = useHandoff("image_editing");
  const discoveryTask = useHandoff("image_discovery");
  // A report found on returning to the window and rejected says why first.
  const reportError =
    state.editing.rejected ||
    state.discovery.rejected ||
    state.editing.errors?.[0] ||
    state.discovery.errors?.[0] ||
    "";
  // A dismissed task no longer waits for its report.
  const awaitingResults =
    state.editing.status === "awaiting_results" && !editingTask.dismissed;
  const awaitingFindings =
    state.discovery.status === "awaiting_results" && !discoveryTask.dismissed;
  const copiedAt =
    (awaitingResults && state.editing.copiedAt) ||
    (awaitingFindings && state.discovery.copiedAt) ||
    "";
  const selectedApplied = draft.dirty ? 0 : counts.selectedApplied || 0;
  const allApplied =
    !!value.selection.length && selectedApplied === value.selection.length;
  const primaryAction = allApplied
    ? "next"
    : selectedReady
      ? "preview_apply"
      : selectedNotPrepared
        ? "prepare"
        : value.selection.length
          ? awaitingResults
            ? "refresh_results"
            : "edit_task"
          : awaitingFindings
            ? "refresh_findings"
            : "discovery_task";
  const reportIssues = [
    ...(state.discovery.errors || []),
    ...(state.editing.errors || []),
    ...state.warnings,
  ];
  const activeCompare =
    compare &&
    (grid.items.find(({ asset }) => asset.id === compare.id)?.asset || compare);
  const modeToggle = (
    <Button
      variant="link"
      className="image-mode-toggle"
      disabled={action.busy}
      onClick={() =>
        changeView({ workflowMode: manual ? "discovery" : "manual" })
      }
    >
      {manual ? "Use AI discovery" : "Choose images myself"}
    </Button>
  );
  // Refreshing reads a saved assistant report, so it leads only while one is due.
  const assistantState = reportError
    ? "attention"
    : awaitingResults || awaitingFindings
      ? "waiting"
      : lastReport
        ? "ready"
        : "idle";
  // The selected batch moves through these steps; each reports beside itself.
  const stepKey =
    ["prepare", "edit_task", "preview_apply"].includes(action.key) ||
    (action.key === "refresh_results" && awaitingResults);
  const owned = useOwnedFeedback(action.key);
  const step = (key: string, pendingText: string) => ({
    feedbackKey: key,
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
    onClick: () => void perform(key),
  });
  // One slot walks the selection from editable copies to the image task; it
  // follows the saved counts so the label holds while choices save.
  const prepareFirst = !!counts.selectedNotPrepared;
  const editKey = action.key === "prepare" || action.key === "edit_task";
  const moreMenu = (
    <Menu
      trigger={
        <>
          <MoreHorizontal size={16} aria-hidden="true" />
          More
        </>
      }
      label="Image tools and recovery"
      aria-label="Image tools and recovery"
      disabled={action.busy}
    >
      <MenuItem
        disabled={!value.selection.length}
        onSelect={() => {
          void action.run(
            async () => {
              await draft.session.flush();
              // The editor works on editable copies; images still to be made
              // editable stay selected for Make editable.
              const editable: string[] = [];
              for (let offset = 0, total = 1; offset < total; offset += 500) {
                const page = await imagesApi.list(projectId, {
                  selected_only: true,
                  offset,
                  limit: 500,
                });
                total = page.total;
                for (const item of page.items)
                  if (item.editable) editable.push(item.id);
              }
              if (!editable.length)
                throw new Error("Make the selected images editable first.");
              onOpenEditor(editable);
            },
            "",
            "edit_text",
          );
        }}
      >
        Edit text…
      </MenuItem>
      {!awaitingFindings && (
        <MenuItem
          disabled={jobRunning || state.discovery.status === "idle"}
          onSelect={() => void perform("refresh_findings")}
        >
          Refresh findings
        </MenuItem>
      )}
      {!awaitingResults && (
        <MenuItem
          disabled={jobRunning || state.editing.status === "idle"}
          onSelect={() => void perform("refresh_results")}
        >
          Refresh results
        </MenuItem>
      )}
      <MenuItem onSelect={() => perform("scan")}>Refresh inventory</MenuItem>
      {state.profile.id === "generic" && (
        <MenuItem
          onSelect={() => {
            setImageRoot(state.profile.imageRoot || "");
            setFolderDialog(true);
          }}
        >
          Choose image folder…
        </MenuItem>
      )}
      <MenuSeparator />
      <MenuItem
        disabled={!value.selection.length}
        onSelect={() => perform("preview_restore")}
      >
        Review restore originals…
      </MenuItem>
      <MenuItem
        disabled={!value.selection.length}
        onSelect={() =>
          perform("exclude", {
            asset_ids: value.selection,
            reason: "Excluded from this image translation scope.",
          })
        }
      >
        Exclude selected
      </MenuItem>
      <MenuItem
        disabled={!value.selection.length}
        onSelect={() => perform("include", { asset_ids: value.selection })}
      >
        Include selected again
      </MenuItem>
    </Menu>
  );
  const footer = (
    <ActionBar
      feedback={
        <div className="image-footer-context">
          {host.back}
          {draft.dirty ? (
            <span>Saving choices…</span>
          ) : (
            !!hidden && (
              <span>{hidden.toLocaleString()} selected hidden by filters</span>
            )
          )}
          {!draft.dirty && !!selectedBlocked && (
            <Button
              variant="link"
              onClick={() =>
                changeView({ status: "blocked", showSelected: true }, true)
              }
            >
              {selectedBlocked.toLocaleString()} blocked
            </Button>
          )}
        </div>
      }
    >
      {moreMenu}
      <ActionControl
        label={
          prepareFirst
            ? `Make editable (${(counts.selectedNotPrepared || 0).toLocaleString()})`
            : "Copy image task"
        }
        variant={
          primaryAction === (prepareFirst ? "prepare" : "edit_task")
            ? "primary"
            : "default"
        }
        disabled={
          action.busy ||
          jobRunning ||
          !value.selection.length ||
          (!prepareFirst && draft.dirty)
        }
        disabledReason={value.selection.length ? "" : "Select images first."}
        {...step(
          prepareFirst ? "prepare" : "edit_task",
          prepareFirst ? "Making editable…" : "Copying task…",
        )}
        error={editKey ? action.error : ""}
        notice={editKey ? action.notice : ""}
      />
      {awaitingResults && (
        <ActionControl
          label="Refresh results"
          variant={primaryAction === "refresh_results" ? "primary" : "default"}
          disabled={action.busy || jobRunning}
          {...step("refresh_results", "Reading results…")}
        />
      )}
      {applyControl ? (
        applyControl({
          ids: value.selection,
          ready: selectedReady,
          primary: primaryAction === "preview_apply",
          blocked: action.busy || jobRunning,
        })
      ) : (
        <ActionControl
          label={`Review & apply${selectedReady ? ` (${selectedReady.toLocaleString()})` : ""}`}
          variant={primaryAction === "preview_apply" ? "primary" : "default"}
          disabled={action.busy || jobRunning || !selectedReady}
          disabledReason={
            value.selection.length && !selectedReady
              ? "No selected image is ready."
              : ""
          }
          {...step("preview_apply", "Preparing review…")}
        />
      )}
      {host.next(allApplied ? "primary" : "quiet")}
    </ActionBar>
  );
  return (
    <section className="image-manager" aria-label="Image Manager">
      {!state.profile.supported && (
        <div className="image-profile-issue">
          <span>
            {state.profile.reason ||
              "Choose a folder containing loose PNGs. Archive extraction is not available in Image Manager."}
          </span>
          <Button
            onClick={() => {
              setImageRoot(state.profile.imageRoot || "");
              setFolderDialog(true);
            }}
          >
            Choose image folder
          </Button>
        </div>
      )}
      <AssistantTask
        state={assistantState}
        progress={
          assistantState === "waiting" && copiedAt
            ? `since ${new Date(copiedAt).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}`
            : undefined
        }
        description={
          assistantState === "waiting"
            ? "Results appear on the images as your assistant saves them."
            : assistantState === "attention"
              ? reportError
              : lastReport
                ? `Last saved report ${new Date(lastReport).toLocaleString()}.`
                : manual
                  ? "Your assistant edits the selected copies; its results appear on their tiles."
                  : "Your assistant examines the images in scope and recommends the ones whose text needs translating."
        }
      >
        {!manual && (
          <div className="image-discovery-actions">
            <label>
              Scope
              <select
                aria-label="Discovery scope"
                value={value.discoveryScope}
                onChange={(event) =>
                  change({
                    discoveryScope: event.target
                      .value as ImageDraft["discoveryScope"],
                  })
                }
              >
                <option value="all">All images</option>
                <option value="folders">Current folder</option>
                <option value="selected">Selected images</option>
              </select>
            </label>
            {/* Each discovery step reports its result beside itself. */}
            <ActionControl
              inline
              label="Copy discovery task"
              variant={
                primaryAction === "discovery_task" ? "primary" : "default"
              }
              disabled={
                action.busy || jobRunning || scopeMissing || !counts.indexed
              }
              {...step("discovery_task", "Copying…")}
              onClick={() => void perform("discovery_task", scopeOptions)}
            />
            {awaitingFindings && (
              <ActionControl
                inline
                label="Refresh findings"
                variant={
                  primaryAction === "refresh_findings" ? "primary" : "default"
                }
                disabled={action.busy || jobRunning}
                {...step("refresh_findings", "Reading findings…")}
              />
            )}
            {!!counts.recommended && (
              <ActionControl
                inline
                label={`Use recommendations (${counts.recommended.toLocaleString()})`}
                disabled={action.busy || jobRunning}
                {...step("use_recommendations", "Selecting…")}
                onClick={() =>
                  void perform("use_recommendations", { mode: "add" })
                }
              />
            )}
            {value.discoveryScope === "folders" && (
              <span className="image-scope-context">
                {value.view.folder || "Choose a folder in the browser."}
              </span>
            )}
          </div>
        )}
        <div className="image-discovery-counts">
          {!!counts.examined && (
            <span>{counts.examined.toLocaleString()} examined</span>
          )}
          {!!counts.recommended && (
            <Button
              variant="link"
              onClick={() => changeView({ status: "recommended" }, true)}
            >
              {counts.recommended.toLocaleString()} recommended
            </Button>
          )}
          {!!counts.uncertain && (
            <Button
              variant="link"
              onClick={() => changeView({ status: "uncertain" }, true)}
            >
              {counts.uncertain.toLocaleString()} uncertain
            </Button>
          )}
          {!!counts.notExamined && (
            <Button
              variant="link"
              onClick={() => changeView({ status: "not_examined" }, true)}
            >
              {counts.notExamined.toLocaleString()} not examined
            </Button>
          )}
          {modeToggle}
        </div>
      </AssistantTask>
      <div className="image-browser-toolbar">
        <div className="image-search">
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search images"
            placeholder="Search filenames or paths…"
            maxLength={200}
            value={value.view.query}
            onChange={(event) =>
              changeView({ query: event.target.value }, true)
            }
          />
        </div>
        {/* The same pressed toggle as the translation file list, so the
            narrowed grid always shows why it is narrowed. */}
        <Button
          aria-pressed={value.view.showSelected}
          disabled={!value.selection.length && !value.view.showSelected}
          onClick={() =>
            changeView({ showSelected: !value.view.showSelected }, true)
          }
        >
          Selected only
        </Button>
        <select
          aria-label="Image status"
          value={value.view.status}
          onChange={(event) => changeView({ status: event.target.value }, true)}
        >
          {[
            ["all", "All images"],
            ["recommended", "Recommended"],
            ["uncertain", "Uncertain"],
            ["no_text", "No text found"],
            ["already_english", "Already English"],
            ["not_examined", "Not examined"],
            ["excluded", "Excluded"],
            ["editable", "Editable"],
            ["ready", "Ready to apply"],
            ["blocked", "Blocked"],
            ["applied", "Applied"],
          ].map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <Menu
          trigger={
            value.selection.length ? (
              <>
                {value.selection.length.toLocaleString()} selected
                <ChevronDown size={14} aria-hidden="true" />
              </>
            ) : (
              "Select…"
            )
          }
          label="Bulk image selection"
          align="start"
          disabled={action.busy}
        >
          <MenuItem
            onSelect={() =>
              perform("select_matching", {
                query: value.view.query,
                filter: value.view.status,
                folder: value.view.folder,
                selected_only: value.view.showSelected,
                mode: "add",
              })
            }
          >
            Add matching ({grid.total.toLocaleString()})
          </MenuItem>
          <MenuItem
            onSelect={() =>
              perform("select_matching", {
                query: "",
                filter: "all",
                folder: "",
                mode: "add",
              })
            }
          >
            Select all ({counts.indexed.toLocaleString()})
          </MenuItem>
          <MenuSeparator />
          <MenuItem
            disabled={!value.selection.length}
            onSelect={() => change({ selection: [] })}
          >
            Clear selection
          </MenuItem>
        </Menu>
        <label className="image-size-label">
          Size
          <input
            aria-label="Thumbnail size"
            type="range"
            min={80}
            max={176}
            step={8}
            value={value.view.tileSize}
            onChange={(event) =>
              changeView({ tileSize: Number(event.target.value) })
            }
          />
        </label>
      </div>
      {jobRunning && (
        <div className="image-index-progress" role="status">
          <span>{state.job?.message || "Indexing images…"}</span>
          {state.job?.progress && (
            <progress
              value={state.job.progress.current}
              max={state.job.progress.total || 1}
            />
          )}
          <Button disabled={action.busy} onClick={() => perform("stop_scan")}>
            Stop indexing
          </Button>
        </div>
      )}
      <div className="image-browser">
        <ImageFolders
          folders={state.folders}
          indexed={counts.indexed}
          folder={value.view.folder}
          ready={counts.ready || 0}
          onChoose={(folder) => {
            change({ folders: folder ? [folder] : [] });
            changeView({ folder, showSelected: false }, true);
          }}
          onStatus={(status) => changeView({ status }, true)}
        />
        <div
          className="image-grid-viewport"
          ref={viewport}
          onScroll={(event) => {
            const next = event.currentTarget.scrollTop;
            setScroll(next);
            changeView({ scroll: next });
          }}
          aria-label="Image thumbnails"
          tabIndex={0}
        >
          <Message message={grid.error} />
          {!grid.total && !grid.loading ? (
            <div className="image-grid-empty">
              <ImageIcon size={30} />
              <h3>
                {!counts.indexed
                  ? "No images indexed"
                  : folderSearch
                    ? "No matches in this folder"
                    : "No matching images"}
              </h3>
              {/* A search inside a folder looks only there, which the grid
                  alone does not show. */}
              {(!counts.indexed || folderSearch || hidden > 0) && (
                <p>
                  {!counts.indexed
                    ? "Index the image library to begin discovery or choose images yourself."
                    : folderSearch
                      ? `The search looks only in ${value.view.folder}.`
                      : `${hidden.toLocaleString()} selected ${hidden === 1 ? "image stays" : "images stay"} selected.`}
                </p>
              )}
              <Button
                onClick={() =>
                  !counts.indexed
                    ? perform("scan")
                    : folderSearch
                      ? changeView({ folder: "" }, true)
                      : changeView(
                          {
                            query: "",
                            status: "all",
                            folder: "",
                            showSelected: false,
                          },
                          true,
                        )
                }
              >
                {!counts.indexed
                  ? "Index images"
                  : folderSearch
                    ? "Search all folders"
                    : "Clear filters"}
              </Button>
            </div>
          ) : (
            <div className="image-grid-space" style={{ height: range.height }}>
              <div
                className="image-grid"
                style={{
                  transform: `translateY(${range.top}px)`,
                  gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
                  gridAutoRows: rowHeight,
                }}
              >
                {grid.items.map(({ asset, index }) => (
                  <div
                    key={asset.id}
                    style={{
                      minWidth: 0,
                      display: "flex",
                      gridRow: Math.floor((index - range.start) / columns) + 1,
                      gridColumn: ((index - range.start) % columns) + 1,
                    }}
                  >
                    <Tile
                      asset={asset}
                      selected={selection.has(asset.id)}
                      size={value.view.tileSize}
                      queue={queue}
                      onSelect={(checked) =>
                        change({
                          selection: toggleImage(
                            draft.session.getSnapshot().value!.selection,
                            asset.id,
                            checked,
                          ),
                        })
                      }
                      onCompare={() => openCompare(asset)}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
          {grid.loading && (
            <span className="image-grid-loading" role="status">
              Loading visible images…
            </span>
          )}
        </div>
      </div>
      {/* Other results sit between the images and the footer. */}
      <div className="image-action-feedback">
        <Message
          message={stepKey || owned ? "" : action.error}
          onDismiss={action.clear}
        />
        {!!action.error && draft.dirty && (
          <Button
            pending={action.busy}
            onClick={() =>
              action.run(
                async () => {
                  images.set(await imagesApi.state(projectId));
                  await draft.session.flush();
                },
                "Choices saved.",
                "retry-save",
              )
            }
          >
            Retry saving choices
          </Button>
        )}
        {action.notice && !stepKey && (
          <span role="status">{action.notice}</span>
        )}
        {!!reportIssues.length && (
          <details>
            <summary>{reportIssues.length} image issues</summary>
            {reportIssues.slice(0, 50).map((warning, index) => (
              <p key={index}>{warning}</p>
            ))}
            {reportIssues.length > 50 && (
              <Button
                onClick={() =>
                  void action.run(
                    () => window.dazedtl.copyText(reportIssues.join("\n")),
                    "Issue list copied.",
                    "copy-issues",
                  )
                }
              >
                Copy all {reportIssues.length} issues
              </Button>
            )}
          </details>
        )}
      </div>
      <ActionSlot target={host.target}>{footer}</ActionSlot>
      {activeCompare && (
        <ImageCompare
          projectId={projectId}
          asset={activeCompare}
          busy={action.busy}
          error={action.error}
          notice={action.notice}
          onDismiss={() => {
            setCompare(null);
            changeView({ currentImage: "" });
            action.clear();
          }}
          onAction={perform}
        />
      )}
      {preview && (
        <ImageApply
          preview={preview}
          selected={value.selection.length}
          busy={action.busy}
          error={action.error}
          onDismiss={() => {
            setPreview(null);
            action.clear();
          }}
          onConfirm={() => {
            void perform(
              preview.action.includes("restore") ? "restore" : "apply",
              { token: preview.token },
              preview.action.includes("restore")
                ? "Original images restored."
                : "Reviewed images applied.",
            );
          }}
        />
      )}
      {folderDialog && (
        <Modal
          label="Choose loose image folder"
          size="md"
          className="image-apply-modal"
          dismissible={!action.busy}
          onDismiss={() => {
            setFolderDialog(false);
            action.clear();
          }}
        >
          <DialogHeader
            title="Choose loose image folder"
            description="Enter a folder relative to this game's root. Only loose PNGs are supported; archives must be extracted separately."
          />
          <DialogBody className="image-apply-body">
            <label>
              Image folder
              <input
                aria-label="Loose image folder"
                value={imageRoot}
                onChange={(event) => setImageRoot(event.target.value)}
                maxLength={2000}
                placeholder="assets/images"
              />
            </label>
            <p className="muted">
              Game root: <PathText path={state.source} wrap />
            </p>
          </DialogBody>
          <ActionBar feedback={<Message message={action.error} />}>
            <Button
              disabled={action.busy}
              onClick={() => {
                setFolderDialog(false);
                action.clear();
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!imageRoot.trim() || jobRunning}
              pending={action.busy && action.key === "image-folder"}
              onClick={saveFolder}
            >
              Save &amp; index images
            </Button>
          </ActionBar>
        </Modal>
      )}
    </section>
  );
}
