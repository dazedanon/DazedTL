import { Plus } from "lucide-react";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import { api } from "../../api/client";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import type {
  ImageEditorSave,
  ImageEditorState,
  ImageNativeTranslationPreview,
  ImageNativeTranslationState,
  ImageTextBlock,
  ImageTextStyle,
} from "../../api/contracts";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { useOwnedFeedback } from "../../ui/FeedbackOwners";
import { sentence } from "../../ui/displayText";
import { Button } from "../../ui/Button";
import { ActionBar } from "../../ui/ActionBar";
import { Feedback, Message } from "../../ui/Feedback";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { JobStatus } from "../../ui/JobStatus";
import { ExpandableText } from "../../ui/ExpandableText";
import { useRead } from "../../state/useRead";

export interface ImageTextEditorProps {
  projectId: string;
  assetIds: string[];
  onClose: () => void;
  onChanged?: () => void;
  observationKey?: unknown;
}

type BackgroundRepair = NonNullable<ImageTextStyle["background"]>;
const backgroundRepairs: Record<BackgroundRepair, string> = {
  keep: "Leave pixels",
  transparent: "Clear text to transparent",
  solid: "Solid colour",
  vgradient: "Vertical gradient",
  hgradient: "Horizontal gradient",
  patch: "Clone clean strip",
  inpaint: "Local OpenCV repair",
};
/** Keep side-by-side canvases on the same region as one is scrolled. */
const syncScroll = (source: HTMLElement) => {
  const area = source.closest(".native-editor-canvases");
  for (const element of area?.querySelectorAll<HTMLElement>(
    ".native-editor-canvas-scroll",
  ) ?? [])
    if (
      element !== source &&
      (element.scrollLeft !== source.scrollLeft ||
        element.scrollTop !== source.scrollTop)
    ) {
      element.scrollLeft = source.scrollLeft;
      element.scrollTop = source.scrollTop;
    }
};
const isBackgroundRepair = (value: string): value is BackgroundRepair =>
  Object.hasOwn(backgroundRepairs, value);

const editorDraft = (state: ImageEditorState): ImageEditorSave[] =>
  state.images.map((image) => ({
    assetId: image.assetId,
    sourceHash: image.sourceHash,
    candidateHash: image.candidateHash,
    blocks: image.blocks,
    status: ["confirmed", "translated", "rendered"].includes(image.status)
      ? "confirmed"
      : "needs_review",
  }));
const colourHex = (value: number[] | null | undefined) =>
  "#" +
  (value || [255, 255, 255])
    .slice(0, 3)
    .map((channel) => channel.toString(16).padStart(2, "0"))
    .join("");
const colourChannels = (value: string) => [
  ...[1, 3, 5].map((index) =>
    Number.parseInt(value.slice(index, index + 2), 16),
  ),
  255,
];

export function ImageTextEditor(props: ImageTextEditorProps) {
  const scopeKey = JSON.stringify(props.assetIds);
  const editor = useRead(JSON.stringify([props.projectId, scopeKey]), () =>
    api.images.editorState(props.projectId, props.assetIds),
  );
  const initial = editor.value ?? null;
  const error = editor.error === undefined ? "" : messageOf(editor.error);
  if (!initial)
    return (
      <Modal
        label="Image Text Editor"
        className="native-image-editor"
        onDismiss={props.onClose}
      >
        <DialogHeader
          title="Image Text Editor"
          description="Optional tool · working copies only"
          actions={
            <Button onClick={props.onClose}>Back to Image Manager</Button>
          }
        />
        <div className="native-editor-empty">
          <Message message={error} />
          <p role="status">
            {error
              ? "The selected images could not open."
              : "Loading saved text and image work…"}
          </p>
          {error && <Button onClick={editor.retry}>Retry</Button>}
        </div>
      </Modal>
    );
  return (
    <Editor
      key={props.projectId + ":" + scopeKey}
      {...props}
      initial={initial}
    />
  );
}

