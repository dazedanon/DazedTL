import { useCallback, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Eye } from "lucide-react";
import type { GuidedFile, GuidedState } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { VirtualList } from "../../ui/VirtualList";
import { fileGroup, filterFiles, selectFile, selectMatching, sortFiles, type FileGroup, type SelectionGesture } from "./selection";

const groups = [["all", "All files"], ["database", "Database"], ["maps", "Maps"], ["common", "Other events"]] as const;
const keyOf = (file: GuidedFile) => file.name;
type Modifiers = { shiftKey: boolean; ctrlKey: boolean; metaKey: boolean };
const gesture = (event: Modifiers, checkbox = false): SelectionGesture => event.shiftKey
  ? event.ctrlKey || event.metaKey ? "add-range" : "range"
  : checkbox || event.ctrlKey || event.metaKey ? "toggle" : "replace";

export function FileSelection({ state, selected, change, disabled, inline, actions }: {
  state: GuidedState; selected: string[]; change: (names: string[]) => void; disabled: boolean;
  actions?: ReactNode;
  inline?: { columns: ReactNode; details: (file: GuidedFile) => ReactNode; preview: (name: string) => void; previewed?: string };
}) {
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState<FileGroup>("all");
  const [selectedOnly, setSelectedOnly] = useState(false);
  const [changedOnly, setChangedOnly] = useState(false);
  const [notice, setNotice] = useState("");
  const [focusName, setFocusName] = useState<string | null>(null);
  const anchor = useRef<string | null>(null);
  const search = useRef<HTMLInputElement>(null);
  const files = useMemo(() => sortFiles(state.files), [state.files]);
  const selection = useMemo(() => new Set(selected), [selected]);
  const changed = useMemo(() => new Set(state.sourceStatus.changed), [state.sourceStatus.changed]);
  const matches = useMemo(() => filterFiles(files, group, query).filter((file) => !changedOnly || changed.has(file.name)), [files, group, query, changedOnly, changed]);
  const visible = useMemo(() => matches.filter((file) => !selectedOnly || selection.has(file.name)), [matches, selectedOnly, selection]);
  const names = useMemo(() => visible.map(keyOf), [visible]);
  const matchedSelection = matches.filter((file) => selection.has(file.name)).length;
  const selectedChanges = selected.filter((name) => changed.has(name)).length;
  const hidden = selected.length - matchedSelection;
  const counts = groups.slice(1).map(([value, label]) => ({ label: label.toLowerCase(), count: files.filter((file) => fileGroup(file) === value && selection.has(file.name)).length })).filter((item) => item.count > 0);
  const resetFilter = () => { anchor.current = null; setFocusName(null); setNotice(""); };
  const apply = (next: string[], message = "") => {
    if (disabled) return;
    change(next); setNotice(message);
  };
  const focus = useCallback((row: HTMLElement) => {
    row.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true });
    setFocusName(null);
  }, []);
  const choose = (name: string, event: Modifiers, checkbox = false) => {
    if (disabled) return;
    const operation = gesture(event, checkbox);
    const next = selectFile(selected, names, name, operation, anchor.current);
    anchor.current = next.anchor;
    apply(next.selected, operation === "range" ? "Selected this range." : operation === "add-range" ? "Added this range to your selection." : "");
    const target = selectedOnly && !next.selected.includes(name) ? names.find((item) => next.selected.includes(item)) : name;
    if (target) setFocusName(target); else search.current?.focus();
  };
  const bulk = (add: boolean) => {
    apply(selectMatching(selected, names, add), `${add ? "Selected" : "Cleared"} ${add ? names.length : visible.filter((file) => selection.has(file.name)).length} matching files. Other groups are unchanged.`);
    anchor.current = null;
  };
  const keyDown = (event: KeyboardEvent, index: number) => {
    const additive = event.ctrlKey || event.metaKey;
    if (additive && event.key.toLowerCase() === "a") { event.preventDefault(); bulk(true); return; }
    if (event.key === " ") { event.preventDefault(); choose(names[index], event, true); return; }
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? names.length - 1
      : Math.min(names.length - 1, Math.max(0, index + (event.key === "ArrowDown" ? 1 : -1)));
    if (additive && !event.shiftKey) setFocusName(names[next]);
    else choose(names[next], event);
  };
  return <div className={`file-browser${inline ? " file-browser-inline" : ""}`}>
    <div className="file-browser-search">
      <input ref={search} aria-label="Search game files" value={query}
        placeholder={inline ? "Search files…" : "Search filename, map name, or ID range (10–25)…"}
        title="Search filename, map name, or ID range (10–25)"
        onChange={(event) => { setQuery(event.target.value); resetFilter(); }} />
      <Button aria-pressed={selectedOnly} onClick={() => { setSelectedOnly(!selectedOnly); resetFilter(); }}>Selected only</Button>
    </div>
    {!inline && <nav className="file-browser-groups" aria-label="File groups">
      {groups.map(([value, label]) => <Button key={value} variant="quiet" aria-pressed={group === value}
        onClick={() => { setGroup(value); resetFilter(); }}>{label} <span>{value === "all" ? files.length : files.filter((file) => fileGroup(file) === value).length}</span></Button>)}
    </nav>}
    <div className="file-browser-toolbar">
      <span>{inline ? `${visible.length} files` : `${visible.length} ${visible.length === 1 ? "match" : "matches"}`}{inline && hidden > 0 && ` · ${hidden} hidden`}</span>
      <div className="actions">
        <Button variant="quiet" disabled={disabled || !visible.length || visible.every((file) => selection.has(file.name))} onClick={() => bulk(true)}>Select {inline && !query ? "all" : "matching"}</Button>
        <Button variant="quiet" disabled={disabled || !visible.some((file) => selection.has(file.name))} onClick={() => bulk(false)}>Clear {inline && !query ? "all" : "matching"}</Button>
        {actions}
      </div>
    </div>
    <div className="file-browser-heading" aria-hidden="true"><span /><span>File</span>{inline ? inline.columns : <><span>Map / contents</span><span>Source</span></>}</div>
    <VirtualList key={`${group}:${query}:${selectedOnly}:${changedOnly}`} items={visible} itemKey={keyOf} label="Files to include in this pass"
      focusKey={focusName} onFocusReady={focus}
      empty={<div className="file-browser-empty"><strong>{files.length ? "No files match these filters." : "No supported files are available."}</strong>
        <p>{files.length ? "Your selection is retained." : "Prepare the game’s JSON data first."}</p>
        {!!files.length && <Button variant="quiet" onClick={() => { setGroup("all"); setQuery(""); setSelectedOnly(false); setChangedOnly(false); resetFilter(); }}>Clear filters</Button>}</div>}>
      {(file, index) => <div className="file-browser-row" data-selected={selection.has(file.name)} data-previewed={inline?.previewed === file.name}
        onMouseDown={(event) => { if (event.shiftKey) event.preventDefault(); }}
        onClick={(event) => choose(file.name, event)} onKeyDown={(event) => keyDown(event, index)}>
        <input type="checkbox" aria-label={`Include ${file.name}${file.title ? ": " + file.title : ""}`} disabled={disabled} checked={selection.has(file.name)}
          onClick={(event) => event.stopPropagation()} onChange={(event) => choose(file.name, event.nativeEvent as MouseEvent, true)} />
        <span className="file-browser-name" title={inline && file.title ? `${file.name}\n${file.title}` : file.name}>{file.name}{inline && file.title && <small>{file.title}</small>}</span>
        {inline ? <>{inline.details(file)}<Button variant="quiet" className="file-preview-control" aria-label={`Inspect ${file.name}`} aria-pressed={inline.previewed === file.name} title={`Inspect ${file.name}`} onKeyDown={event => event.stopPropagation()} onClick={event => { event.stopPropagation(); inline.preview(file.name); }}><Eye size={16} aria-hidden="true" /></Button></> : <><span className="file-browser-title">{file.title || (file.group === "database" ? "Names & interface" : "Dialogue & choices")}</span>
        <span className={changed.has(file.name) ? "file-browser-changed" : "muted"}>{changed.has(file.name) ? "Changed" : "Unchanged"}</span></>}
      </div>}
    </VirtualList>
    {!inline && <div className="file-browser-selection" aria-live="polite">
      <div><strong>{selected.length} selected</strong>{hidden > 0 && <span className="muted"> · {hidden} outside this filter</span>}
        {counts.length === 1 ? <span className="muted"> · {counts[0].label}</span> : counts.length > 1 && <span className="file-browser-counts">{counts.map((item) => `${item.count} ${item.label}`).join(" · ")}</span>}</div>
      <div className="actions">
        <Button variant="quiet" disabled={disabled || !selected.length} onClick={() => { apply([], "Selection cleared."); anchor.current = null; }}>Clear selection</Button>
      </div>
      {!!selectedChanges && <p className="file-browser-source-warning">{selectedChanges} selected {selectedChanges === 1 ? "source has" : "sources have"} changed. <Button variant="quiet" onClick={() => { setGroup("all"); setQuery(""); setSelectedOnly(true); setChangedOnly(true); resetFilter(); }}>Show changed sources</Button></p>}
      {changedOnly && <Button variant="quiet" onClick={() => { setChangedOnly(false); resetFilter(); }}>Show all source states</Button>}
      {notice && <p role="status">{notice}</p>}
    </div>}
    {inline && notice && <span className="sr-only" role="status">{notice}</span>}
  </div>;
}
