import type { ContextSetup, Documents } from "../../api/contracts";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { coreGuidance, guidanceTitle } from "./guidanceReview";
import { Button } from "../../ui/Button";
import { DocumentEditor } from "../../ui/DocumentEditor";
import type { useContextDraft } from "./useContextDraft";

export function GuidanceReview({ documents, context, setup, names, selectedName, select, disabled }:
  { documents: Documents; context: ReturnType<typeof useContextDraft>; setup: ContextSetup; names: string[];
    selectedName: string; select: (name: string) => void; disabled: boolean }) {
  const custom = names.filter((name) => name.startsWith("custom:"));
  return <><DocumentEditor documents={documents} drafts={context.drafts} edit={context.edit} disabled={disabled}
    names={names} tabNames={[...coreGuidance, ...(selectedName.startsWith("custom:") ? [selectedName] : [])]} titles={{ quirks: "Style & quirks" }}
    tabLabel={(name) => <>{guidanceTitle(name)}{context.drafts[name] && <span className="badge">Draft</span>}</>}
    selectedName={selectedName} select={select} focused showActions={false} save={context.save} discard={context.discard}
    before={(name) => <>
      <div className="guided-document-state"><span className="path">{(documents[name]?.path || "").replaceAll("\\", "/").replace(/^.*?(?=\.dazedtl\/)/, "")}</span>
        <span className="muted">{context.drafts[name] ? "Unsaved edits" : setup.documents[name]?.exists ? "Saved" : "Not saved yet"}</span></div>
      {name === "glossary" && <p className="muted guided-glossary-hint">Keep category headers and source (translation) entries; notes stay on the same line.</p>}
    </>} />
    {!!custom.length && <details className="guided-custom-guidance"><summary>Custom guidance (optional)</summary><ActionList>{custom.map((name) => <ActionRow key={name} label={<strong>{guidanceTitle(name)}</strong>}><Button disabled={disabled} variant="quiet" onClick={() => select(name)}>Open guidance</Button></ActionRow>)}</ActionList></details>}
  </>;
}
