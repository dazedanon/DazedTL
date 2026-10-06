import { useMemo, useState, type ReactNode } from "react";
import type {
  GuidedState,
  ReferenceFolder,
  SpeakerScan,
} from "../../api/contracts";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Tabs } from "../../ui/Tabs";
import { VirtualList } from "../../ui/VirtualList";
import type { InvestigationPart, InvestigationResult } from "./contextView";
import { StatusIcon } from "../../ui/StatusIcon";

const counted = (label: string, count: number) =>
  count ? `${label} (${count.toLocaleString()})` : label;

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
                    <StatusIcon
                      status={
                        row.status === "working"
                          ? "active"
                          : row.status === "failed"
                            ? "failed"
                            : row.saved
                              ? "done"
                              : "idle"
                      }
                    />
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
  // Until a scan is saved there is nothing to browse; the scan control says why.
  if (!scan.available)
    return <p className="muted">{scan.issue || "No names collected yet."}</p>;
  return (
    <div className="context-name-results">
      <p className="muted">
        {`${scan.names.length} source nameplates · ${scan.files} event files`}
      </p>
      <Tabs
        id="speaker-results"
        label="Speaker result types"
        value={tab}
        onChange={setTab}
        items={[
          { id: "nameplates", label: counted("Nameplates", scan.names.length) },
          {
            id: "actors",
            label: counted("Actors", Object.keys(scan.actorNames).length),
          },
          {
            id: "variables",
            label: counted(
              "Variable links",
              Object.keys(scan.variableActorIds).length,
            ),
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
