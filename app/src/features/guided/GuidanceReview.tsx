import type { ContextSetup, Documents } from "../../api/contracts";
import { coreGuidance, guidanceTitle } from "./guidanceReview";
import { DocumentEditor } from "../../ui/DocumentEditor";
import { HelpPopover } from "../../ui/HelpPopover";
import type { useContextDraft } from "./useContextDraft";

export function GuidanceReview({ documents, context, setup, names, selectedName, select, disabled }:
  { documents: Documents; context: ReturnType<typeof useContextDraft>; setup: ContextSetup; names: string[];
    selectedName: string; select: (name: string) => void; disabled: boolean }) {
  const custom = names.filter((name) => name.startsWith("custom:"));
  return <><DocumentEditor documents={documents} drafts={context.drafts} edit={context.edit} disabled={disabled}
    names={names} tabNames={[...coreGuidance, ...(selectedName.startsWith("custom:") ? [selectedName] : [])]} titles={{ quirks: "Style & quirks" }}
    tabLabel={(name) => <>{name.startsWith("custom:") ? "Custom" : guidanceTitle(name)}{context.drafts[name] && <span className="badge">Draft</span>}</>}
    selectedName={selectedName} select={select} focused fill showActions={false} save={context.save} discard={context.discard}
    before={(name) => <>
      <div className="guided-document-state"><span className="context-document-path"><span className="path">{(documents[name]?.path || "").replaceAll("\\", "/").replace(/^.*?(?=\.dazedtl\/)/, "")}</span>
        {name === "glossary" && <HelpPopover label="Glossary format">Keep category headers and source (translation) entries; notes stay on the same line.</HelpPopover>}</span>
        <span className="muted">{context.drafts[name] ? "Unsaved edits" : setup.documents[name]?.exists ? "Saved" : "Not saved yet"}</span>
        {!!custom.length && <select aria-label="Custom guidance" value={name.startsWith("custom:") ? name : ""} onChange={event => select(event.target.value)}>
          <option value="" disabled>Custom guidance…</option>{custom.map(key => <option key={key} value={key}>{guidanceTitle(key)}</option>)}
        </select>}</div>
    </>} />
  </>;
}
