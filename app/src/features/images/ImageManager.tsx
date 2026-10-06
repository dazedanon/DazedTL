import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  CheckCircle2,
  Circle,
  Image as ImageIcon,
  LockKeyhole,
  MoreHorizontal,
  Pencil,
  Search,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import type {
  ImageActionResult,
  ImageAsset,
  ImageDraft,
  ImageEntryMode,
  ImageManagerState,
  ImagePreview,
} from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { Button } from "../../ui/Button";
import { ActionBar } from "../../ui/ActionBar";
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
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";
import "./images.css";

export interface ImageManagerProps {
  projectId: string;
  onClose: () => void;
  onOpenEditor: (assetIds: string[], mode?: ImageEntryMode) => void;
  observed?: ImageManagerState | null;
  observationKey?: unknown;
  initialMode?: ImageEntryMode;
  backLabel?: string;
}

export function ImageManager(props: ImageManagerProps) {
  const loaded = useRead(props.projectId, () =>
    imagesApi.state(props.projectId),
  );
  const initial = loaded.value;
  const error = loaded.error === undefined ? "" : messageOf(loaded.error);
  if (!initial || initial.projectId !== props.projectId)
    return (
      <section className="image-manager image-manager-loading">
        <header className="image-manager-heading">
          <h2>Image Manager</h2>
          <Button onClick={props.onClose}>
            {props.backLabel || "Back to Images"}
          </Button>
        </header>
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
  const blocked =
    !!asset.sourceIssue ||
    ["blocked", "conflict", "error", "missing_source"].includes(asset.state);
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
        title={`${asset.path}\n${imageStatus(asset)}`}
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
          className={`image-tile-status ${blocked || asset.classification === "uncertain" ? "image-status-blocked" : ""}`}
          aria-label={imageStatus(asset)}
        >
          {blocked || asset.classification === "uncertain" ? (
            <TriangleAlert size={14} />
          ) : asset.aiReviewed || asset.userReviewed ? (
            <CheckCircle2 size={14} />
          ) : asset.classification === "recommended" ? (
            <Sparkles size={13} />
          ) : asset.encrypted ? (
            <LockKeyhole size={13} />
          ) : asset.editable ? (
            <Pencil size={13} />
          ) : (
            <Circle size={12} />
          )}
        </span>
      </button>
      <span className="image-tile-name" title={asset.path}>
        {asset.filename}
      </span>
    </article>
  );
}