function Editor({
  projectId,
  assetIds,
  initial,
  onClose,
  onChanged,
  observationKey,
}: ImageTextEditorProps & { initial: ImageEditorState }) {
  const [state, setState] = useState(initial);
  const stateRef = useRef(initial);
  const [imageId, setImageId] = useState(initial.images[0]?.assetId || "");
  const [selected, setSelected] = useState<string[]>([]);
  const [zoom, setZoom] = useState(1);
  const [comparison, setComparison] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const [drag, setDrag] = useState<{
    x: number;
    y: number;
    x2: number;
    y2: number;
  } | null>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const [nativeState, setNativeState] =
    useState<ImageNativeTranslationState | null>(null);
  const [selectedRun, setSelectedRun] = useState("");
  const [preview, setPreview] = useState<ImageNativeTranslationPreview | null>(
    null,
  );
  const [resumeReview, setResumeReview] = useState(false);
  const [replaceOcr, setReplaceOcr] = useState(false);
  const [translationOpen, setTranslationOpen] = useState(false);
  const detailsPanel = useRef<HTMLElement>(null);
  const action = useAction();
  const owned = useOwnedFeedback(action.key);
  const adopt = (next: ImageEditorState) => {
    stateRef.current = next;
    setState(next);
  };
  const draft = useDraft<ImageEditorSave[]>("image-editor:" + projectId, {
    autosave: true,
    initial: { saved: editorDraft(initial) },
    report: action.report,
    persist: async (changes) => {
      adopt(
        await api.images.editorSave(
          projectId,
          stateRef.current.revision,
          changes,
          assetIds,
        ),
      );
    },
  });
  const edits = draft.value || editorDraft(state);
  const image = state.images.find((image) => image.assetId === imageId);
  const current = edits.find((image) => image.assetId === imageId);
  const block = current?.blocks.find((block) => block.id === selected[0]);
  const firstSelected = selected[0];
  useEffect(() => {
    if (detailsPanel.current) detailsPanel.current.scrollTop = 0;
  }, [imageId, firstSelected]);
  // The original and the editable copy scroll as one, and open on the box
  // being edited: a large image at 100% otherwise shows empty corners.
  const canvasArea = useRef<HTMLDivElement>(null);
  const focusBox = (block ?? current?.blocks[0])?.box;
  const focusKey = focusBox ? focusBox.join(",") : "";
  useEffect(() => {
    if (!focusKey || !canvasArea.current) return;
    const [x, y, width, height] = focusKey.split(",").map(Number);
    for (const element of canvasArea.current.querySelectorAll<HTMLElement>(
      ".native-editor-canvas-scroll",
    )) {
      element.scrollLeft = (x + width / 2) * zoom - element.clientWidth / 2;
      element.scrollTop = (y + height / 2) * zoom - element.clientHeight / 2;
    }
  }, [imageId, focusKey, zoom, comparison]);
  const busy = action.busy || draft.committing;
  const refreshNative = async () => {
    setNativeState(await api.images.editorTranslationState(projectId));
  };
  const report = useEffectEvent((error: unknown) => action.report(error));
  const nativeRead = useRef(false);
  useEffect(() => {
    if (!translationOpen || busy || draft.dirty || nativeRead.current) return;
    let alive = true;
    nativeRead.current = true;
    void api.images
      .editorTranslationState(projectId)
      .then((next) => {
        if (alive) setNativeState(next);
      })
      .catch((error: unknown) => {
        if (alive) report(error);
      })
      .finally(() => {
        nativeRead.current = false;
      });
    return () => {
      alive = false;
    };
  }, [projectId, observationKey, translationOpen, busy, draft.dirty]);
  const images = useRead(
    image
      ? JSON.stringify([
          projectId,
          imageId,
          image.sourceHash,
          image.candidateHash,
        ])
      : null,
    (signal) =>
      Promise.all([
        imagesApi.pixels(
          projectId,
          image!.assetId,
          "original",
          0,
          () => !signal.aborted,
        ),
        imagesApi.pixels(
          projectId,
          image!.assetId,
          "candidate",
          0,
          () => !signal.aborted,
        ),
      ]),
  );
  const pixels = {
    source: images.value?.[0].url || "",
    candidate: images.value?.[1].url || "",
    error: images.error === undefined ? "" : messageOf(images.error),
  };

  function edit(update: (image: ImageEditorSave) => ImageEditorSave) {
    draft.session.edit((images) =>
      images.map((image) =>
        image.assetId === imageId ? update(image) : image,
      ),
    );
    action.clear();
  }
  function editBlock(update: Partial<ImageTextBlock>, sourceChanged = false) {
    edit((image) => ({
      ...image,
      status: sourceChanged ? "needs_review" : image.status,
      blocks: image.blocks.map((value) =>
        value.id === block?.id ? { ...value, ...update } : value,
      ),
    }));
  }
  function editStyle(update: Partial<ImageTextStyle>) {
    if (block)
      editBlock({ style: { ...block.style, ...update, locked: true } });
  }
  async function operate(
    name: "ocr" | "export" | "import" | "render" | "undo",
    options: Record<string, unknown> = {},
    all = false,
  ) {
    await action.run(
      async () => {
        let failures: string[] = [];
        await draft.session.commit(async () => {
          const scope = all
            ? stateRef.current
            : await api.images.editorState(projectId, [imageId]);
          const next = await api.images.editorAction(
            projectId,
            scope.revision,
            name,
            all ? assetIds : [imageId],
            options,
          );
          // The action scope is smaller than the opened editor, so reopen the
          // complete selection to retain the other images in this view.
          const opened = all
            ? next.state
            : await api.images.editorState(projectId, assetIds);
          adopt(opened);
          onChanged?.();
          if (name === "ocr") {
            setSelected([]);
            setReplaceOcr(false);
          }
          if (name === "export") {
            setTranslationOpen(true);
            await refreshNative();
          }
          failures = Object.values(next.result.errors || {});
          return { saved: editorDraft(opened) };
        });
        if (failures.length) throw new Error(failures.join(" "));
      },
      name === "export"
        ? "Confirmed text exported for the native translator."
        : name === "render"
          ? "Editable image rendered. Review it in Image Manager before applying."
          : name === "undo"
            ? "Original pixels restored; text and boxes retained."
            : "Image work saved.",
      name,
    );
  }
  async function close() {
    await action.run(
      async () => {
        await draft.session.flush();
        onClose();
      },
      "",
      "close",
    );
  }
  async function prepareTranslation(mode: "estimate" | "translate" | "batch") {
    await action.run(
      async () => {
        await draft.session.flush();
        const next = await api.images.editorTranslationPreview(projectId, mode);
        if (mode === "estimate") {
          setNativeState(
            await api.images.editorTranslationStart(
              projectId,
              next.token,
              false,
            ),
          );
          setSelectedRun("");
        } else setPreview(next);
      },
      mode === "estimate" ? "Local estimate started." : "",
      "native:" + mode,
    );
  }
  async function nativeAction(
    name: "stop" | "resume" | "answer" | "export" | "import",
    options: Record<string, unknown> = {},
  ) {
    const job =
      nativeState?.jobs.find((run) => run.id === selectedRun) ||
      nativeState?.job;
    if (!job) return;
    let feedback = "";
    const outcome = await action.run(
      async () => {
        await draft.session.flush();
        const next = await api.images.editorTranslationAction(
          projectId,
          job.id,
          name,
          options,
        );
        setNativeState(next.state);
        setResumeReview(false);
        if (name === "import") {
          const opened = await api.images.editorState(projectId, assetIds);
          adopt(opened);
          draft.session.adopt(editorDraft(opened));
          onChanged?.();
          const counts = next.result.result;
          feedback = `${counts?.applied || 0} translated targets imported · ${(counts?.missing || 0) + (counts?.empty || 0)} unresolved. Source text and boxes retained.`;
        }
        if (name === "export" && next.result.path)
          await window.dazedtl.openFolder("output", next.result.path);
      },
      "",
      "native:" + name,
    );
    if (outcome.ok && feedback) action.succeed(feedback, "native:" + name);
  }
  function addBox(box: ImageTextBlock["box"]) {
    const id = crypto.randomUUID();
    edit((image) => ({
      ...image,
      status: "needs_review",
      blocks: [
        ...image.blocks,
        { id, box, source: "", target: "", angle: 0, skip: false },
      ],
    }));
    setSelected([id]);
    setDrawing(false);
  }
  function mergeBoxes() {
    if (!current || selected.length < 2) return;
    const chosen = current.blocks
      .filter((block) => selected.includes(block.id))
      .sort((a, b) => a.box[1] - b.box[1] || a.box[0] - b.box[0]);
    const left = Math.min(...chosen.map((block) => block.box[0])),
      top = Math.min(...chosen.map((block) => block.box[1]));
    const right = Math.max(
        ...chosen.map((block) => block.box[0] + block.box[2]),
      ),
      bottom = Math.max(...chosen.map((block) => block.box[1] + block.box[3]));
    const merged: ImageTextBlock = {
      id: chosen[0].id,
      box: [left, top, right - left, bottom - top],
      source: chosen.map((block) => block.source).join("\n"),
      target: chosen.every((block) => block.target)
        ? chosen.map((block) => block.target).join("\n")
        : "",
      angle: 0,
      skip: false,
    };
    edit((image) => ({
      ...image,
      status: "needs_review",
      blocks: [
        ...image.blocks.filter((block) => !selected.includes(block.id)),
        merged,
      ],
    }));
    setSelected([merged.id]);
  }
  function splitBox() {
    if (!block || !current) return;
    const sources = block.source.split("\n").filter(Boolean);
    if (sources.length < 2 || sources.length > block.box[3]) return;
    const targets = block.target.split("\n");
    const pieces: ImageTextBlock[] = sources.map((source, index) => {
      const top = Math.floor((block.box[3] * index) / sources.length),
        bottom = Math.floor((block.box[3] * (index + 1)) / sources.length);
      return {
        id: crypto.randomUUID(),
        source,
        target: targets.length === sources.length ? targets[index] : "",
        box: [block.box[0], block.box[1] + top, block.box[2], bottom - top],
        angle: block.angle,
        skip: block.skip,
      };
    });
    edit((image) => ({
      ...image,
      status: "needs_review",
      blocks: [
        ...image.blocks.filter((value) => value.id !== block.id),
        ...pieces,
      ],
    }));
    setSelected(pieces.map((block) => block.id));
  }
  function point(event: React.PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(
        0,
        Math.min(
          image!.width,
          Math.round(
            ((event.clientX - bounds.left) * image!.width) / bounds.width,
          ),
        ),
      ),
      y: Math.max(
        0,
        Math.min(
          image!.height,
          Math.round(
            ((event.clientY - bounds.top) * image!.height) / bounds.height,
          ),
        ),
      ),
    };
  }
  // Estimates report in their row; the picker lists translation runs.
  const runs = (nativeState?.jobs || []).filter(
    (run) => run.mode !== "estimate",
  );
  const job =
    nativeState?.jobs.find((run) => run.id === selectedRun) ||
    (nativeState?.activeId
      ? nativeState.job
      : runs.find((run) => run.id === nativeState?.job?.id) || runs[0]);
  const confirmedImages = edits.filter(
    (image) => image.status === "confirmed",
  ).length;
  const runWaiting = "Wait for the current image run to finish.";
  // Until the saved run state arrives, no step can say what it waits for.
  const checking = "Checking saved image work…";
  const translateBlocked = !nativeState
    ? checking
    : !nativeState.quoteCurrent
      ? nativeState?.quote
        ? "Estimate again after these changes."
        : "Estimate first."
      : !nativeState.providerEnabled
        ? "Provider execution is off for this launch."
        : nativeState.activeId
          ? runWaiting
          : "";
  const stepFeedback = (key: string, pendingText: string) => ({
    feedbackKey: key,
    pending: action.busy && action.key === key,
    pendingText,
    error: action.key === key ? action.error : "",
    notice: action.key === key ? action.notice : "",
  });
  return (
    <Modal
      label="Image Text Editor"
      className="native-image-editor"
      onDismiss={() => {
        void close();
      }}
      dismissible={!busy}
    >
      <DialogHeader
        title="Image Text Editor"
        description="Optional tool · working copies only"
        actions={
          <Button
            disabled={busy}
            onClick={() => {
              void close();
            }}
          >
            Back to Image Manager
          </Button>
        }
      />
      <div className="native-editor-toolbar">
        <label>
          Image
          <select
            aria-label="Editor image"
            value={imageId}
            disabled={busy}
            onChange={(event) => {
              setImageId(event.target.value);
              setSelected([]);
            }}
          >
            {state.images.map((image) => (
              <option key={image.assetId} value={image.assetId}>
                {image.path}
              </option>
            ))}
          </select>
        </label>
        <label>
          Zoom
          <select
            aria-label="Editor zoom"
            value={zoom}
            onChange={(event) => setZoom(Number(event.target.value))}
          >
            {[0.25, 0.5, 1, 1.5, 2, 3].map((value) => (
              <option key={value} value={value}>
                {value * 100}%
              </option>
            ))}
          </select>
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={comparison}
            onChange={(event) => setComparison(event.target.checked)}
          />
          Compare
        </label>
        <Button
          disabled={busy || !image}
          variant={drawing ? "primary" : "default"}
          onClick={() => {
            pointer.current = null;
            setDrag(null);
            setDrawing(!drawing);
          }}
        >
          {drawing ? (
            "Cancel drawing"
          ) : (
            <>
              <Plus size={16} aria-hidden="true" />
              Add box
            </>
          )}
        </Button>
        <Button
          disabled={busy || !selected.length}
          onClick={() => {
            edit((image) => ({
              ...image,
              status: "needs_review",
              blocks: image.blocks.filter(
                (block) => !selected.includes(block.id),
              ),
            }));
            setSelected([]);
          }}
        >
          Delete box{selected.length > 1 ? "es" : ""}
        </Button>
        <Button disabled={busy || selected.length < 2} onClick={mergeBoxes}>
          Merge boxes
        </Button>
        <Button
          disabled={
            busy || selected.length !== 1 || !block?.source.includes("\n")
          }
          onClick={splitBox}
        >
          Split lines
        </Button>
      </div>
      <div className="native-editor-body">
        <div className="native-editor-workspace">
          {image && current ? (
            <>
              {/* The Image menu above names the file. */}
              {/* The drawing hint shares the caption row, so starting to
                  draw never moves the image under the pointer. */}
              <div className="native-editor-image-caption">
                <span>
                  {image.width} × {image.height} · {current.blocks.length}{" "}
                  {current.blocks.length === 1 ? "box" : "boxes"}
                </span>
                {drawing && (
                  <strong role="status">
                    Drag a box around source text on the original image.
                  </strong>
                )}
              </div>
              <Message message={pixels.error || image.error} />
              <div
                ref={canvasArea}
                className={`native-editor-canvases ${comparison ? "native-editor-compare" : ""}`}
              >
                <figure>
                  <figcaption>Original</figcaption>
                  <div
                    className="native-editor-canvas-scroll"
                    onScroll={(event) => syncScroll(event.currentTarget)}
                  >
                    <div
                      className="native-editor-pixels"
                      style={{
                        width: image.width * zoom,
                        height: image.height * zoom,
                      }}
                    >
                      {pixels.source ? (
                        <img
                          src={pixels.source}
                          alt={`Original ${image.path}`}
                          draggable={false}
                        />
                      ) : (
                        <span role="status">Loading original…</span>
                      )}
                      <svg
                        viewBox={`0 0 ${image.width} ${image.height}`}
                        aria-label="Editable text boxes"
                        className={drawing ? "native-editor-draw" : ""}
                        onPointerDown={(event) => {
                          if (drawing && !busy) {
                            pointer.current = point(event);
                            setDrag({
                              ...pointer.current,
                              x2: pointer.current.x,
                              y2: pointer.current.y,
                            });
                            event.currentTarget.setPointerCapture(
                              event.pointerId,
                            );
                          }
                        }}
                        onPointerMove={(event) => {
                          if (pointer.current) {
                            const next = point(event);
                            setDrag({
                              ...pointer.current,
                              x2: next.x,
                              y2: next.y,
                            });
                          }
                        }}
                        onPointerUp={(event) => {
                          if (!pointer.current) return;
                          const start = pointer.current,
                            end = point(event);
                          pointer.current = null;
                          setDrag(null);
                          const width = Math.abs(end.x - start.x),
                            height = Math.abs(end.y - start.y);
                          if (width > 1 && height > 1)
                            addBox([
                              Math.min(start.x, end.x),
                              Math.min(start.y, end.y),
                              width,
                              height,
                            ]);
                        }}
                        onPointerCancel={() => {
                          pointer.current = null;
                          setDrag(null);
                        }}
                      >
                        {current.blocks.map((block, index) => (
                          <g
                            key={block.id}
                            className={
                              selected.includes(block.id)
                                ? "native-editor-box selected"
                                : "native-editor-box"
                            }
                          >
                            <rect
                              x={block.box[0]}
                              y={block.box[1]}
                              width={block.box[2]}
                              height={block.box[3]}
                              tabIndex={0}
                              role="button"
                              aria-label={`Text box ${index + 1}`}
                              onClick={(event) => {
                                if (drawing) return;
                                setSelected(
                                  event.shiftKey
                                    ? selected.includes(block.id)
                                      ? selected.filter((id) => id !== block.id)
                                      : [...selected, block.id]
                                    : [block.id],
                                );
                              }}
                              onKeyDown={(event) => {
                                if (
                                  event.key === "Enter" ||
                                  event.key === " "
                                ) {
                                  event.preventDefault();
                                  setSelected([block.id]);
                                }
                              }}
                            />
                            <text
                              x={block.box[0] + 3}
                              y={Math.max(14, block.box[1] - 3)}
                            >
                              {index + 1}
                            </text>
                          </g>
                        ))}
                        {drag && (
                          <rect
                            className="native-editor-drag"
                            x={Math.min(drag.x, drag.x2)}
                            y={Math.min(drag.y, drag.y2)}
                            width={Math.abs(drag.x2 - drag.x)}
                            height={Math.abs(drag.y2 - drag.y)}
                          />
                        )}
                      </svg>
                    </div>
                  </div>
                </figure>
                {comparison && (
                  <figure>
                    <figcaption>Editable copy</figcaption>
                    <div
                      className="native-editor-canvas-scroll"
                      onScroll={(event) => syncScroll(event.currentTarget)}
                    >
                      <div
                        className="native-editor-pixels"
                        style={{
                          width: image.width * zoom,
                          height: image.height * zoom,
                        }}
                      >
                        {pixels.candidate ? (
                          <img
                            src={pixels.candidate}
                            alt={`Edited ${image.path}`}
                          />
                        ) : (
                          <span>No editable preview.</span>
                        )}
                      </div>
                    </div>
                  </figure>
                )}
              </div>
              {image.notes.length > 0 && (
                <details className="native-editor-notes">
                  <summary>Render notes ({image.notes.length})</summary>
                  <ul>
                    {image.notes.map((note, index) => (
                      <li key={index}>{note.message}</li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          ) : (
            <p>Select prepared images in Image Manager to begin.</p>
          )}
        </div>
        <aside className="native-editor-details" ref={detailsPanel}>
          <section>
            <h3>Text boxes</h3>
            {!current?.blocks.length && (
              <p>Add a box or read text with installed local OCR.</p>
            )}
            <div className="native-editor-box-list">
              {current?.blocks.map((block, index) => (
                <Button
                  key={block.id}
                  variant={selected.includes(block.id) ? "primary" : "quiet"}
                  onClick={() => setSelected([block.id])}
                >
                  {index + 1}. {block.source || "Empty box"}
                </Button>
              ))}
            </div>
            <Button
              disabled={busy || !image || !state.localOcr.available}
              onClick={() =>
                current?.blocks.length
                  ? setReplaceOcr(true)
                  : void operate("ocr")
              }
            >
              Read text locally
            </Button>
            <p className="muted">{state.localOcr.detail}</p>
          </section>
          {block && (
            <section className="native-editor-block-form">
              <h3>Box {current!.blocks.indexOf(block) + 1}</h3>
              <div className="native-editor-box-fields">
                {["X", "Y", "Width", "Height"].map((label, index) => (
                  <label key={label}>
                    {label}
                    <input
                      type="number"
                      aria-label={`Box ${label}`}
                      min={index < 2 ? 0 : 1}
                      max={index % 2 === 0 ? image?.width : image?.height}
                      value={block.box[index]}
                      disabled={busy}
                      onChange={(event) => {
                        const next = [...block.box] as ImageTextBlock["box"];
                        next[index] = Number(event.target.value);
                        editBlock({ box: next }, true);
                      }}
                    />
                  </label>
                ))}
              </div>
              <label>
                Source text
                <textarea
                  aria-label="Image source text"
                  value={block.source}
                  disabled={busy}
                  rows={3}
                  onChange={(event) =>
                    editBlock({ source: event.target.value }, true)
                  }
                />
              </label>
              <label>
                Translation
                <textarea
                  aria-label="Image target text"
                  value={block.target}
                  disabled={busy}
                  rows={3}
                  onChange={(event) =>
                    editBlock({ target: event.target.value })
                  }
                />
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={block.skip}
                  disabled={busy}
                  onChange={(event) =>
                    editBlock({ skip: event.target.checked })
                  }
                />
                Leave this box unchanged
              </label>
              <details open>
                <summary>Text style</summary>
                <div className="native-editor-style-fields">
                  <label>
                    Font
                    <select
                      aria-label="Image font"
                      value={block.style?.font || ""}
                      disabled={busy}
                      onChange={(event) =>
                        editStyle({ font: event.target.value })
                      }
                    >
                      <option value="">System default</option>
                      {(state.fonts || []).map((font) => (
                        <option key={font.id} value={font.id}>
                          {font.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {/* The renderer sizes type by its capital height, which
                      is what the measurement reads off the original. */}
                  <label>
                    Letter height (px)
                    <input
                      aria-label="Image letter height in pixels"
                      type="number"
                      min={1}
                      max={512}
                      value={block.style?.cap_height || 12}
                      disabled={busy}
                      onChange={(event) =>
                        editStyle({ cap_height: Number(event.target.value) })
                      }
                    />
                  </label>
                  <label>
                    Alignment
                    <select
                      aria-label="Image text alignment"
                      value={block.style?.align || "center"}
                      disabled={busy}
                      onChange={(event) =>
                        editStyle({
                          align: event.target.value as ImageTextStyle["align"],
                        })
                      }
                    >
                      {["left", "center", "right"].map((value) => (
                        <option key={value}>{value}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Text colour
                    <input
                      aria-label="Image text colour"
                      type="color"
                      value={colourHex(block.style?.text_color)}
                      disabled={busy}
                      onChange={(event) =>
                        editStyle({
                          text_color: colourChannels(event.target.value),
                        })
                      }
                    />
                  </label>
                  <label>
                    Outline
                    <input
                      aria-label="Image outline size"
                      type="number"
                      min={0}
                      max={64}
                      value={block.style?.outline_width || 0}
                      disabled={busy}
                      onChange={(event) =>
                        editStyle({
                          outline_width: Number(event.target.value),
                          outline_color: block.style?.outline_color || [
                            0, 0, 0, 255,
                          ],
                        })
                      }
                    />
                  </label>
                  <label>
                    Repair background
                    <select
                      aria-label="Image background repair"
                      value={block.style?.background || "keep"}
                      disabled={busy}
                      onChange={(event) => {
                        const background = event.target.value;
                        if (!isBackgroundRepair(background)) return;
                        editStyle({
                          background,
                          ...(background === "solid"
                            ? { fill: block.style?.fill || [0, 0, 0, 255] }
                            : {}),
                        });
                      }}
                    >
                      {Object.entries(backgroundRepairs).map(
                        ([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                  {block.style?.background === "solid" && (
                    <label>
                      Fill colour
                      <input
                        aria-label="Image background fill"
                        type="color"
                        value={colourHex(block.style.fill)}
                        disabled={busy}
                        onChange={(event) =>
                          editStyle({
                            fill: colourChannels(event.target.value),
                          })
                        }
                      />
                    </label>
                  )}
                </div>
              </details>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={current?.status === "confirmed"}
                  disabled={busy}
                  onChange={(event) =>
                    edit((image) => ({
                      ...image,
                      status: event.target.checked
                        ? "confirmed"
                        : "needs_review",
                    }))
                  }
                />
                Source text and boxes confirmed
              </label>
            </section>
          )}
          <section className="native-editor-native-translation">
            <Button
              variant="link"
              onClick={() => setTranslationOpen(!translationOpen)}
            >
              {translationOpen ? "Hide API translation" : "Translate with API…"}
            </Button>
            {translationOpen && (
              <>
                {/* Each step says why it waits, beside its own button; the
                    saved state's error is why no export is current. */}
                <ActionList compact>
                  <ActionRow
                    title="Export text"
                    description={
                      nativeState?.current
                        ? `${nativeState.current.count} text ${nativeState.current.count === 1 ? "region" : "regions"} exported`
                        : "Confirmed source text from the open images."
                    }
                  >
                    <ActionControl
                      label="Export confirmed text"
                      disabled={busy || !confirmedImages}
                      disabledReason={
                        confirmedImages
                          ? ""
                          : "Confirm the source text and boxes first."
                      }
                      {...stepFeedback("export", "Exporting…")}
                      onClick={() => {
                        void operate("export", {}, true);
                      }}
                    />
                  </ActionRow>
                  <ActionRow
                    title="Estimate"
                    description={
                      nativeState?.quoteCurrent && nativeState.quote?.estimate
                        ? estimateSummary(nativeState.quote.estimate)
                        : nativeState?.quote
                          ? "Estimate again after text, scope, guidance or settings changes."
                          : "A local estimate; nothing is sent."
                    }
                  >
                    <ActionControl
                      label="Estimate"
                      disabled={
                        busy || !nativeState?.current || !!nativeState.activeId
                      }
                      disabledReason={
                        !nativeState
                          ? checking
                          : !nativeState.current
                            ? nativeState.error ||
                              "Export confirmed text first."
                            : nativeState.activeId
                              ? runWaiting
                              : ""
                      }
                      {...stepFeedback("native:estimate", "Estimating…")}
                      onClick={() => {
                        void prepareTranslation("estimate");
                      }}
                    />
                  </ActionRow>
                  <ActionRow
                    title="Translate"
                    description="Review its cost before paid work starts."
                  >
                    <ActionControl
                      label="Review live translation"
                      disabled={busy || !!translateBlocked}
                      disabledReason={translateBlocked}
                      {...stepFeedback("native:translate", "Preparing review…")}
                      onClick={() => {
                        void prepareTranslation("translate");
                      }}
                    />
                    {nativeState?.batchSupported && (
                      <ActionControl
                        label="Review Batch"
                        disabled={busy || !!translateBlocked}
                        {...stepFeedback("native:batch", "Preparing review…")}
                        onClick={() => {
                          void prepareTranslation("batch");
                        }}
                      />
                    )}
                  </ActionRow>
                </ActionList>
                {!!runs.length && (
                  <label>
                    Saved image run
                    <select
                      aria-label="Saved image run"
                      value={job?.id || ""}
                      onChange={(event) => setSelectedRun(event.target.value)}
                    >
                      {runs.map((run) => (
                        <option key={run.id} value={run.id}>
                          {run.mode === "batch" ? "Batch" : "Live"} ·{" "}
                          {run.model} · {sentence(run.status)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {/* A finished estimate reports through its row above. */}
                {job &&
                  !(
                    job.mode === "estimate" && nativeState?.activeId !== job.id
                  ) && (
                    <>
                      <JobStatus
                        job={{
                          label:
                            job.mode === "estimate"
                              ? "Image text estimate"
                              : "Image text translation",
                          status: job.status,
                          message: job.message,
                        }}
                      />
                      {["failed", "interrupted"].includes(job.status) &&
                        !!job.log?.length && (
                          <ExpandableText
                            text={job.log.join("\n")}
                            label="Run log"
                            tail
                          />
                        )}
                      {nativeState?.activeId === job.id && job.progress && (
                        <progress
                          value={job.progress.current}
                          max={job.progress.total || 1}
                        />
                      )}
                      {job.approval && (
                        <div className="native-editor-approval">
                          <strong>Review provider Batch submission</strong>
                          <Costs value={job.approval.detail} />
                          <Button
                            disabled={busy}
                            onClick={() => {
                              void nativeAction("answer", {
                                token: job.approval!.token,
                                approved: true,
                              });
                            }}
                          >
                            Submit Batch
                          </Button>
                          <Button
                            disabled={busy}
                            onClick={() => {
                              void nativeAction("answer", {
                                token: job.approval!.token,
                                approved: false,
                              });
                            }}
                          >
                            Decline
                          </Button>
                        </div>
                      )}
                      {job.status === "complete" && job.mode !== "estimate" && (
                        <div className="actions">
                          <Button
                            disabled={busy}
                            onClick={() => {
                              void nativeAction("import");
                            }}
                          >
                            {job.imported
                              ? "Import targets again"
                              : "Import translated targets"}
                          </Button>
                          <Button
                            disabled={busy}
                            onClick={() => {
                              void nativeAction("export");
                            }}
                          >
                            Save output copy
                          </Button>
                        </div>
                      )}
                    </>
                  )}
                <div className="actions">
                  {job && nativeState?.activeId === job.id ? (
                    <Button
                      disabled={busy}
                      onClick={() => {
                        void nativeAction("stop");
                      }}
                    >
                      {job.mode === "batch"
                        ? "Pause monitoring"
                        : "Stop after current work"}
                    </Button>
                  ) : job &&
                    ["failed", "stopped", "interrupted", "canceled"].includes(
                      job.status,
                    ) ? (
                    <Button
                      disabled={busy}
                      onClick={() =>
                        job.mode === "estimate"
                          ? void nativeAction("resume", { approved: false })
                          : setResumeReview(true)
                      }
                    >
                      Resume saved run
                    </Button>
                  ) : null}
                  {/* Only an existing run has a saved state to read again. */}
                  {!!runs.length && (
                    <Button
                      disabled={busy}
                      onClick={() => {
                        void action.run(
                          refreshNative,
                          "Saved native run refreshed.",
                        );
                      }}
                    >
                      Refresh saved run
                    </Button>
                  )}
                </div>
              </>
            )}
          </section>
        </aside>
      </div>
      <ActionBar
        feedback={
          action.error && !owned ? (
            <Message message={action.error} />
          ) : (
            // Text and boxes save as they change; leaving flushes the rest.
            <Feedback
              pending={draft.dirty || draft.committing}
              notice={(!owned && action.notice) || "Saved"}
            />
          )
        }
      >
        {/* Undo returns the copy to its original pixels, so it appears
            while the copy differs from the game image; later text edits
            leave a render in place. */}
        {!!image?.changed && (
          <Button
            disabled={busy}
            onClick={() => {
              void operate("undo");
            }}
          >
            Undo render
          </Button>
        )}
        <ActionControl
          label="Render image"
          variant="primary"
          pending={action.key === "render" && action.busy}
          disabled={
            busy || !current?.blocks.length || current.status !== "confirmed"
          }
          disabledReason={
            !current?.blocks.length
              ? "Add a text box first."
              : current.status !== "confirmed"
                ? "Confirm the source text and boxes first."
                : ""
          }
          onClick={() => {
            setComparison(true);
            void operate("render");
          }}
        />
      </ActionBar>
      {replaceOcr && (
        <Modal
          label="Replace OCR boxes"
          size="sm"
          className="native-editor-confirm"
          onDismiss={() => setReplaceOcr(false)}
        >
          <DialogHeader
            title="Replace this image’s boxes?"
            description="Local OCR replaces its retained source text, translations and boxes. Other images remain saved."
          />
          <ActionBar feedback={<Message message={action.error} />}>
            <Button disabled={busy} onClick={() => setReplaceOcr(false)}>
              Cancel
            </Button>
            <Button
              disabled={busy}
              onClick={() => {
                void operate("ocr", { replaceConfirmed: true });
              }}
            >
              Read text locally
            </Button>
          </ActionBar>
        </Modal>
      )}
      {(preview || resumeReview) && (
        <Modal
          label="Review native image translation"
          size="sm"
          className="native-editor-confirm"
          dismissible={!busy}
          onDismiss={() => {
            setPreview(null);
            setResumeReview(false);
          }}
        >
          <DialogHeader
            title={
              resumeReview
                ? "Resume saved image translation"
                : "Translate confirmed image text"
            }
            description={
              preview
                ? `${preview.count} text regions · ${preview.assetIds.length} images · ${preview.mode === "batch" ? "Provider Batch" : "Live API"}`
                : "Continue using this run’s frozen scope and settings."
            }
          />
          <DialogBody>
            <p>
              {preview?.configuration.model || job?.model} ·{" "}
              {preview?.configuration.language ||
                job?.imageConfiguration?.language}
            </p>
            {(preview?.configuration.endpoint ||
              job?.imageConfiguration?.endpoint) && (
              <p className="path">
                {preview?.configuration.endpoint ||
                  job?.imageConfiguration?.endpoint}
              </p>
            )}
            <Costs value={preview?.estimate || job?.estimate || {}} />
            <p>
              Approval uses the saved provider and can incur charges. Applying
              images remains a separate reviewed action.
            </p>
          </DialogBody>
          <ActionBar feedback={<Message message={action.error} />}>
            <Button
              disabled={busy}
              onClick={() => {
                setPreview(null);
                setResumeReview(false);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              pending={action.busy}
              onClick={() => {
                if (resumeReview) {
                  void nativeAction("resume", { approved: true });
                  return;
                }
                if (preview)
                  void action.run(
                    async () => {
                      setNativeState(
                        await api.images.editorTranslationStart(
                          projectId,
                          preview.token,
                          true,
                        ),
                      );
                      setSelectedRun("");
                      setPreview(null);
                    },
                    "Saved image translation started.",
                    "native:start",
                  );
              }}
            >
              {resumeReview ? "Resume paid run" : "Start translation"}
            </Button>
          </ActionBar>
        </Modal>
      )}
    </Modal>
  );
}

const money = (value: unknown) => "$" + Number(value).toFixed(5);
/** One line for a finished estimate: requests and the Live and Batch prices. */
function estimateSummary(value: Record<string, unknown>) {
  const requests = Number(value.requests ?? value.request_count ?? 0);
  return [
    `${requests.toLocaleString()} ${requests === 1 ? "request" : "requests"}`,
    typeof value.live_cost === "number" && `Live ${money(value.live_cost)}`,
    typeof value.batch_cost === "number" && `Batch ${money(value.batch_cost)}`,
  ]
    .filter(Boolean)
    .join(" · ");
}
function Costs({ value }: { value: Record<string, unknown> }) {
  // Cache variants only matter when they differ from each other.
  const sameBatch = value.batch_cached_cost === value.batch_nocache_cost;
  return (
    <dl className="native-editor-costs">
      {[
        ["requests", "Requests"],
        ["request_count", "Requests"],
        ["input_tokens", "Input tokens"],
        ["output_tokens", "Estimated output tokens"],
        ["live_cost", "Live estimate"],
        ["batch_cost", "Batch estimate"],
        ["batch_cached_cost", "Batch with cache"],
        ["batch_nocache_cost", "Batch without cache"],
      ]
        .filter(
          ([key]) =>
            typeof value[key] === "number" &&
            !(
              sameBatch &&
              ["batch_cached_cost", "batch_nocache_cost"].includes(key)
            ),
        )
        .map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {key.includes("cost")
                ? money(value[key])
                : Number(value[key]).toLocaleString()}
            </dd>
          </div>
        ))}
    </dl>
  );
}
