import { useState } from "react";
import type { GuidedState } from "../../api/contracts";
import { Button } from "../../ui/Button";

export function FileSelection({ state, selected, change, disabled }: {
  state: GuidedState; selected: string[]; change: (names: string[]) => void; disabled: boolean;
}) {
  const [query, setQuery] = useState("");
  const visible = state.files.filter((file) => file.name.toLowerCase().includes(query.toLowerCase()));
  return <>
    <div className="actions">
      <input aria-label="Filter game files" placeholder="Filter files…" value={query} onChange={(event) => setQuery(event.target.value)} />
      <Button disabled={disabled} onClick={() => change(state.files.map((file) => file.name))}>Select all</Button>
      <Button disabled={disabled} onClick={() => change([])}>Clear</Button>
      <span className="muted">{selected.length} selected · {state.importedFiles.length} imported</span>
    </div>
    <div className="file-list">
      {visible.map((file) => <label key={file.name}>
        <input type="checkbox" checked={selected.includes(file.name)} disabled={disabled}
          onChange={(event) => change(event.target.checked ? [...selected, file.name] : selected.filter((name) => name !== file.name))} />
        <span>{file.name}</span>
        {state.importedFiles.includes(file.name) && <small>Imported</small>}
      </label>)}
      {!visible.length && <p className="muted">{state.files.length ? "No files match this filter." : "Prepare the game's JSON data before selecting files."}</p>}
    </div>
  </>;
}
