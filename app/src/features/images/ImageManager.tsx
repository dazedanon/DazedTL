import { PathText } from "../../ui/PathText";
import { FileName } from "../../ui/FileName";
import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import {
  ChevronDown,
  Eye,
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
  ImageForeignWork,
  ImageManagerState,
  ImagePreview,
} from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { Button } from "../../ui/Button";
import { Menu, MenuItem, MenuSeparator } from "../../ui/Menu";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { FeedbackOwners, useOwnedFeedback } from "../../ui/FeedbackOwners";
import { ActionSlot } from "../../ui/ActionSlot";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { Message } from "../../ui/Feedback";
import { ForeignWork } from "../../ui/ForeignWork";
import {
  gridStep,
  imageDraft,
  imageStatus,
  virtualRows,
} from "./imageSelection";
import { focusItem, selectItem, type Modifiers } from "../../ui/selection";
import { useImageGrid } from "./useImageGrid";
import { ThumbnailQueue, useThumbnail } from "./thumbnails";
import { ImageCompare } from "./ImageCompare";
import { ImageViewer } from "./ImageViewer";
import { ImageApply } from "./ImageApply";
import { ImageFolders } from "./ImageFolders";
import { useObserved } from "../../state/useObserved";
import { useOnChange } from "../../state/useOnChange";
import { useRead } from "../../state/useRead";
import { AssistantTask, type AssistantTaskState } from "../../ui/AssistantTask";
import { SegmentedControl } from "../../ui/SegmentedControl";
import { StepProgress } from "../../ui/StepProgress";
import { imageFlow, imageSteps } from "./imageFlow";
import { useHandoff } from "../assistant/useAssistantTasks";

