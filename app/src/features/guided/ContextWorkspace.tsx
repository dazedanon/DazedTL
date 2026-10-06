import { useMemo, useState, type ReactNode, type Ref } from "react";
import { Check, Circle, LoaderCircle } from "lucide-react";
import type {
  GuidedState,
  ReferenceFolder,
  SpeakerScan,
} from "../../api/contracts";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Tabs } from "../../ui/Tabs";
import { VirtualList } from "../../ui/VirtualList";
import type { InvestigationPart, InvestigationResult } from "./contextView";

export function ContextTaskHeader({
  title,
  description,
  actions,
  headingRef,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  headingRef: Ref<HTMLHeadingElement>;
}) {
  return (
    <header className="context-task-header">
      <div>
        <h2 ref={headingRef} tabIndex={-1}>
          {title}
        </h2>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

export function ContextWorkspace({
  state,
  results,
  actions,
  addReference,
  removeReference,
  removeImported,
}: {
  state: GuidedState;
  results: InvestigationResult[];
  actions: Record<InvestigationPart, ReactNode>;
  addReference: ReactNode;
  removeReference: (row: ReferenceFolder) => ReactNode;
  removeImported: (id: string) => ReactNode;
}) {
  const references = state.referenceFolders || [];
  const saved = results.filter((row) => row.saved).length;
  return (
    <div className="context-columns">
      <section
        className="context-investigation"
        aria-label="Investigation progress"
      >
        <div className="context-section-heading">
          <h3>Saved results</h3>
          <span>
            {saved} of {results.length} saved
          </span>
        </div>
        <ActionList compact>
          {results.map((row) => (
            <ActionRow
              key={row.id}
              label={
                <>
                  <span className="context-result-heading">
                    <span aria-hidden="true">
                      {row.status === "working" ? (
                        <LoaderCircle
                          size={16}
                          className="job-status-spinner"
                        />
                      ) : row.saved ? (
                        <Check size={16} />
                      ) : (
                        <Circle size={14} />
                      )}
                    </span>
                    <strong>{row.title}</strong>
                    <span className={`context-result-state ${row.status}`}>
                      {
                        {
                          saved: "Saved",
                          waiting: "Awaiting files",
                          idle: "Not saved",
                          working: "Scanning",
                          failed: "Scan failed",
                          unavailable: "Unavailable",
                        }[row.status]
                      }
                    </span>
                  </span>
                  <small>{row.detail}</small>
                </>
              }
            >
              {actions[row.id]}
            </ActionRow>
          ))}
        </ActionList>
        <p className="context-observation-note">
          Results update automatically from saved files.
        </p>
      </section>
      <section className="context-references" aria-label="Reference games">
        <div className="context-section-heading">
          <h3>
            Reference games <span>Optional</span>
          </h3>
          {addReference}
        </div>
        <p className="muted">
          The assistant will look for earlier names and terms in the selected
          game folders.
        </p>
        {!references.length && !state.references.length && (
          <p className="context-empty">No reference games added.</p>
        )}
        <ActionList compact>
          {references.map((row) => (
            <ActionRow
              key={row.id}
              label={
                <>
                  <strong>{row.title}</strong>
                  <small className="context-reference-path">{row.path}</small>
                  {!row.available && (
                    <small>
                      Folder unavailable · choose it again if it moved.
                    </small>
                  )}
                </>
              }
            >
              {removeReference(row)}
            </ActionRow>
          ))}
        </ActionList>
        {!!state.references.length && (
          <ActionList compact>
            {state.references.map((row) => (
              <ActionRow
                key={row.id}
                label={
                  <>
                    <strong>{row.title}</strong>
                    <small>Previously imported reference</small>
                  </>
                }
              >
                {removeImported(row.id)}
              </ActionRow>
            ))}
          </ActionList>
        )}
      </section>
    </div>
  );
}

const rowKey = (row: { id: string }) => row.id;
export function SpeakerNames({ scan }: { scan: SpeakerScan }) {
  const [tab, setTab] = useState("nameplates");
  const [query, setQuery] = useState("");
  const rows = useMemo(
    () =>
      tab === "actors"
        ? Object.entries(scan.actorNames).map(([id, text]) => ({
            id,
            label: `Actor ${id}`,
            text,
          }))
        : tab === "variables"
          ? Object.entries(scan.variableActorIds).map(([id, actor]) => ({
              id,
              label: `Variable ${id}`,
              text: `Actor ${actor}${scan.actorNames[String(actor)] ? " · " + scan.actorNames[String(actor)] : ""}`,
            }))
          : scan.names.map((text, index) => ({
              id: String(index),
              label: "",
              text,
            })),
    [scan, tab],
  );
  const matching = rows.filter((row) =>
    `${row.label} ${row.text}`
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  return (
    <div className="context-name-results">
      <p className="muted">
        {scan.available
          ? `${scan.names.length} source nameplates · ${scan.files} event files`
          : scan.issue ||
            "Run the local scan after the speaker formats are saved."}
      </p>
      <Tabs
        id="speaker-results"
        label="Speaker result types"
        value={tab}
        onChange={setTab}
        items={[
          { id: "nameplates", label: `Nameplates (${scan.names.length})` },
          {
            id: "actors",
            label: `Actors (${Object.keys(scan.actorNames).length})`,
          },
          {
            id: "variables",
            label: `Variable links (${Object.keys(scan.variableActorIds).length})`,
          },
        ]}
      />
      <div className="context-names-toolbar">
        <input
          type="search"
          aria-label="Find speaker names"
          placeholder="Find a name or ID…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <span>{matching.length} shown</span>
      </div>
      <div
        className="context-names-list"
        role="tabpanel"
        id={`speaker-results-panel-${tab}`}
        aria-labelledby={`speaker-results-tab-${tab}`}
      >
        <VirtualList
          items={matching}
          itemKey={rowKey}
          label="Saved speaker names"
          empty={
            <p className="muted">
              {query
                ? "No matching names."
                : "No entries in this saved result."}
            </p>
          }
        >
          {(row) => (
            <div className="context-name-row">
              {row.label && <span>{row.label}</span>}
              <span>{row.text}</span>
            </div>
          )}
        </VirtualList>
      </div>
    </div>
  );
}
