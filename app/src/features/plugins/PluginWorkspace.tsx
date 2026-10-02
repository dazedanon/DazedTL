import { useEffect, useRef, useState, type ReactNode } from "react";
import { FileCode2, Search, Sparkles, ShieldCheck, TriangleAlert } from "lucide-react";
import { useApplication } from "../../app/ApplicationProvider";
import { pluginsApi } from "../../api/plugins";
import type { PluginDetail, PluginList, PluginPreview, PluginState, PluginView } from "../../api/pluginContracts";
import { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { Button } from "../../ui/Button";
import { ActionControl } from "../../ui/ActionControl";
import { ActionSlot } from "../../ui/ActionSlot";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import "./plugins.css";

export const pluginStatus = (status:string) => ({not_investigated:"Not investigated",awaiting_report:"Awaiting saved report",current:"Current findings",partial:"Partial results",selected:"Selected",working_copy:"Working copy",needs_revision:"Needs revision",not_needed:"Not needed",ready:"Ready",stale:"Stale source",unresolved:"Needs evidence",applied:"Applied to game",latent:"Latent / disabled",available:"Available",unchanged:"No changes"}[status] || status);
const checks:Record<string,string>={boundaries:"Approved text locations only",protectedLookups:"Original lookup values protected",structure:"Keys, ordering, types and serialization",syntax:"JavaScript / JSON syntax",decodedTargets:"Decoded targets match saved results",controlTokens:"Interpolation and control codes",residual:"Approved scope residual check"};

export function PluginWorkspace({projectId,observed,error,footerTarget,continueControl,beforeAction,disabled=false}: {
  projectId:string;observed?:PluginState|null;error?:string;footerTarget:HTMLElement|null;continueControl:ReactNode;
  beforeAction:()=>Promise<unknown>;disabled?:boolean;
}) {
  const application=useApplication();
  const action=useAction({after:application.refresh});
  const [state,setState]=useState<PluginState|null>(observed||null);
  const stateRef=useRef(state);
  const [list,setList]=useState<PluginList|null>(null), [detail,setDetail]=useState<PluginDetail|null>(null);
  const [loading,setLoading]=useState(false), [preview,setPreview]=useState<PluginPreview|null>(null);
  const [manual,setManual]=useState<{paths:string[];ids?:string[]}|null>(null),[reason,setReason]=useState("");
  const [recovery,setRecovery]=useState(false);
  const draft=useDraft<PluginView>("plugins-view:"+projectId,{
    initial:{saved:observed?.view||{mode:"scope",query:"",filter:"all",selectedOnly:false,currentFile:"",offset:0}},
    report:action.report,
    persist:async view=>{if(!stateRef.current)throw Error("Plugin state is loading.");const next=await pluginsApi.update(projectId,stateRef.current.revision,view);stateRef.current=next;setState(next);},
  });
  const view=draft.value||state?.view;
  useEffect(()=>{
    if(observed?.projectId!==projectId)return;
    if(draft.session.getSnapshot().dirty||draft.session.getSnapshot().committing||action.busy)return;
    const changed=stateRef.current?.revision!==observed.revision;
    stateRef.current=observed;setState(observed);
    if(changed)draft.session.adopt(observed.view);
  },[observed,action.busy]);
  useEffect(()=>{let alive=true;if(!state)void pluginsApi.state(projectId).then(next=>{if(alive){stateRef.current=next;setState(next);draft.session.adopt(next.view);}}).catch(action.report);return()=>{alive=false;};},[projectId]);
  useEffect(()=>{
    if(!state||!view)return;let alive=true;setLoading(true);
    void pluginsApi.list(projectId,{query:view.query,filter:view.filter,selected_only:view.selectedOnly,offset:view.offset,limit:100},()=>alive)
      .then(next=>{if(alive){setList(next);setLoading(false);}}).catch(error=>{if(alive){action.report(error,"list");setLoading(false);}});
    return()=>{alive=false;};
  },[projectId,state?.observationRevision,view?.query,view?.filter,view?.selectedOnly,view?.offset]);
  useEffect(()=>{
    setDetail(null);if(!view?.currentFile)return;let alive=true;
    void pluginsApi.detail(projectId,view.currentFile,()=>alive).then(next=>{if(alive)setDetail(next);}).catch(error=>{if(alive)action.report(error,"detail");});
    return()=>{alive=false;};
  },[projectId,view?.currentFile,state?.observationRevision]);
  const edit=(patch:Partial<PluginView>)=>draft.session.edit(current=>({...current,...patch}));
  const busy=disabled||action.busy||draft.committing;
  const run=async(name:string,options:Record<string,unknown>={},notice="")=>action.run(async()=>{
    await beforeAction();
    let reply:Awaited<ReturnType<typeof pluginsApi.action>>={};
    await draft.session.commit(async current=>{
      reply=await pluginsApi.action(projectId,name,options);
      if(reply.state){stateRef.current=reply.state;setState(reply.state);}
      if(reply.text)await window.dazedtl.copyText(reply.text);
      if(reply.preview)setPreview(reply.preview);
      return {saved:reply.state?.view||current};
    });
    return reply;
  },notice,name);
  const feedback=(key:string)=>({pending:action.busy&&action.key===key,error:action.key===key?action.error:"",notice:action.key===key?action.notice:""});
  const chooseFile=async(path:string,selected:boolean,latentOnly:boolean)=>{
    if(selected&&latentOnly){setReason("");setManual({paths:[path]});return;}
    await run("select_files",{paths:[path],selected},selected?"File scope retained.":"File excluded.");
  };
  if(!state||!view)return <Message message={error||"Loading saved plugin work…"}/>;
  if(!state.supported)return <section className="plugin-workspace"><Message message={state.limitation}/><p className="muted">Existing Ruby sources and native packing remain in the preserved workflow. This guarded workspace does not claim Ruby publication support.</p><ActionSlot target={footerTarget}>{continueControl}</ActionSlot></section>;
  const working=view.mode==="working", counts=state.counts;
  const selectedHidden=Math.max(0,counts.selectedFiles-(list?.selectedMatched||0));
  const topKey=working?"translation_task":"investigate", refreshKey=working?"refresh_results":"refresh_findings";
  const readyToCopy=counts.selectedFiles>0&&!counts.selectedNotPrepared;
  return <section className="plugin-workspace" aria-label="Plugin text workspace">
    <div className="plugin-state-line"><span className="plugin-stage-badge">{pluginStatus((working?state.editing:state.findings).status === "idle" ? "not_investigated" : (working?state.editing:state.findings).status)}</span><span className="muted">{working?`${counts.ready} ready · ${counts.blocked} awaiting results or revision`:state.layout?`Detected layout: ${state.layout}`:"MV / MZ plugin files"}</span><div className="plugin-mode"><Button variant="quiet" aria-pressed={!working} disabled={busy} onClick={()=>edit({mode:"scope"})}>Scope</Button><Button variant="quiet" aria-pressed={working} disabled={busy} onClick={()=>edit({mode:"working"})}>Working copies</Button></div></div>
    <div className="plugin-handoff"><ActionList><ActionRow label={<><strong>{working?"Translation task":"Investigation"}</strong><small>{working?"Your assistant edits approved working copies.":"Read-only task for your coding assistant."}</small></>}>
      <div className="plugin-handoff-controls"><ActionControl label={working?"Copy translation task":"Copy investigation task"} disabled={busy||(working&&!readyToCopy)} {...feedback(topKey)} onClick={()=>run(topKey,{},"Task copied. Paste it into your coding assistant; refresh its saved report when ready.")} />
      <ActionControl label={working?"Refresh results":"Refresh findings"} disabled={busy||!state.requestPaths[working?"translation":"investigation"]} {...feedback(refreshKey)} onClick={()=>run(refreshKey,{},"Saved report checked.")} /></div>
    </ActionRow></ActionList></div>

    <Message message={error||(![topKey,refreshKey,"prepare","preview_apply","preview_restore","apply","restore"].includes(action.key)?action.error:"")} />
    {state.originalIssue&&<div className="plugin-prerequisite"><TriangleAlert size={15}/><span>{state.originalIssue}</span></div>}
        <div className="plugin-filters"><label className="plugin-search"><Search size={15}/><input aria-label="Search plugins" placeholder="Search plugin or file…" value={view.query} onChange={event=>edit({query:event.target.value,offset:0})}/></label>
          <select aria-label="Plugin status" value={view.filter} onChange={event=>edit({filter:event.target.value,offset:0})}>{["all","ready","selected","needs_revision","latent","unresolved","stale","applied","not_investigated","not_needed"].map(status=><option key={status} value={status}>{status==="all"?"All states":pluginStatus(status)}</option>)}</select>
          {!working&&<Button disabled={busy||!counts.recommended} onClick={()=>run("recommended",{},"Recommendations selected; your overrides retained.")}><Sparkles size={14}/>Use AI recommendation</Button>}
          <details className="plugin-selection-menu"><summary>Selection options</summary><div><Button variant="quiet" disabled={busy} aria-pressed={view.selectedOnly} onClick={()=>edit({selectedOnly:!view.selectedOnly,offset:0})}>Show selected</Button><Button variant="quiet" disabled={busy||!counts.selected} onClick={()=>run("clear",{},"Selection cleared; exclusions retained.")}>Clear selection</Button></div></details>
        </div>
    <div className="plugin-columns">
      <div className="plugin-table-pane">

        <div className="plugin-table-scroll" aria-busy={loading}><table className="plugin-table"><thead><tr><th aria-label="Selection"></th><th>Plugin / file</th>{!working&&<th>Enabled</th>}<th>{working?"Changed":"Visible / latent"}</th><th>{working?"Result":"Recommendation / status"}</th></tr></thead><tbody>{list?.items.map(row=><tr key={row.path} data-current={row.path===view.currentFile}>
          <td><input type="checkbox" aria-label={`Select ${row.path}`} checked={row.selected>0} disabled={busy||(!row.selected&&!row.recommended&&!row.latent)} onChange={event=>chooseFile(row.path,event.target.checked,row.recommended===0&&row.latent>0)}/></td>
          <td><button className="plugin-file" onClick={()=>edit({currentFile:row.path})}><FileCode2 size={14}/><span>{row.plugin}<small title={row.path}>{row.path}</small></span></button></td>
          {!working&&<td>{row.kind==="parameters"?"Config":row.enabled===null?"Not configured":row.enabled?"Yes":"No"}</td>}
          <td>{working?(row.changed?`${row.changed} values`:"-"):row.status==="not_investigated"?"Unknown":`${row.visible}${row.latent?` / ${row.latent} latent`:""}`}</td>
          <td className={`plugin-status plugin-status-${row.status}`}><span>{pluginStatus(row.status)}</span>{!working&&<small>{row.manual?"Adjusted by you":row.recommended?`${row.recommended} recommended`:row.latent?"Excluded until selected":""}</small>}</td>
        </tr>)}</tbody></table>{!list?.items.length&&!loading&&<div className="plugin-empty"><FileCode2 size={28}/><p>{counts.files?"No files match these filters.":"Copy the investigation task to discover plugin files and their text locations."}</p></div>}</div>
        <div className="plugin-table-count"><span>{list?.total.toLocaleString()||0} matching files · {counts.selectedFiles} selected · {selectedHidden} hidden</span><Button disabled={busy||!view.offset} onClick={()=>edit({offset:Math.max(0,view.offset-100)})}>Previous</Button><span>{list?.total?Math.floor(view.offset/100)+1:0} / {Math.ceil((list?.total||0)/100)}</span><Button disabled={busy||view.offset+100>=(list?.total||0)} onClick={()=>edit({offset:view.offset+100})}>Next</Button></div>

      </div>
      <aside className="plugin-evidence" aria-label="Plugin evidence and diff"><header><strong>{detail?.plugin||"Evidence & checks"}</strong>{detail&&<span className={`plugin-status plugin-status-${detail.status}`}>{pluginStatus(detail.status)}</span>}</header>
        <div className="plugin-evidence-body">{!detail?<p className="muted">Choose a file to view its exact text locations, protected values and saved evidence.</p>:<>
          <p className="plugin-path">{detail.path}</p>{detail.reason&&<Message message={detail.reason}/>}
        {working&&<details className="plugin-copy-location"><summary><ShieldCheck size={15}/>Protected originals → scoped working copies</summary><small>{detail?.working||"Make working copies after choosing investigated text."}</small></details>}
          {working&&<><h3>Checks for this file</h3><dl className="plugin-checks">{Object.entries(checks).map(([key,label])=><div key={key}><dt>{label}</dt><dd className={detail.checks[key]?"plugin-success":"muted"}>{detail.checks[key]?"Passed":"Pending"}</dd></div>)}<div><dt>Rendered meaning and fit in game</dt><dd>Pending playtest</dd></div></dl><p className="muted">Syntax passing alone does not verify meaning.</p>{detail.resultEvidence&&<p>{detail.resultEvidence}</p>}</>}
          {detail.items.map(item=><article className="plugin-occurrence" key={item.id}>
            <div className="plugin-occurrence-heading"><label><input aria-label={`Include occurrence ${item.id}`} type="checkbox" checked={item.selected} disabled={busy||item.protected||!item.finding?.safe||!["visible","latent"].includes(item.finding.disposition)} onChange={event=>{
              if(event.target.checked&&item.latent){setReason("");setManual({paths:[],ids:[item.id]});}
              else void run("select",{ids:[item.id],selected:event.target.checked},"Occurrence choice retained.");
            }}/><strong>{item.protected?"Protected lookup / control":item.latent?"Latent / default text":item.finding?"Display text":"Not investigated"}</strong></label><span className="muted">Line {item.line}</span></div>
            <p><span lang="ja">{item.value}</span>{item.target&&<> → <span>{item.target}</span></>}</p><small className="plugin-path">{item.id}{item.logical.length?` · ${JSON.stringify(item.logical)}`:""}</small>
            {item.finding&&<><p>{item.finding.reason}</p><p className="muted">{item.finding.evidence}</p></>}
            {working&&<div className="plugin-diff"><div><small>Original snapshot</small><pre>{item.before}</pre></div><div><small>Working copy</small><pre>{item.after}</pre></div></div>}
          </article>)}{detail.total>detail.items.length&&<p className="muted">Showing {detail.items.length} of {detail.total} occurrence previews. File selection and the scoped task include the complete eligible inventory.</p>}
          <details><summary>Paths & hashes</summary><dl className="plugin-hashes"><dt>Source SHA-256</dt><dd>{detail.sourceHash}</dd><dt>Original snapshot</dt><dd>{detail.original||"Not prepared"}</dd><dt>Original SHA-256</dt><dd>{detail.originalHash||"Not prepared"}</dd><dt>Candidate SHA-256</dt><dd>{detail.candidateHash||"Awaiting results"}</dd></dl></details>
        </>}</div>
        <details className="plugin-boundary"><summary>Plugin scope & limits</summary><p>Plugin JS, parameters/config and identified loaded JSON. Event plugin commands stay in Other event text.</p></details>
      </aside>
    </div>
    <ActionSlot target={footerTarget}><div className="plugin-footer-summary"><span>{counts.selected} text locations · {counts.selectedFiles} files selected · {selectedHidden} hidden</span><small>{state.originalBackup?`Original snapshot ${state.originalBackup.slice(0,8)} · ${counts.applied} files applied`:"Investigation can start before originals are preserved."}</small></div><div className="plugin-footer-actions">
      {!!state.receipts.length&&<Button disabled={busy} onClick={()=>setRecovery(true)}>Recovery</Button>}
      {!working?<ActionControl label="Make working copies" variant="primary" disabled={busy||!counts.selected||!!state.originalIssue} {...feedback("prepare")} onClick={()=>run("prepare",{},"Working copies prepared; runtime files unchanged.")}/>:<ActionControl label={`Review & apply (${counts.ready})`} variant="primary" disabled={busy||!counts.ready} {...feedback("preview_apply")} onClick={()=>run("preview_apply")}/>}
      {continueControl}
    </div></ActionSlot>
    {manual&&<Modal label="Include latent plugin text" className="plugin-review-modal" onDismiss={()=>setManual(null)} dismissible={!action.busy}><header><h2>Include inactive or default-only text</h2></header><div className="plugin-review-body"><p>These safe display locations are excluded by default. Your scope choice is retained with a reason.</p><label>Reason<textarea value={reason} onChange={event=>setReason(event.target.value)}/></label><Message message={action.key==="select"||action.key==="select_files"?action.error:""}/></div><footer><Button disabled={action.busy} onClick={()=>setManual(null)}>Cancel</Button><Button variant="primary" disabled={action.busy||!reason.trim()} onClick={async()=>{const result=await run(manual.ids?"select":"select_files",{...manual,selected:true,includeLatent:true,reason},"Manual scope retained.");if(result.ok)setManual(null);}}>Include safe latent text</Button></footer></Modal>}
    {recovery&&<Modal label="Plugin recovery" className="plugin-review-modal" onDismiss={()=>setRecovery(false)}><header><h2>Plugin Apply & recovery</h2></header><div className="plugin-review-body">{state.receipts.slice().reverse().map(receipt=><article className="plugin-receipt" key={receipt.id}><strong>{receipt.mode} · {receipt.status} · {receipt.files.length} files</strong><p className="muted">{receipt.saved}</p>{receipt.failure&&<Message message={receipt.failure}/>}<p>{receipt.conflicts.join(" · ")}</p><Button disabled={busy||receipt.mode!=="apply"||!receipt.files.length} onClick={async()=>{const result=await run("preview_restore",{receipt:receipt.id});if(result.ok)setRecovery(false);}}>Review restore</Button></article>)}</div><footer><Button onClick={()=>setRecovery(false)}>Close</Button></footer></Modal>}
    {preview&&<Modal label={preview.mode==="apply"?"Apply plugin files":"Restore plugin files"} className="plugin-review-modal" dismissible={!action.busy} onDismiss={()=>setPreview(null)}><header><h2>{preview.mode==="apply"?"Apply":"Restore"} {preview.files.length} plugin files</h2><p className="muted">{preview.files.length} included · {preview.blocked.length} blocked / awaiting and excluded</p></header><div className="plugin-review-body">
      <div className="plugin-review-table"><table><thead><tr><th>Exact runtime file</th><th>Before SHA-256</th><th>{preview.mode==="apply"?"Candidate":"Restore"} SHA-256</th></tr></thead><tbody>{preview.files.map(file=><tr key={file.path}><td><strong>{file.destination}</strong><small>{file.changes} values · backup: {file.backup}</small></td><td title={file.beforeHash}>{file.beforeHash.slice(0,16)}…</td><td title={file.afterHash}>{file.afterHash.slice(0,16)}…</td></tr>)}</tbody></table></div>
      {!!preview.blocked.length&&<details open><summary>Blocked files</summary>{preview.blocked.map(file=><p key={file.path}><strong>{file.path}</strong> · {file.reason}</p>)}</details>}
      <div className="plugin-review-callout"><strong>Before any runtime file changes</strong><p>Recheck source, original and candidate hashes; preserve verified backups. Changed files invalidate this review.</p></div>
      <p>Only approved literal spans and decoded parameter paths may change. Identifiers, lookup values, structure, interpolation and control codes stay protected.</p><p className="muted">Plugin-loaded JSON follows this exact scoped publication receipt; ordinary event/database outputs use their existing Apply flow.</p>
      <details><summary>Manifest & recovery</summary><p className="plugin-path">{preview.manifest}</p><p>The saved receipt retains exact paths, before/after hashes and backup references. Restore requires another review and matching current runtime bytes.</p></details>
      <Message message={action.key===preview.mode?action.error:""}/>
    </div><footer><Button disabled={action.busy} onClick={()=>setPreview(null)}>Cancel</Button><ActionControl variant="primary" label={`${preview.mode==="apply"?"Apply":"Restore"} ${preview.files.length} plugin files`} disabled={busy||!preview.files.length} {...feedback(preview.mode)} onClick={async()=>{const result=await run(preview.mode,{token:preview.token},preview.mode==="apply"?"Reviewed plugin files applied.":"Reviewed plugin files restored.");if(result.ok)setPreview(null);}}/></footer></Modal>}
  </section>;
}