function Manager({
  projectId,
  onClose,
  onOpenEditor,
  initial,
  observed,
  observationKey,
  initialMode,
  backLabel,
}: ImageManagerProps & { initial: ImageManagerState }) {
  const [state, setState] = useState(initial);
  const stateRef = useRef(initial);
  const [listRevision, setListRevision] = useState(0);
  const [compare, setCompare] = useState<ImageAsset | null>(null);
  const [preview, setPreview] = useState<ImagePreview | null>(null);
  const [menu, setMenu] = useState(false);
  const [selectMenu, setSelectMenu] = useState(false);
  const [folderDialog, setFolderDialog] = useState(false);
  const [imageRoot, setImageRoot] = useState(initial.profile.imageRoot || "");
  const action = useAction();
  const adopt = (next: ImageManagerState) => {
    if (next.projectId !== projectId) return;
    stateRef.current = next;
    setState(next);
  };
  const draft = useDraft<ImageDraft>("images:" + projectId, {
    initial: { saved: imageDraft(initial) },
    report: action.report,
    persist: async (changes) => {
      const selectionChanged =
        stateRef.current.selection.join("\n") !== changes.selection.join("\n");
      const next = await imagesApi.update(
        projectId,
        stateRef.current.revision,
        changes,
      );
      adopt(next);
      if (selectionChanged) setListRevision((value) => value + 1);
    },
  });
  const value = draft.value || imageDraft(state);
  const manual = value.view.workflowMode === "manual";
  const applyInitialMode = useEffectEvent(() => {
    if (initialMode)
      draft.session.edit((current) => ({
        ...current,
        view: { ...current.view, workflowMode: initialMode },
      }));
  });
  useEffect(() => applyInitialMode(), []);
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
  const applyObserved = async (next: ImageManagerState) => {
    if (next.projectId !== projectId) return;
    const previous = stateRef.current;
    const inventoryChanged =
      previous.inventoryRevision !== next.inventoryRevision ||
      previous.counts.indexed !== next.counts.indexed ||
      previous.observationRevision !== next.observationRevision;
    if (draft.session.getSnapshot().dirty || action.busy) {
      setState((current) => ({
        ...current,
        counts: next.counts,
        job: next.job,
        folders: next.folders,
        warnings: next.warnings,
      }));
      return;
    }
    adopt(next);
    if (next.revision !== previous.revision)
      draft.session.adopt(imageDraft(next));
    if (
      inventoryChanged ||
      next.editing.lastReport !== previous.editing.lastReport ||
      next.discovery.lastReport !== previous.discovery.lastReport
    )
      setListRevision((value) => value + 1);
  };
  const observe = useEffectEvent(applyObserved);
  const reportObservation = useEffectEvent((error: unknown) =>
    action.report(error),
  );
  useEffect(() => {
    // Pushed observer state also updates the external draft session, which
    // cannot change during render.
    // oxlint-disable-next-line react/set-state-in-effect
    if (observed) void observe(observed);
  }, [observed]);
  useEffect(() => {
    if (observed || observationKey === undefined) return;
    let alive = true;
    void imagesApi
      .state(projectId)
      .then((next) => {
        if (alive) void observe(next);
      })
      .catch(reportObservation);
    return () => {
      alive = false;
    };
  }, [observed, observationKey, projectId]);
  const perform = async (
    name: string,
    options: Record<string, unknown> = {},
    notice = "",
  ) => {
    setMenu(false);
    setSelectMenu(false);
    await action.run(
      async () => {
        await draft.session.commit(async () => {
          const reply: ImageActionResult = await imagesApi.action(
            projectId,
            name,
            options,
          );
          adopt(reply.state);
          setListRevision((value) => value + 1);
          if (reply.text) await window.dazedtl.copyText(reply.text);
          if (reply.preview) setPreview(reply.preview);
          if (reply.text)
            action.succeed(
              "Task copied. Paste into your coding assistant to begin or resume.",
              name,
            );
          if (name === "apply" || name === "restore") setPreview(null);
          return { saved: imageDraft(reply.state) };
        });
      },
      notice ||
        (name.includes("task")
          ? "Task copied. Paste into your coding assistant to begin or resume."
          : ""),
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
          const next = await imagesApi.update(
            projectId,
            stateRef.current.revision,
            { imageRoot: imageRoot.trim() },
          );
          adopt(next);
          const reply = await imagesApi.action(projectId, "scan");
          adopt(reply.state);
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
  const close = () => {
    void action.run(
      async () => {
        await draft.session.flush();
        onClose();
      },
      "",
      "close",
    );
  };
  const counts = state.counts;
  const hidden = Math.max(0, value.selection.length - grid.selectedMatched);
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
  const selectedApplied = draft.dirty ? 0 : counts.selectedApplied || 0;
  const allApplied =
    !!value.selection.length && selectedApplied === value.selection.length;
  const primaryAction = allApplied
    ? "close"
    : selectedReady
      ? "preview_apply"
      : selectedNotPrepared
        ? "prepare"
        : value.selection.length
          ? state.editing.status === "awaiting_results"
            ? "refresh_results"
            : "edit_task"
          : state.discovery.status === "awaiting_results"
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
  return (
    <section className="image-manager" aria-label="Image Manager">
      <header className="image-manager-heading">
        <div>
          <h2>Image Manager</h2>
          <span>
            {state.name} · {counts.indexed.toLocaleString()} images
          </span>
        </div>
        <Button
          variant={primaryAction === "close" ? "primary" : "default"}
          disabled={action.busy}
          onClick={close}
        >
          {backLabel || "Back to Images"}
        </Button>
      </header>
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
      <section
        className="image-discovery"
        aria-label="Find images to translate"
      >
        <div className="image-discovery-heading">
          <strong>Find images to translate</strong>
          <span>
            AI findings help choose a batch; you can adjust the selection.
          </span>
          <Button
            variant="link"
            disabled={action.busy}
            onClick={() =>
              changeView({ workflowMode: manual ? "discovery" : "manual" })
            }
          >
            {manual ? "Use AI discovery" : "Choose images myself"}
          </Button>
        </div>
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
            <Button
              variant={
                primaryAction === "discovery_task" ? "primary" : "default"
              }
              disabled={
                action.busy || jobRunning || scopeMissing || !counts.indexed
              }
              pending={action.busy && action.key === "discovery_task"}
              onClick={() => perform("discovery_task", scopeOptions)}
            >
              Copy discovery task
            </Button>
            <Button
              variant={
                primaryAction === "refresh_findings" ? "primary" : "default"
              }
              disabled={action.busy || jobRunning}
              pending={action.busy && action.key === "refresh_findings"}
              onClick={() => perform("refresh_findings")}
            >
              Refresh findings
            </Button>
            <Button
              disabled={action.busy || jobRunning || !counts.recommended}
              onClick={() => perform("use_recommendations", { mode: "add" })}
            >
              Use recommended selection ({counts.recommended})
            </Button>
            {value.discoveryScope === "folders" && (
              <span className="image-scope-context">
                {value.view.folder || "Choose a folder in the browser."}
              </span>
            )}
          </div>
        )}
        <div className="image-discovery-counts">
          <span>{counts.examined.toLocaleString()} examined</span>
          <Button
            variant="link"
            onClick={() => changeView({ status: "recommended" }, true)}
          >
            {counts.recommended.toLocaleString()} recommended
          </Button>
          <Button
            variant="link"
            onClick={() => changeView({ status: "uncertain" }, true)}
          >
            {counts.uncertain.toLocaleString()} uncertain
          </Button>
          <Button
            variant="link"
            onClick={() => changeView({ status: "not_examined" }, true)}
          >
            {counts.notExamined.toLocaleString()} not examined
          </Button>
          {lastReport ? (
            <span>
              Last saved report: {new Date(lastReport).toLocaleString()}
            </span>
          ) : state.editing.status === "awaiting_results" ||
            state.discovery.status === "awaiting_results" ? (
            <span>Awaiting saved assistant results.</span>
          ) : null}
        </div>
      </section>
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
        <div className="image-menu-anchor">
          <Button
            aria-expanded={selectMenu}
            disabled={action.busy}
            onClick={() => {
              setSelectMenu(!selectMenu);
              setMenu(false);
            }}
          >
            Select…
          </Button>
          {selectMenu && (
            <div
              className="image-popover"
              role="group"
              aria-label="Bulk image selection"
            >
              <Button
                onClick={() =>
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
              </Button>
              <Button
                onClick={() =>
                  perform("select_matching", {
                    query: "",
                    filter: "all",
                    folder: "",
                    mode: "add",
                  })
                }
              >
                Select all ({counts.indexed.toLocaleString()})
              </Button>
              <Button
                onClick={() => {
                  change({ selection: [] });
                  setSelectMenu(false);
                }}
              >
                Clear selection
              </Button>
            </div>
          )}
        </div>
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
                {counts.indexed ? "No matching images" : "No images indexed"}
              </h3>
              <p>
                {counts.indexed
                  ? "Hidden images remain selected."
                  : "Index the image library to begin discovery or choose images yourself."}
              </p>
              <Button
                onClick={() =>
                  counts.indexed
                    ? changeView(
                        {
                          query: "",
                          status: "all",
                          folder: "",
                          showSelected: false,
                        },
                        true,
                      )
                    : perform("scan")
                }
              >
                {counts.indexed ? "Clear filters" : "Index images"}
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
      <footer className="image-manager-footer">
        <div className="image-selection-context">
          <div>
            <strong>{value.selection.length.toLocaleString()} selected</strong>
            <span> · {hidden.toLocaleString()} hidden</span>
            {draft.dirty ? (
              <span> · Saving choices…</span>
            ) : (
              <span>
                {" "}
                · {selectedReady} ready
                {selectedNotPrepared
                  ? ` · ${selectedNotPrepared} not prepared`
                  : ""}
                {selectedApplied ? ` · ${selectedApplied} applied` : ""} ·{" "}
                {selectedBlocked} blocked
              </span>
            )}
          </div>
          <div className="image-selection-links">
            <Button
              variant="link"
              aria-pressed={value.view.showSelected}
              onClick={() =>
                changeView({ showSelected: !value.view.showSelected }, true)
              }
            >
              {value.view.showSelected ? "Show all" : "Show selected"}
            </Button>
            <Button
              variant="link"
              disabled={!value.selection.length || action.busy}
              onClick={() => change({ selection: [] })}
            >
              Clear selection
            </Button>
            {!!selectedBlocked && (
              <Button
                variant="link"
                onClick={() =>
                  changeView({ status: "blocked", showSelected: true }, true)
                }
              >
                View issues
              </Button>
            )}
          </div>
        </div>
        <div className="image-main-actions">
          <Button
            variant={primaryAction === "prepare" ? "primary" : "default"}
            disabled={action.busy || jobRunning || !value.selection.length}
            pending={action.busy && action.key === "prepare"}
            onClick={() => perform("prepare")}
          >
            Make editable
          </Button>
          <Button
            variant={primaryAction === "edit_task" ? "primary" : "default"}
            disabled={
              action.busy ||
              jobRunning ||
              draft.dirty ||
              !value.selection.length ||
              !!selectedNotPrepared
            }
            pending={action.busy && action.key === "edit_task"}
            onClick={() => perform("edit_task")}
          >
            Copy image task
          </Button>
          <Button
            variant={
              primaryAction === "refresh_results" ? "primary" : "default"
            }
            disabled={action.busy || jobRunning}
            pending={action.busy && action.key === "refresh_results"}
            onClick={() => perform("refresh_results")}
          >
            Refresh results
          </Button>
          <Button
            variant={primaryAction === "preview_apply" ? "primary" : "default"}
            disabled={action.busy || jobRunning || !selectedReady}
            pending={action.busy && action.key === "preview_apply"}
            onClick={() => perform("preview_apply")}
          >
            Review &amp; apply ({selectedReady})
          </Button>
          <div className="image-menu-anchor">
            <Button
              aria-label="Image tools and recovery"
              aria-expanded={menu}
              disabled={action.busy}
              onClick={() => {
                setMenu(!menu);
                setSelectMenu(false);
              }}
            >
              <MoreHorizontal size={16} />
              More
            </Button>
            {menu && (
              <div
                className="image-popover image-popover-up"
                role="group"
                aria-label="Image tools and recovery"
              >
                <Button
                  disabled={!value.selection.length}
                  onClick={() => {
                    setMenu(false);
                    void action.run(async () => {
                      await draft.session.flush();
                      const current = draft.session.getSnapshot().value!;
                      onOpenEditor(
                        current.selection,
                        current.view.workflowMode || "discovery",
                      );
                    });
                  }}
                >
                  Edit text…
                </Button>
                <Button onClick={() => perform("scan")}>
                  Refresh inventory
                </Button>
                {state.profile.id === "generic" && (
                  <Button
                    onClick={() => {
                      setMenu(false);
                      setImageRoot(state.profile.imageRoot || "");
                      setFolderDialog(true);
                    }}
                  >
                    Choose image folder…
                  </Button>
                )}
                <Button
                  disabled={!value.selection.length}
                  onClick={() => perform("preview_restore")}
                >
                  Review restore originals…
                </Button>
                <Button
                  disabled={!value.selection.length}
                  onClick={() =>
                    perform("exclude", {
                      asset_ids: value.selection,
                      reason: "Excluded from this image translation scope.",
                    })
                  }
                >
                  Exclude selected
                </Button>
                <Button
                  disabled={!value.selection.length}
                  onClick={() =>
                    perform("include", { asset_ids: value.selection })
                  }
                >
                  Include selected again
                </Button>
              </div>
            )}
          </div>
        </div>
        <div className="image-action-feedback">
          <Message message={action.error} />
          {!!action.error && draft.dirty && (
            <Button
              pending={action.busy}
              onClick={() =>
                action.run(
                  async () => {
                    const latest = await imagesApi.state(projectId);
                    adopt(latest);
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
          {action.notice && <span role="status">{action.notice}</span>}
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
      </footer>
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
          className="image-apply-modal"
          dismissible={!action.busy}
          onDismiss={() => {
            setFolderDialog(false);
            action.clear();
          }}
        >
          <header className="image-modal-heading">
            <h2>Choose loose image folder</h2>
          </header>
          <div className="image-apply-body">
            <p>
              Enter a folder relative to this game's root. Only loose PNGs are
              supported; archives must be extracted separately.
            </p>
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
            <p className="muted">Game root: {state.source}</p>
          </div>
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