export interface ImageManagerProps {
  projectId: string;
  onOpenEditor: (assetIds: string[]) => void;
  observed?: ImageManagerState | null;
  /** Image work this game folder holds for another project. */
  foreign?: ImageForeignWork;
  /**
   * Replaces Apply to game with the host's own review, such as Guided's
   * pending changes, of the list's translated images.
   */
  applyControl?: (apply: {
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
  // The choice made for saved work stays settled until the snapshot shows it.
  const [settled, setSettled] = useState({ binding: "", notice: "" });
  const foreign =
    props.foreign && props.foreign.binding !== settled.binding
      ? props.foreign
      : undefined;
  const observed = start?.projectId === props.projectId ? start : null;
  const loaded = useRead(observed || foreign ? null : props.projectId, () =>
    imagesApi.state(props.projectId),
  );
  const initial = observed || loaded.value;
  const error = loaded.error === undefined ? "" : messageOf(loaded.error);
  const hostFooter = (
    <ActionSlot target={props.footer.target}>
      <ActionBar
        feedback={
          <div className="image-footer-context">{props.footer.back}</div>
        }
      >
        {props.footer.next("quiet")}
      </ActionBar>
    </ActionSlot>
  );
  if (foreign)
    return (
      <section className="image-manager">
        {hostFooter}
        <ForeignImages
          projectId={props.projectId}
          work={foreign}
          onSettled={(reply) => {
            setStart(reply.state);
            setSettled({
              binding: foreign.binding,
              notice: reply.message || "",
            });
          }}
        />
      </section>
    );
  if (!initial || initial.projectId !== props.projectId)
    return (
      <section className="image-manager image-manager-loading">
        {hostFooter}
        <Message message={error} />
        <p role="status">
          {error
            ? "Image Manager could not load."
            : "Loading saved image work…"}
        </p>
        {error && <Button onClick={loaded.retry}>Retry</Button>}
      </section>
    );
  return (
    <FeedbackOwners>
      <Manager
        key={props.projectId}
        {...props}
        initial={initial}
        notice={settled.notice}
      />
    </FeedbackOwners>
  );
}

/** Image work another project saved here, and the two ways on. */
function ForeignImages({
  projectId,
  work,
  onSettled,
}: {
  projectId: string;
  work: ImageForeignWork;
  onSettled: (reply: ImageActionResult) => void;
}) {
  const action = useAction();
  const choose = async (choice: "adopt" | "start_over") => {
    const result = await action.run(
      () =>
        choice === "adopt"
          ? imagesApi.adopt(projectId, work.binding)
          : imagesApi.startOver(projectId, work.binding),
      "",
      choice,
    );
    if (result.ok) onSettled(result.value);
  };
  const feedback = (key: string) => ({
    pending: action.busy && action.key === key,
    error: action.key === key ? action.error : "",
  });
  return (
    <ForeignWork
      title="Image work from another project"
      work={work}
      counts={[
        [work.examined, "images examined"],
        [work.edited, "edited"],
        [work.applied, "applied"],
      ]}
      kept={["findings", "selected and edited images", "reviews"]}
      noun="images"
      next="Copy image tasks again to continue them: tasks copied in the other project aren't accepted here."
      left={`Edited copies are kept and found again by the next scan.${work.applied ? " Applied images stay in the game but can't be restored or added to patch ZIPs here." : ""}`}
      adopt={
        <ActionControl
          label="Use saved progress"
          variant={work.blocked ? "default" : "primary"}
          disabled={action.busy || !!work.blocked}
          {...feedback("adopt")}
          onClick={() => choose("adopt")}
        />
      }
      startOver={
        <ActionControl
          label="Start over"
          disabled={action.busy}
          {...feedback("start_over")}
          onClick={() => choose("start_over")}
        />
      }
    />
  );
}

function Tile({
  asset,
  selected,
  size,
  queue,
  onPick,
  onKeyDown,
  onCompare,
}: {
  asset: ImageAsset;
  selected: boolean;
  size: number;
  queue: ThumbnailQueue;
  /** Chooses the image with the click's modifiers; `checkbox` toggles it. */
  onPick: (event: Modifiers, checkbox?: boolean) => void;
  onKeyDown: (event: KeyboardEvent) => void;
  onCompare: () => void;
}) {
  const pixels = useThumbnail(queue, asset, size);
  const display = imageDisplay(asset, selected);
  // Of the images not started, recommended ones and editable copies are the
  // ones to work on next, so their mark takes the accent.
  const next =
    display === "not_started" &&
    (asset.classification === "recommended" || asset.editable);
  // Keys continue from the image last clicked, Shift-clicked ones included.
  const focus = (event: ReactMouseEvent<HTMLElement>) => {
    const input = event.currentTarget.querySelector("input");
    if (input) focusItem(input, "pointer");
  };
  // A click anywhere on the tile chooses the image as a file selector row
  // does, and its checkbox toggles it and takes the keyboard from there; only
  // the eye opens Compare.
  return (
    <article
      className="image-tile"
      data-selected={selected}
      data-state={asset.state}
      onMouseDown={(event) => {
        if (event.shiftKey) event.preventDefault();
      }}
      onClick={(event) => {
        focus(event);
        onPick(event);
      }}
      onKeyDown={onKeyDown}
    >
      <label
        className="image-tile-select"
        onClick={(event) => {
          event.stopPropagation();
          focus(event);
        }}
      >
        <input
          aria-label={`Select ${asset.filename}`}
          type="checkbox"
          checked={selected}
          onChange={(event) => onPick(event.nativeEvent as MouseEvent, true)}
        />
      </label>
      <div
        className="image-tile-preview"
        // Encryption is supported throughout; it is noted, not marked, since a
        // game encrypts all of its images or none.
        title={`${asset.path}\n${imageStatus(asset, selected)}${asset.encrypted ? " · Encrypted" : ""}`}
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
          role="img"
          data-next={next || undefined}
          aria-label={imageStatus(asset, selected)}
        >
          <StatusIcon status={displayMarks[display]} size={14} />
        </span>
      </div>
      <div className="image-tile-footer">
        <FileName
          className="image-tile-name"
          name={asset.filename}
          title={asset.path}
        />
        <Button
          variant="quiet"
          className="image-tile-compare"
          aria-label={`Compare ${asset.filename}`}
          title={`Compare ${asset.filename}`}
          onKeyDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onCompare();
          }}
        >
          <Eye size={14} aria-hidden="true" />
        </Button>
      </div>
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
  notice,
}: ImageManagerProps & {
  initial: ImageManagerState;
  /** What the choice made for another project's saved work did. */
  notice: string;
}) {
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
    // Saved choices leave the grid as it is; useImageGrid recounts the
    // selected images its filters hide.
    persist: async (changes) => {
      images.set(
        await imagesApi.update(projectId, images.latest().revision, changes),
      );
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
  const editingTask = useHandoff("image_editing");
  const discoveryTask = useHandoff("image_discovery");
  // A dismissed task no longer waits for its report, and a task copied again
  // waits for a newer one.
  const flow = imageFlow(state, {
    investigation:
      (state.discovery.status === "awaiting_results" &&
        !discoveryTask.dismissed) ||
      discoveryTask.waiting,
    translation:
      (state.editing.status === "awaiting_results" && !editingTask.dismissed) ||
      editingTask.waiting,
  });
  // A step's result stays with its step: a notice from a step that has
  // passed is not shown under the grid.
  const [actedIn, setActedIn] = useState(flow.step);
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
  const queue = useMemo(
    () =>
      new ThumbnailQueue((asset, size, current) =>
        imagesApi.pixels(
          projectId,
          asset.id,
          asset.candidateHash ? "candidate" : "source",
          size,
          current,
        ),
      ),
    [projectId],
  );
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
  // Thumbnails match the screen's pixel density, with room for columns that
  // stretch past the chosen size; steps of 16 keep cached sizes shared.
  const thumbnailSize =
    Math.ceil((value.view.tileSize * devicePixelRatio * 1.25) / 16) * 16;
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
    state.selection,
    range.start,
    range.end,
  );
  useOnChange(grid.total, setTotal);
  // The view's other thumbnails load while nothing on screen waits, nearest
  // first, so scrolling and the viewer find them ready.
  const middle = useEffectEvent(() => (range.start + range.end) / 2);
  useEffect(() => {
    const from = middle();
    queue.prefetch(
      [...grid.listed]
        .sort((a, b) => Math.abs(a.index - from) - Math.abs(b.index - from))
        .map(({ asset }) => asset),
      thumbnailSize,
    );
  }, [queue, grid.listed, thumbnailSize]);
  // Shift ranges start from the last image clicked without Shift in this view.
  const view = JSON.stringify([
    value.view.query,
    value.view.status,
    value.view.folder,
    value.view.showSelected,
  ]);
  const anchor = useRef<{ id: string; index: number; view: string }>(null);
  const picks = useRef(0);
  const [pickNotice, setPickNotice] = useState("");
  // The viewer shows the image last clicked or moved to. A drawn tile hands
  // over its image; otherwise, and after each reload, it is read by its id.
  const viewedId = value.view.viewedImage || "";
  const [viewed, setViewed] = useState<{
    id: string;
    revision: number;
    asset: ImageAsset | null;
  }>();
  useEffect(() => {
    if (
      !viewedId ||
      (viewed?.id === viewedId && viewed.revision === listRevision)
    )
      return;
    let alive = true;
    void imagesApi
      .list(projectId, { asset_id: viewedId, limit: 1 }, () => alive)
      .then(
        (result) => {
          if (alive)
            setViewed({
              id: viewedId,
              revision: listRevision,
              asset: result.items[0] ?? null,
            });
        },
        // The grid's own reads report a failing list.
        () => {},
      );
    return () => {
      alive = false;
    };
  }, [projectId, viewedId, listRevision, viewed]);
  const viewedAsset =
    (viewedId &&
      (grid.items.find(({ asset }) => asset.id === viewedId)?.asset ??
        (viewed?.id === viewedId ? viewed.asset : null))) ||
    null;
  const showInViewer = (index: number, id: string) => {
    const asset = grid.items.find((item) => item.index === index)?.asset;
    if (asset?.id === id) setViewed({ id, revision: listRevision, asset });
  };
  /**
   * A click previews its image. The tick box, Ctrl/Cmd-click and Space tick
   * or untick it, and Shift adds the run from the image last clicked, so
   * looking at an image never changes the list to translate.
   */
  const pick = (index: number, event: Modifiers, checkbox = false) => {
    const gesture = event.shiftKey
      ? "add-range"
      : checkbox || event.ctrlKey || event.metaKey
        ? "toggle"
        : null;
    const from =
      anchor.current?.view === view && gesture === "add-range"
        ? anchor.current
        : null;
    const first = Math.min(index, from?.index ?? index);
    const ticket = ++picks.current;
    const finish = (ids: string[]) => {
      const target = ids[index - first];
      if (ticket !== picks.current || !target) return;
      const start = from && ids.includes(from.id) ? from.id : null;
      anchor.current = start ? from : { id: target, index, view };
      showInViewer(index, target);
      draft.session.edit((current) => ({
        ...current,
        ...(gesture && {
          selection: selectItem(current.selection, ids, target, gesture, start)
            .selected,
        }),
        view: { ...current.view, viewedImage: target },
      }));
      setPickNotice(start ? "Ticked these images to translate." : "");
    };
    const ids = grid.ids(first, Math.max(index, from?.index ?? index));
    if (Array.isArray(ids)) finish(ids);
    else
      void ids.then(finish, (error: unknown) => {
        if (ticket === picks.current) action.report(error, "select-range");
      });
  };
  // A key can move to a tile that is not drawn yet; it takes focus on arrival.
  const pendingFocus = useRef<{ index: number; view: string }>(null);
  const focusTile = (index: number) => {
    const element = viewport.current;
    if (!element) return;
    const space = element.querySelector<HTMLElement>(".image-grid-space");
    const top =
      (space?.offsetTop ?? 0) + Math.floor(index / columns) * rowHeight;
    if (top < element.scrollTop) element.scrollTop = top;
    else if (top + rowHeight > element.scrollTop + element.clientHeight)
      element.scrollTop = top + rowHeight - element.clientHeight;
    const input = element.querySelector<HTMLInputElement>(
      `[data-tile-index="${index}"] input`,
    );
    if (input) focusItem(input, "key");
    pendingFocus.current = input ? null : { index, view };
  };
  const tileKeyDown = (event: KeyboardEvent, index: number) => {
    const additive = event.ctrlKey || event.metaKey;
    if (additive && event.key.toLowerCase() === "a") {
      event.preventDefault();
      addMatching();
      return;
    }
    if (event.key === " ") {
      event.preventDefault();
      pick(index, event, true);
      return;
    }
    const next = gridStep(event.key, index, columns, grid.total);
    if (next === null) return;
    event.preventDefault();
    focusTile(next);
    // Arrows move the preview; Shift ticks the images they pass.
    pick(
      next,
      event.shiftKey
        ? event
        : { shiftKey: false, ctrlKey: false, metaKey: false },
    );
  };
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
    setActedIn(flow.step);
    // Only a task that reached the clipboard says it was copied.
    let copied = false;
    let message = "";
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
          message = reply.message || "";
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
        `Copied. Paste it into your coding assistant.${message ? ` ${message}` : ""}`,
        name,
      );
    else if (result.ok && message) action.succeed(message, name);
  };
  // A project's first visit indexes its images once. What opened the
  // manager, such as setting earlier work aside, reports as its result.
  const opened = useEffectEvent(() => {
    if (
      state.profile.supported &&
      !state.inventoryRevision &&
      !state.counts.indexed &&
      !state.job
    )
      void perform("scan", {}, notice);
    else if (notice) action.succeed(notice, "opened");
  });
  const initialScan = useRef(false);
  useEffect(() => {
    if (initialScan.current) return;
    initialScan.current = true;
    opened();
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
  // Ctrl+A and Select tick or untick every image the view shows.
  const tickShown = (mode: "add" | "remove") =>
    void perform("select_matching", {
      query: value.view.query,
      filter: value.view.status,
      folder: value.view.folder,
      selected_only: value.view.showSelected,
      mode,
    });
  const addMatching = () => tickShown("add");
  const openCompare = (asset: ImageAsset) => {
    setCompare(asset);
    changeView({ currentImage: asset.id });
    action.clear();
  };
  const counts = state.counts;
  const hidden = grid.hidden ?? 0;
  const folderSearch = !!value.view.folder && !!value.view.query.trim();
  const selectedBlocked = draft.dirty ? 0 : counts.selectedBlocked || 0;
  const jobRunning =
    !!state.job &&
    ["pending", "running", "stopping"].includes(state.job.status);
  const waiting = flow.waiting.investigation || flow.waiting.translation;
  const copiedAt =
    (flow.waiting.translation && state.editing.copiedAt) ||
    (flow.waiting.investigation && state.discovery.copiedAt) ||
    "";
  // A report found on returning to the window and rejected says why first.
  const rejected = state.editing.rejected || state.discovery.rejected || "";
  const imageCount = (count: number) =>
    `${count.toLocaleString()} ${count === 1 ? "image" : "images"}`;
  const cardState: AssistantTaskState = rejected
    ? "blocked"
    : waiting
      ? "waiting"
      : flow.step === "choose"
        ? "needs_review"
        : flow.step === "apply"
          ? "ready"
          : flow.step === "done"
            ? counts.applied
              ? "applied"
              : "done"
            : "not_started";
  const description = rejected
    ? rejected
    : flow.step === "investigate"
      ? flow.waiting.investigation
        ? "Your assistant is examining the images. The ones it recommends are ticked to translate as it saves them."
        : "Your assistant examines the game's images and recommends the ones with text players read."
      : flow.step === "choose"
        ? flow.listed
          ? `${imageCount(flow.listed)} to translate. Untick any to leave out, or tick other images to add them.`
          : "Tick the images to translate, then copy the translation task."
        : flow.step === "translate"
          ? flow.waiting.translation
            ? `Your assistant is translating ${imageCount(flow.toTranslate)}. Results appear on them as it saves them.`
            : `${imageCount(flow.untranslated)} in your list ${flow.untranslated === 1 ? "isn't" : "aren't"} translated yet. Copy the translation task to continue.`
          : flow.step === "apply"
            ? `${flow.ready ? `${imageCount(flow.ready)} translated. ` : ""}Look them over, Compare shows before and after, and tell your assistant about anything to redo.`
            : counts.applied
              ? `${imageCount(counts.applied)} ${counts.applied === 1 ? "is" : "are"} in the game. Later tasks skip them unless the game's image changes.`
              : "Your assistant found no image text players read.";
  const reportIssues = [
    ...(state.discovery.errors || []),
    ...(state.editing.errors || []),
    ...state.warnings,
  ];
  const activeCompare =
    compare &&
    (grid.items.find(({ asset }) => asset.id === compare.id)?.asset || compare);
  const owned = useOwnedFeedback(action.key);
  const step = (key: string, pendingText: string) => ({
    feedbackKey: key,
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
    onClick: () => void perform(key),
  });
  const busy = action.busy || jobRunning;
  // The grid's views, from the list to translate to every image.
  const views = {
    list: { showSelected: true, status: "all" },
    uncertain: { showSelected: false, status: "uncertain" },
    ready: { showSelected: false, status: "ready" },
    applied: { showSelected: false, status: "applied" },
    all: { showSelected: false, status: "all" },
  } as const;
  type GridView = keyof typeof views | "";
  const shown: GridView = value.view.showSelected
    ? value.view.status === "all"
      ? "list"
      : ""
    : (["uncertain", "ready", "applied", "all"] as const).find(
        (key) => key === value.view.status,
      ) || "";
  const viewOptions: { value: GridView; label: string; count: number }[] = [
    { value: "list", label: "To translate", count: value.selection.length },
    { value: "uncertain", label: "Unsure", count: counts.uncertain },
    { value: "ready", label: "Translated", count: counts.ready },
    { value: "applied", label: "Applied", count: counts.applied },
    { value: "all", label: "All images", count: counts.indexed },
  ];
  const editText = () =>
    void action.run(
      async () => {
        await draft.session.flush();
        // The editor works on editable copies; images in the list without
        // one get it first, as the translation task does.
        const listed = async () => {
          const rows: ImageAsset[] = [];
          for (let offset = 0, total = 1; offset < total; offset += 500) {
            const page = await imagesApi.list(projectId, {
              selected_only: true,
              offset,
              limit: 500,
            });
            total = page.total;
            rows.push(...page.items);
          }
          return rows;
        };
        let rows = await listed();
        const missing = rows.filter((row) => !row.editable);
        if (missing.length) {
          const reply = await imagesApi.action(projectId, "prepare", {
            asset_ids: missing.map((row) => row.id),
          });
          images.set(reply.state);
          rows = await listed();
        }
        const editable = rows.filter((row) => row.editable);
        if (!editable.length)
          throw new Error("These images can't be edited; Blocked lists why.");
        onOpenEditor(editable.map((row) => row.id));
      },
      "",
      "edit_text",
    );
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
      {flow.step !== "investigate" && !!counts.notExamined && (
        <MenuItem
          disabled={jobRunning}
          onSelect={() =>
            void perform("discovery_task", { scope: "remaining" })
          }
        >
          Investigate the {imageCount(counts.notExamined)} not examined
        </MenuItem>
      )}
      <MenuItem
        disabled={jobRunning || !value.view.folder}
        onSelect={() =>
          void perform("discovery_task", {
            scope: "folders",
            folders: [value.view.folder],
          })
        }
      >
        Investigate this folder
      </MenuItem>
      <MenuItem
        disabled={
          jobRunning ||
          (state.discovery.status === "idle" && state.editing.status === "idle")
        }
        onSelect={() =>
          void perform(
            state.editing.status === "idle" || flow.step === "investigate"
              ? "refresh_findings"
              : "refresh_results",
          )
        }
      >
        Check for results
      </MenuItem>
      <MenuItem disabled={!value.selection.length} onSelect={editText}>
        Edit text…
      </MenuItem>
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
        Restore originals…
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
        Exclude ticked images
      </MenuItem>
      <MenuItem
        disabled={!value.selection.length}
        onSelect={() => perform("include", { asset_ids: value.selection })}
      >
        Include ticked images again
      </MenuItem>
    </Menu>
  );
  // One button leads: the current step's, or Continue once Images is done.
  const translating =
    flow.step === "choose" ||
    flow.step === "translate" ||
    (flow.step === "apply" && flow.untranslated > 0);
  const footer = (
    <ActionBar
      feedback={
        <div className="image-footer-context">
          {host.back}
          {draft.dirty && <span>Saving choices…</span>}
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
      {flow.step === "investigate" && (
        <ActionControl
          label="Copy investigation task"
          variant={flow.waiting.investigation ? "default" : "primary"}
          disabled={busy || !counts.indexed}
          disabledReason={counts.indexed ? "" : "Index the images first."}
          {...step("discovery_task", "Copying…")}
          onClick={() => void perform("discovery_task", { scope: "remaining" })}
        />
      )}
      {translating && (
        <ActionControl
          label={`Copy translation task${flow.toTranslate ? ` (${flow.toTranslate.toLocaleString()})` : ""}`}
          variant={
            flow.step === "choose" ||
            (flow.step === "translate" && !flow.waiting.translation)
              ? "primary"
              : "default"
          }
          disabled={busy || draft.dirty || !flow.toTranslate}
          disabledReason={
            flow.toTranslate ? "" : "Tick the images to translate first."
          }
          {...step("edit_task", "Copying…")}
        />
      )}
      {(flow.ready > 0 || flow.step === "apply") &&
        (applyControl ? (
          applyControl({
            ready: flow.ready,
            primary: flow.step === "apply",
            blocked: busy || draft.dirty,
          })
        ) : (
          <ActionControl
            label={`Apply to game${flow.ready ? ` (${flow.ready.toLocaleString()})` : ""}`}
            variant={flow.step === "apply" ? "primary" : "default"}
            disabled={busy || draft.dirty || !flow.ready}
            disabledReason={
              flow.ready ? "" : "No image in your list is translated yet."
            }
            {...step("preview_apply", "Preparing review…")}
            onClick={() => void perform("preview_apply", { ready_only: true })}
          />
        ))}
      {host.next(flow.step === "done" ? "primary" : "quiet")}
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
      {/* The preview fills a column beside the task, toolbar and grid. */}
      <div className="image-manager-body">
        <div className="image-manager-work">
          <AssistantTask
            title="Image translation"
            state={cardState}
            progress={
              waiting && copiedAt
                ? `since ${new Date(copiedAt).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}`
                : undefined
            }
            description={description}
          >
            <StepProgress
              label="Image translation steps"
              steps={imageSteps}
              current={
                flow.step === "done"
                  ? imageSteps.length
                  : imageSteps.findIndex((item) => item.id === flow.step)
              }
            />
            {!!flow.review && (
              <Button
                variant="link"
                className="image-task-note"
                onClick={() =>
                  changeView(
                    { status: "needs_review", showSelected: true },
                    true,
                  )
                }
              >
                {imageCount(flow.review)} changed after your assistant checked{" "}
                {flow.review === 1 ? "it" : "them"}
              </Button>
            )}
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
            <Menu
              trigger={
                <>
                  Select
                  <ChevronDown size={14} aria-hidden="true" />
                </>
              }
              label="Tick images"
              align="start"
              disabled={action.busy}
            >
              <MenuItem onSelect={() => tickShown("add")}>
                Tick all shown ({grid.total.toLocaleString()})
              </MenuItem>
              <MenuItem
                disabled={!value.selection.length}
                onSelect={() => tickShown("remove")}
              >
                Untick all shown
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
            <SegmentedControl
              label="Show images"
              className="image-views"
              value={shown}
              options={viewOptions
                .filter(
                  (option) =>
                    option.count ||
                    option.value === shown ||
                    option.value === "all",
                )
                .map((option) => ({
                  value: option.value,
                  label: (
                    <>
                      {option.label}
                      <span className="image-view-count">
                        {option.count.toLocaleString()}
                      </span>
                    </>
                  ),
                }))}
              onChange={(next) => next && changeView(views[next], true)}
            />
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
              <Button
                disabled={action.busy}
                onClick={() => perform("stop_scan")}
              >
                Stop indexing
              </Button>
            </div>
          )}
          <div className="image-browser">
            <ImageFolders
              folders={state.folders}
              indexed={counts.indexed}
              folder={value.view.folder}
              onChoose={(folder) =>
                changeView({ folder, showSelected: false }, true)
              }
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
                <div
                  className="image-grid-space"
                  style={{ height: range.height }}
                >
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
                        data-tile-index={index}
                        ref={(cell) => {
                          const target = pendingFocus.current;
                          if (cell && target?.index === index) {
                            pendingFocus.current = null;
                            const input = cell.querySelector("input");
                            if (input && target.view === view)
                              focusItem(input, "key");
                          }
                        }}
                        style={{
                          minWidth: 0,
                          display: "flex",
                          gridRow:
                            Math.floor((index - range.start) / columns) + 1,
                          gridColumn: ((index - range.start) % columns) + 1,
                        }}
                      >
                        <Tile
                          asset={asset}
                          selected={selection.has(asset.id)}
                          size={thumbnailSize}
                          queue={queue}
                          onPick={(event, checkbox) =>
                            pick(index, event, checkbox)
                          }
                          onKeyDown={(event) => tileKeyDown(event, index)}
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
              <span className="sr-only" role="status">
                {pickNotice}
              </span>
            </div>
          </div>
          {/* Other results sit between the images and the footer. */}
          <div className="image-action-feedback">
            <Message
              message={owned ? "" : action.error}
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
            {action.notice && !owned && actedIn === flow.step && (
              <span role="status">{action.notice}</span>
            )}
            {!!reportIssues.length && (
              <details>
                <summary>
                  {reportIssues.length.toLocaleString()} image{" "}
                  {reportIssues.length === 1 ? "issue" : "issues"}
                </summary>
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
        </div>
        <ImageViewer
          projectId={projectId}
          asset={viewedAsset}
          listed={!!viewedAsset && selection.has(viewedAsset.id)}
          queue={queue}
          thumbnailSize={thumbnailSize}
          onCompare={openCompare}
        />
      </div>
      <ActionSlot target={host.target}>{footer}</ActionSlot>
      {activeCompare && (
        <ImageCompare
          projectId={projectId}
          asset={activeCompare}
          listed={selection.has(activeCompare.id)}
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
