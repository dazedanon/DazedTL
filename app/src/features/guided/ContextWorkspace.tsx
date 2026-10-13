import { PathText } from "../../ui/PathText";
import { useMemo, useState, type ReactNode } from "react";
import type {
  GuidedState,
  ReferenceFolder,
  ShowTextHeader,
  SpeakerScan,
} from "../../api/contracts";
import type { DisplayState } from "../../ui/displayStatus";
import { StatusHeading } from "../../ui/StatusMark";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { AssistantTask } from "../../ui/AssistantTask";
import { Tabs } from "../../ui/Tabs";
import { VirtualList } from "../../ui/VirtualList";
import type { InvestigationPart, InvestigationResult } from "./contextView";
import { textLocation } from "./textLocation";
import { withHandoff } from "../assistant/assistantTasks";
import { useHandoff } from "../assistant/useAssistantTasks";

const counted = (label: string, count: number) =>
  count ? `${label} (${count.toLocaleString()})` : label;

export function ContextWorkspace({
  state,
  results,
  actions,
  addReference,
  removeReference,
  removeImported,
  investigation,
}: {
  state: GuidedState;
  results: InvestigationResult[];
  actions: Record<InvestigationPart, ReactNode>;
  addReference: ReactNode;
  /** How the copied task investigates, such as its number of passes. */
  investigation: ReactNode;
  removeReference: (row: ReferenceFolder) => ReactNode;
  removeImported: (id: string) => ReactNode;
}) {
  const references = state.referenceFolders || [];
  const saved = results.filter((row) => row.saved).length;
  const problem = results.find((row) =>
    ["failed", "unavailable"].includes(row.status),
  );
  const handoff = useHandoff("names");
  // Saved results complete the task once its assistant stops; reading them
  // over is advice, not a review the app waits for.
  const finishing = saved === results.length && handoff.waiting;
  const taskState = withHandoff(
    saved === results.length && !handoff.waiting
      ? "done"
      : problem
        ? "blocked"
        : // Results saved earlier are not a task in progress; a copy is.
          handoff.waiting ||
            results.some((row) => ["waiting", "working"].includes(row.status))
          ? "waiting"
          : "not_started",
    handoff,
  );
  return (
    <div className="context-columns">
      <AssistantTask
        state={taskState}
        progress={
          saved && saved < results.length
            ? `${saved} of ${results.length} saved`
            : undefined
        }
        description={
          taskState === "done"
            ? "Look over the guidance before translating."
            : taskState === "blocked"
              ? problem!.detail
              : finishing
                ? "Your assistant is still investigating; the task finishes when it saves the line widths."
                : taskState === "waiting"
                  ? "Results appear here as your assistant saves them."
                  : "Your assistant finds speaker formats, running jokes and terms, and writes the glossary and game context; a local scan collects names."
        }
        results={results.map((row) => ({
          id: row.id,
          title: row.title,
          state: (
            {
              saved: "done",
              // A dismissed task no longer waits for its results.
              waiting: handoff.dismissed ? "not_started" : "waiting",
              idle: "not_started",
              working: "working",
              failed: "blocked",
              unavailable: "blocked",
            } as const
          )[row.status],
          detail: row.detail,
          action: actions[row.id],
        }))}
      />
      <div className="context-side">
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
                    <small>
                      <PathText path={row.path} />
                    </small>
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
        <section aria-labelledby="context-investigation-heading">
          <div className="context-section-heading">
            <h3 id="context-investigation-heading">Investigation</h3>
          </div>
          {investigation}
        </section>
      </div>
    </div>
  );
}

const rowKey = (row: { id: string }) => row.id;
/** A saved name, or a likely speaker slip with its header, reason and the
 * assistant's decision. */
interface ResultRow {
  id: string;
  label: string;
  text: string;
  header?: string;
  evidence?: string;
  state?: DisplayState;
  reason?: string;
}
const showHeader = (header: ShowTextHeader) =>
  (header.name || "No nameplate") +
  (header.faceName ? ` · face ${header.faceName} ${header.faceIndex}` : "");
export function SpeakerNames({ scan }: { scan: SpeakerScan }) {
  const [tab, setTab] = useState("nameplates");
  const [query, setQuery] = useState("");
  const rows = useMemo<ResultRow[]>(
    () =>
      tab === "slips"
        ? (scan.headers?.flags || []).map((flag) => ({
            id: flag.file + flag.pointer,
            label: `${flag.file} · ${textLocation(flag.pointer)}`,
            text: flag.text,
            header:
              showHeader(flag) +
              (flag.fixedTo ? ` → ${showHeader(flag.fixedTo)}` : ""),
            evidence: flag.evidence,
            state:
              flag.decision === "fixed"
                ? "applied"
                : flag.decision === "kept"
                  ? "done"
                  : undefined,
            reason: flag.reason,
          }))
        : tab === "actors"
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
    Object.values(row)
      .join(" ")
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  // Until a scan is saved there is nothing to browse; the scan control says why.
  if (!scan.available)
    return <p className="muted">{scan.issue || "No names collected yet."}</p>;
  return (
    <div className="context-name-results">
      <p className="muted">{`${scan.files} event files scanned`}</p>
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
          {
            id: "slips",
            label: counted("Speaker slips", scan.headers?.flags.length || 0),
          },
        ]}
      />
      <div className="context-names-toolbar">
        <input
          type="search"
          aria-label="Find speaker names"
          placeholder={
            tab === "slips"
              ? "Find a name, line or place…"
              : "Find a name or ID…"
          }
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {/* The tab already counts every result; count only a filtered view. */}
        {query && <span>{matching.length} shown</span>}
      </div>
      <div
        className="context-names-list"
        role="tabpanel"
        id={`speaker-results-panel-${tab}`}
        aria-labelledby={`speaker-results-tab-${tab}`}
      >
        {tab === "slips" && !!scan.headers?.flags.length && (
          <p className="muted">
            {scan.headers.fixed + scan.headers.kept
              ? `Your assistant checked these in their scenes, fixed ${scan.headers.fixed} and kept ${scan.headers.kept}; Text QA looks at the kept ones again after translation.`
              : "Nameplates and faces in the original game that likely show the wrong speaker. Your assistant checks each in its scene during this task and fixes the slips."}
          </p>
        )}
        <VirtualList
          items={matching}
          itemKey={rowKey}
          label={
            tab === "slips" ? "Likely speaker slips" : "Saved speaker names"
          }
          empty={
            <p className="muted">
              {query
                ? "No matching results."
                : tab !== "slips"
                  ? "No entries in this saved result."
                  : scan.headers
                    ? "No likely speaker slips in the game's nameplates and faces."
                    : "Scan again to check the game's nameplates and faces for speaker slips."}
            </p>
          }
        >
          {(row) =>
            row.evidence ? (
              <div className="context-slip-row">
                <small>{row.label}</small>
                <StatusHeading state={row.state} title={row.header} />
                <span lang="ja">{row.text}</span>
                <span className="muted">{row.evidence}</span>
                {row.reason && (
                  <span className="muted">
                    {row.state === "applied"
                      ? "Your assistant fixed it: "
                      : "Your assistant kept it: "}
                    {row.reason}
                  </span>
                )}
              </div>
            ) : (
              <div className="context-name-row">
                {row.label && <span>{row.label}</span>}
                <span>{row.text}</span>
              </div>
            )
          }
        </VirtualList>
      </div>
    </div>
  );
}
