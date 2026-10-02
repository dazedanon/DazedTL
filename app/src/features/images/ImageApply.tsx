import type { ImagePreview } from "../../api/imageContracts";
import { Button } from "../../ui/Button";
import { Modal } from "../../ui/Modal";
import { ActionBar } from "../../ui/ActionBar";
import { Message } from "../../ui/Feedback";

export function ImageApply({ preview, selected, busy, error, onDismiss, onConfirm }: {
  preview: ImagePreview; selected: number; busy: boolean; error: string; onDismiss: () => void; onConfirm: () => void;
}) {
  const restore = preview.action.includes("restore");
  const count = typeof preview.included === "number" ? preview.included : preview.assets.length;
  const [page, setPage] = useState(0);
  const [blockedPage, setBlockedPage] = useState(0);
  const [copyNotice, setCopyNotice] = useState("");
  const pageSize = 50;
  const included = preview.assets.slice(page * pageSize, (page + 1) * pageSize);
  const blocked = preview.blocked.slice(blockedPage * pageSize, (blockedPage + 1) * pageSize);
  return <Modal label={restore ? "Restore image originals" : "Review image application"} className="image-apply-modal" dismissible={!busy} onDismiss={onDismiss}>
    <header className="image-modal-heading"><h2>{restore ? `Restore ${count} original images` : `Apply ${count} images to the game`}</h2></header>
    <div className="image-apply-body"><p><strong>{selected} selected · {count} included · {preview.blocked.length} blocked</strong>{!!preview.unchanged && <span> · {preview.unchanged} unchanged</span>}</p>
      <p>{restore ? "Verified backups replace these runtime assets. Editable copies remain available." : "Originals are backed up. Source files and edited images are validated again before this batch is applied."}</p>
      <div className="image-apply-files" aria-label="Included runtime destinations"><h3>Included destinations</h3>{included.map((asset) => <div key={asset.id}><strong>{asset.path}</strong><span>{asset.destination}</span></div>)}{!count && <p>No images can be included. Return to the manager and resolve the issues.</p>}{preview.assets.length > pageSize && <div className="image-apply-pagination"><span>{page * pageSize + 1}–{Math.min((page + 1) * pageSize, preview.assets.length)} of {preview.assets.length} destinations</span><Button disabled={!page} onClick={() => setPage(page - 1)}>Previous</Button><Button disabled={(page + 1) * pageSize >= preview.assets.length} onClick={() => setPage(page + 1)}>Next</Button></div>}<Button variant="link" onClick={() => { void window.dazedtl.copyText(preview.assets.map((asset) => asset.path + "\n  " + asset.destination).join("\n")).then(() => setCopyNotice("Destination list copied."), () => setCopyNotice("Could not copy the list. The destinations remain available here.")); }}>Copy destination list</Button>{copyNotice && <span role="status">{copyNotice}</span>}</div>
      {!!preview.blocked.length && <section className="image-apply-blocked"><h3>Blocked images remain excluded</h3>{blocked.map((asset) => <p key={asset.id}><strong>{asset.path}</strong><span>{asset.reason}</span></p>)}{preview.blocked.length > pageSize && <div className="image-apply-pagination"><span>{blockedPage * pageSize + 1}–{Math.min((blockedPage + 1) * pageSize, preview.blocked.length)} of {preview.blocked.length} blocked images</span><Button disabled={!blockedPage} onClick={() => setBlockedPage(blockedPage - 1)}>Previous blocked</Button><Button disabled={(blockedPage + 1) * pageSize >= preview.blocked.length} onClick={() => setBlockedPage(blockedPage + 1)}>Next blocked</Button></div>}</section>}
      <details className="image-details"><summary>Details and recovery</summary><p>If any included image fails validation, this batch is not applied. A publishing failure attempts to restore runtime replacements; any recovery failure is reported.</p>{Array.isArray(preview.backups) && !!preview.backups.length && <ul>{preview.backups.map((path) => <li key={path}>{path}</li>)}</ul>}<p>Approval applies only to these source and candidate versions.</p></details>
    </div>
    <ActionBar feedback={<Message message={error} />}><Button disabled={busy} onClick={onDismiss}>Cancel</Button><Button variant="primary" pending={busy} disabled={!count} onClick={onConfirm}>{restore ? `Restore ${count} images` : `Apply ${count} images`}</Button></ActionBar>
  </Modal>;
}
import { useState } from "react";
