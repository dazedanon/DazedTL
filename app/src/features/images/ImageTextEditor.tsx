import { useEffect, useRef, useState } from "react";
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
} from "../../api/imageEditorContracts";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { Button } from "../../ui/Button";
import { ActionBar } from "../../ui/ActionBar";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { JobStatus } from "../../ui/JobStatus";
import { ExpandableText } from "../../ui/ExpandableText";
import "./image-editor.css";

export interface ImageTextEditorProps {
  projectId: string;
  assetIds: string[];
  onClose: () => void;
  onChanged?: () => void;
  observationKey?: unknown;
}

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
  const [loaded, setLoaded] = useState<{
    projectId: string;
    scopeKey: string;
    state: ImageEditorState;
  } | null>(null);
  const generation = useRef(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const ticket = ++generation.current;
    setLoaded(null);
    setError("");
    void api.images
      .editorState(props.projectId, props.assetIds)
      .then((next) => {
        if (alive && ticket === generation.current)
          setLoaded({ projectId: props.projectId, scopeKey, state: next });
      })
      .catch((error) => {
        if (alive && ticket === generation.current) setError(messageOf(error));
      });
    return () => {
      alive = false;
      generation.current++;
    };
  }, [props.projectId, scopeKey]);
  const initial =
    loaded?.projectId === props.projectId && loaded.scopeKey === scopeKey
      ? loaded.state
      : null;
  if (!initial)
    return (
      <Modal
        label="Image Text Editor"
        className="native-image-editor"
        onDismiss={props.onClose}
      >
        <header className="native-editor-heading">
          <h2>Image Text Editor</h2>
          <Button onClick={props.onClose}>Back to Image Manager</Button>
        </header>
        <div className="native-editor-empty">
          <Message message={error} />
          <p role="status">
            {error
              ? "The selected images could not open."
              : "Loading saved text and image work…"}
          </p>
          {error && (
            <Button
              onClick={() => {
                const ticket = ++generation.current;
                setError("");
                void api.images
                  .editorState(props.projectId, props.assetIds)
                  .then((next) => {
                    if (ticket === generation.current)
                      setLoaded({
                        projectId: props.projectId,
                        scopeKey,
                        state: next,
                      });
                  })
                  .catch((error) => {
                    if (ticket === generation.current)
                      setError(messageOf(error));
                  });
              }}
            >
              Retry
            </Button>
          )}
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
  const [pixels, setPixels] = useState({
    source: "",
    candidate: "",
    error: "",
  });
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
  const adopt = (next: ImageEditorState) => {
    stateRef.current = next;
    setState(next);
  };
  const draft = useDraft<ImageEditorSave[]>("image-editor:" + projectId, {
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
  useEffect(() => {
    if (detailsPanel.current) detailsPanel.current.scrollTop = 0;
  }, [imageId, selected[0]]);
  const busy = action.busy || draft.committing;
  const refreshNative = async () => {
    setNativeState(await api.images.editorTranslationState(projectId));
  };
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
      .catch((error) => {
        if (alive) action.report(error);
      })
      .finally(() => {
        nativeRead.current = false;
      });
    return () => {
      alive = false;
    };
  }, [projectId, observationKey, translationOpen, busy, draft.dirty]);
  useEffect(() => {
    if (!image) return;
    let alive = true;
    setPixels({ source: "", candidate: "", error: "" });
    void Promise.all([
      imagesApi.pixels(projectId, image.assetId, "original", 0, () => alive),
      imagesApi.pixels(projectId, image.assetId, "candidate", 0, () => alive),
    ])
      .then(([source, candidate]) => {
        if (alive)
          setPixels({
            source: source.url || "",
            candidate: candidate.url || "",
            error: "",
          });
      })
      .catch((error) => {
        if (alive)
          setPixels({ source: "", candidate: "", error: messageOf(error) });
      });
    return () => {
      alive = false;
    };
  }, [projectId, imageId, image?.sourceHash, image?.candidateHash]);

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
  const job =
    nativeState?.jobs.find((run) => run.id === selectedRun) || nativeState?.job;
  return (
    <Modal
      label="Image Text Editor"
      className="native-image-editor"
      onDismiss={() => {
        void close();
      }}
      dismissible={!busy}
    >
      <header className="native-editor-heading">
        <div>
          <h2>Image Text Editor</h2>
          <span className="muted">Optional tool · working copies only</span>
        </div>
        <Button
          disabled={busy}
          onClick={() => {
            void close();
          }}
        >
          Back to Image Manager
        </Button>
      </header>
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
          {drawing ? "Cancel drawing" : "Add box"}
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
              <div className="native-editor-image-caption">
                <strong title={image.path}>{image.path}</strong>
                <span>
                  {image.width} × {image.height} · {current.blocks.length}{" "}
                  {current.blocks.length === 1 ? "box" : "boxes"}
                </span>
              </div>
              <Message message={pixels.error || image.error} />
              {drawing && (
                <p role="status">
                  Drag a box around source text on the original image.
                </p>
              )}
              <div
                className={`native-editor-canvases ${comparison ? "native-editor-compare" : ""}`}
              >
                <figure>
                  <figcaption>Original</figcaption>
                  <div className="native-editor-canvas-scroll">
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
                    <div className="native-editor-canvas-scroll">
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
                  <label>
                    Size
                    <input
                      aria-label="Image font size"
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
                      onChange={(event) =>
                        editStyle({
                          background: event.target.value,
                          ...(event.target.value === "solid"
                            ? { fill: block.style?.fill || [0, 0, 0, 255] }
                            : {}),
                        })
                      }
                    >
                      <option value="keep">Leave pixels</option>
                      <option value="transparent">
                        Clear text to transparent
                      </option>
                      <option value="solid">Solid colour</option>
                      <option value="vgradient">Vertical gradient</option>
                      <option value="hgradient">Horizontal gradient</option>
                      <option value="patch">Clone clean strip</option>
                      <option value="inpaint">Local OpenCV repair</option>
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
              variant="quiet"
              onClick={() => setTranslationOpen(!translationOpen)}
            >
              {translationOpen
                ? "Hide native translation"
                : "Native translation…"}
            </Button>
            {translationOpen && (
              <>
                <p>
                  Export confirmed text, estimate, then review paid work using
                  the saved provider.
                </p>
                <Button
                  disabled={busy}
                  onClick={() => {
                    void operate("export", {}, true);
                  }}
                >
                  Export confirmed text
                </Button>
                <Message message={nativeState?.error || ""} />
                {nativeState?.current && (
                  <p className="muted">
                    {nativeState.current.count} text regions ·{" "}
                    {nativeState.current.configuration.model}
                  </p>
                )}
                <div className="actions">
                  <Button
                    disabled={
                      busy || !nativeState?.current || !!nativeState.activeId
                    }
                    onClick={() => {
                      void prepareTranslation("estimate");
                    }}
                  >
                    Estimate
                  </Button>
                  <Button
                    disabled={
                      busy ||
                      !nativeState?.quoteCurrent ||
                      !nativeState.providerEnabled ||
                      !!nativeState.activeId
                    }
                    onClick={() => {
                      void prepareTranslation("translate");
                    }}
                  >
                    Review live translation
                  </Button>
                  {nativeState?.batchSupported && (
                    <Button
                      disabled={
                        busy ||
                        !nativeState.quoteCurrent ||
                        !nativeState.providerEnabled ||
                        !!nativeState.activeId
                      }
                      onClick={() => {
                        void prepareTranslation("batch");
                      }}
                    >
                      Review Batch
                    </Button>
                  )}
                </div>
                {nativeState?.quote?.estimate && (
                  <Costs value={nativeState.quote.estimate} />
                )}
                {nativeState?.quote && !nativeState.quoteCurrent && (
                  <p className="muted">
                    Estimate needs refreshing after text, scope, guidance or
                    settings changes.
                  </p>
                )}
                {!!nativeState?.jobs.length && (
                  <label>
                    Saved image run
                    <select
                      aria-label="Saved image run"
                      value={job?.id || ""}
                      onChange={(event) => setSelectedRun(event.target.value)}
                    >
                      {nativeState.jobs.map((run) => (
                        <option key={run.id} value={run.id}>
                          {run.mode} · {run.model} · {run.status}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {job && (
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
                </div>
              </>
            )}
          </section>
        </aside>
      </div>
      <ActionBar
        feedback={
          <>
            <Message message={action.error} />
            {action.notice && <span role="status">{action.notice}</span>}
            {!action.error && !action.notice && (
              <span role="status">
                {draft.committing
                  ? "Saving…"
                  : "Text and boxes save automatically."}
              </span>
            )}
          </>
        }
      >
        <Button
          disabled={busy}
          onClick={() => {
            void action.run(
              async () => {
                await draft.session.flush();
              },
              "Text and boxes saved.",
              "save",
            );
          }}
        >
          Save text
        </Button>
        <Button
          disabled={busy || !image}
          onClick={() => {
            void operate("undo");
          }}
        >
          Undo render
        </Button>
        <Button
          variant="primary"
          pending={action.key === "render" && action.busy}
          disabled={
            busy || !current?.blocks.length || current.status !== "confirmed"
          }
          onClick={() => {
            setComparison(true);
            void operate("render");
          }}
        >
          Render image
        </Button>
      </ActionBar>
      {replaceOcr && (
        <Modal
          label="Replace OCR boxes"
          className="native-editor-confirm"
          onDismiss={() => setReplaceOcr(false)}
        >
          <h2>Replace this image’s boxes?</h2>
          <p>
            Local OCR replaces its retained source text, translations and boxes.
            Other images remain saved.
          </p>
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
          className="native-editor-confirm"
          dismissible={!busy}
          onDismiss={() => {
            setPreview(null);
            setResumeReview(false);
          }}
        >
          <h2>
            {resumeReview
              ? "Resume saved image translation"
              : "Translate confirmed image text"}
          </h2>
          <p>
            {preview
              ? `${preview.count} text regions · ${preview.assetIds.length} images · ${preview.mode === "batch" ? "Provider Batch" : "Live API"}`
              : "Continue using this run’s frozen scope and settings."}
          </p>
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

function Costs({ value }: { value: Record<string, unknown> }) {
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
        .filter(([key]) => typeof value[key] === "number")
        .map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {key.includes("cost")
                ? "$" + Number(value[key]).toFixed(5)
                : Number(value[key]).toLocaleString()}
            </dd>
          </div>
        ))}
    </dl>
  );
}
