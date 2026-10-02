import { useEffect, useState } from "react";
import type { ImageAsset, ImagePixels } from "../../api/imageContracts";
import { imagesApi } from "../../api/images";
import { messageOf } from "../../api/errors";
import { Button } from "../../ui/Button";
import { Modal } from "../../ui/Modal";
import { ActionBar } from "../../ui/ActionBar";
import { Message } from "../../ui/Feedback";
import { imageClassificationLabels, imageStatus } from "./imageSelection";

export function ImageCompare({ projectId, asset, busy, error, notice, onDismiss, onAction }: {
  projectId: string; asset: ImageAsset; busy: boolean; error: string; notice: string; onDismiss: () => void;
  onAction: (action: string, options?: Record<string, unknown>) => Promise<void>;
}) {
  const [source, setSource] = useState<ImagePixels | null>(null);
  const [candidate, setCandidate] = useState<ImagePixels | null>(null);
  const [loadError, setLoadError] = useState("");
  const [zoom, setZoom] = useState(0);
  const [background, setBackground] = useState("checker");
  const [comment, setComment] = useState("");
  useEffect(() => {
    let alive = true;
    setSource(null); setCandidate(null); setLoadError("");
    void Promise.all([imagesApi.pixels(projectId, asset.id, "original", 0, () => alive), asset.candidateHash ? imagesApi.pixels(projectId, asset.id, "candidate", 0, () => alive) : Promise.resolve(null)]).then(([original, edited]) => {
      if (alive) { setSource(original); setCandidate(edited); }
    }).catch((error) => { if (alive) setLoadError(messageOf(error)); });
    return () => { alive = false; };
  }, [projectId, asset.id, asset.sourceHash, asset.candidateHash]);
  return <Modal label={`Compare ${asset.filename}`} className="image-compare-modal" dismissible={!busy} onDismiss={onDismiss}>
    <header className="image-modal-heading"><div><p>{asset.path}</p><h2>Compare images</h2></div><Button disabled={busy} onClick={onDismiss}>Close</Button></header>
    <div className="image-compare-toolbar"><span className="image-review-status">{imageStatus(asset)}</span><label>Zoom<select aria-label="Image zoom" value={zoom} onChange={(event) => setZoom(Number(event.target.value))}>{[0, 0.25, 0.5, 1, 2, 4].map((value) => <option key={value} value={value}>{value ? `${value * 100}%` : "Fit"}</option>)}</select></label><label>Background<select aria-label="Image background" value={background} onChange={(event) => setBackground(event.target.value)}><option value="checker">Transparency</option><option value="dark">Dark</option><option value="light">Light</option></select></label></div>
    <div className="image-compare-body"><Message message={loadError} />
      <div className="image-comparison"><figure><figcaption>Original {source && <span>{source.width} × {source.height} · {source.mode}</span>}</figcaption><div className={`image-comparison-canvas image-background-${background}`}>{source ? <img src={source.url} alt={`Original ${asset.filename}`} style={zoom ? { width: source.width * zoom, height: source.height * zoom } : { width: "100%", height: "100%" }} /> : <p>Loading original…</p>}</div></figure>
      <figure><figcaption>Edited {candidate && <span>{candidate.width} × {candidate.height} · {candidate.mode}</span>}</figcaption><div className={`image-comparison-canvas image-background-${background}`}>{candidate ? <img src={candidate.url} alt={`Edited ${asset.filename}`} style={zoom ? { width: candidate.width * zoom, height: candidate.height * zoom } : { width: "100%", height: "100%" }} /> : <p>{asset.candidateHash ? "Loading edited image…" : "No edited copy yet."}</p>}</div></figure></div>
      {(asset.state === "blocked" || asset.sourceIssue) ? <Message message={asset.blockedReason || asset.sourceIssue || ""} /> : asset.blockedReason ? <p className="muted">{asset.blockedReason}</p> : null}
      <details className="image-details"><summary>Details and validation</summary><dl><dt>Discovery</dt><dd>{imageClassificationLabels[asset.classification] || asset.classification}</dd><dt>Reason</dt><dd>{asset.reason || "No saved finding."}</dd><dt>AI review evidence</dt><dd>{asset.reviewEvidence || "No saved AI review."}</dd><dt>Source hash</dt><dd><code>{asset.sourceHash}</code></dd><dt>Candidate hash</dt><dd><code>{asset.candidateHash || "None"}</code></dd><dt>Runtime destination</dt><dd>{asset.destination}</dd></dl>{asset.checks && Object.keys(asset.checks).length ? <ul>{Object.entries(asset.checks).map(([name, passed]) => <li key={name}><strong>{name}: {asset.candidateHash ? passed ? "Passed" : "Failed" : "Pending"}</strong></li>)}</ul> : <p>Apply rechecks the source and candidate. No detailed validation report is available for this image.</p>}</details>
      <label className="image-revision-comment">Revision notes<textarea aria-label="Image revision notes" rows={2} maxLength={4000} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Describe the change for your coding assistant…" /></label>
    </div>
    <ActionBar feedback={<><Message message={error} />{notice && <span role="status">{notice}</span>}</>}>
      <Button disabled={busy} onClick={() => onAction("revision_task", { asset_ids: [asset.id], comments: comment })}>Copy revision task</Button>
      <Button disabled={busy || !candidate || asset.state === "blocked"} onClick={() => onAction("user_review", { asset_ids: [asset.id], reason: comment, reviewed: !asset.userReviewed })}>{asset.userReviewed ? "Remove user review" : "Mark user reviewed"}</Button>
    </ActionBar>
  </Modal>;
}
