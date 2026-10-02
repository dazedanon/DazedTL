import { useState } from "react";
import type { ContextSetup, Documents } from "../../api/contracts";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { coreGuidance, guidanceBlockers, guidanceStatus, guidanceTitle } from "./guidanceReview";
import { Button } from "../../ui/Button";
import { DocumentEditor } from "../../ui/DocumentEditor";
import type { useContextDraft } from "./useContextDraft";

export function GuidanceReview({ documents, context, setup, names, selectedName, select, disabled, returnToDiscovery, keepEmpty, run, busy }:
  { documents: Documents; context: ReturnType<typeof useContextDraft>; setup: ContextSetup; names: string[];
    selectedName: string; select: (name: string) => void; disabled: boolean; returnToDiscovery: () => void;
    keepEmpty: (name: string) => void; busy: string; run: (operation: () => Promise<unknown>) => void }) {
  const [comparison, setComparison] = useState<{ name: string; saved: Documents[string] } | null>(null);
  const custom = names.filter((name) => name.startsWith("custom:"));
  const hiddenBlockers = guidanceBlockers(names, documents, context.drafts, setup).filter((name) => name !== selectedName);
  return <><DocumentEditor documents={documents} drafts={context.drafts} edit={context.edit} disabled={disabled}
    names={names} tabNames={[...coreGuidance, ...(selectedName.startsWith("custom:") ? [selectedName] : [])]} titles={{ quirks: "Style & quirks" }}
    tabLabel={(name) => { const status = guidanceStatus(name, documents, context.drafts, setup); return <>{guidanceTitle(name)}{status !== "Saved" && <span className="badge guided-guidance-badge">{status}</span>}</>; }}
    selectedName={selectedName} select={select} focused showActions={false} save={context.save} discard={context.discard}
    before={(name) => {
      const saved = documents[name], draft = context.drafts[name], status = setup.documents[name];
      const conflict = !!draft && draft.revision !== saved.revision;
      const empty = !(draft || saved).text.trim();
      const intentional = empty && status?.intentionalEmpty && !draft;
      const label = conflict ? "Saved guidance changed while you were editing" : draft ? "Unsaved edits" : intentional ? "Intentionally empty" : !status?.exists ? (name === "glossary" ? "No glossary saved yet" : "No document saved yet") : empty ? (name === "glossary" ? "Glossary is empty" : "Document is empty") : status?.needsReview ? "Saved guidance needs review" : name === "glossary" ? "Saved glossary" : "Saved";
      const showing = conflict && comparison?.name === name;
      const resolve = (choice: "saved" | "draft" | "save") => run(async () => {
        if (!comparison || comparison.saved.revision !== saved.revision) throw new Error("Saved guidance changed again. Review the new version before resolving it.");
        if (choice === "save") await context.save(name, comparison.saved.revision);
        else await context.resolve(name, saved, comparison.saved.revision, choice);
        setComparison(null);
      });
      return <>
        <div className="guided-document-state"><span className="path">{(saved.path || "").replaceAll("\\", "/").replace(/^.*?(?=\.dazedtl\/)/, "")}</span><strong className={conflict || draft || status?.needsReview ? "guided-status-warning" : intentional || status?.exists && !empty ? "guided-success" : "muted"}>{label}</strong></div>
        {conflict && <div className="guided-document-conflict">
          {busy === "context:resolve" && <p role="status">Resolving saved guidance…</p>}
          <Button variant="link" onClick={() => setComparison({ name, saved: { ...saved } })}>Review differences</Button>
          {showing && <><div className="guided-document-comparison"><section><h3>Your draft</h3><pre>{draft.text || "(empty)"}</pre></section><section><h3>Saved on disk</h3><pre>{comparison.saved.text || "(empty)"}</pre></section></div>
            <p className="muted">Both versions are kept until you choose. Resolve this change before continuing.</p>
            <div className="actions"><Button onClick={() => resolve("saved")}>Use saved version</Button><Button onClick={() => resolve("draft")}>Keep editing draft</Button><Button variant="primary" onClick={() => resolve("save")}>Save my version</Button></div></>}
        </div>}
        {empty && !intentional && !conflict && <div className="guided-empty-guidance"><p className="muted">Create guidance in discovery, or continue intentionally empty.</p><div className="actions"><Button onClick={returnToDiscovery}>Return to discovery</Button><Button pending={busy === "context:empty"} onClick={() => keepEmpty(name)}>{name === "glossary" ? "Keep glossary empty" : "Keep this document empty"}</Button></div></div>}
        {name === "glossary" && <p className="muted guided-glossary-hint">Keep category headers and source (translation) entries; notes stay on the same line.</p>}
      </>;
    }} />
    {!!custom.length && <details className="guided-custom-guidance"><summary>Custom guidance (optional)</summary><ActionList>{custom.map((name) => <ActionRow key={name} label={<><strong>{guidanceTitle(name)}</strong><small>{guidanceStatus(name, documents, context.drafts, setup)}</small></>}><Button disabled={disabled} variant="quiet" onClick={() => select(name)}>Open guidance</Button></ActionRow>)}</ActionList></details>}
    {!!hiddenBlockers.length && <div className="guided-guidance-blockers" role="status"><ActionList>{hiddenBlockers.map((name) => <ActionRow key={name} label={<><strong>{guidanceTitle(name)} {guidanceStatus(name, documents, context.drafts, setup) === "Conflict" ? "has a conflict" : "needs a choice"}</strong></>}><Button variant="link" disabled={disabled} onClick={() => select(name)}>Open {guidanceTitle(name)}</Button></ActionRow>)}</ActionList></div>}
  </>;

}
