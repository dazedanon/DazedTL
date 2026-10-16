/**
 * The Glossary check's list: lines whose English lacks a glossary term their
 * Japanese holds, by term, each with its proposal and the user's choice.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  GlossaryLine,
  GlossaryReport,
  GlossaryState,
} from "../../api/contracts";
import { api } from "../../api/client";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { HelpPopover } from "../../ui/HelpPopover";
import { LineChange, type LineChangeRow } from "../../ui/LineChange";
import { Notice } from "../../ui/Notice";
import { byTerms, glossaryGroups, type GlossaryGroup } from "./glossaryView";
import { textLocation } from "./textLocation";
import type { Feedback } from "./TextQa";

type Choice = "keep" | "use" | "edit" | "clear";
type Choose = (
  feedbackKey: string,
  keys: string[],
  choice: Choice,
  text?: string,
) => void;

/** Lines a group shows before its explicit Show all. */
const groupPreview = 3;

const count = (value: number, one: string, many: string) =>
  `${value.toLocaleString()} ${value === 1 ? one : many}`;

export function GlossaryCheckWork({
  projectId,
  state,
  disabled,
  feedback,
  run,
  checkAgain,
}: {
  projectId: string;
  state: GlossaryState;
  disabled: boolean;
  feedback: Feedback;
  /** Runs one choice under its feedback key. */
  run: (feedbackKey: string, work: () => Promise<void>) => void;
  /** The control that checks again, beside the result. */
  checkAgain?: ReactNode;
}) {
  const [report, setReport] = useState<GlossaryReport | null>(null);
  const [error, setError] = useState("");
  // Lines kept on this visit keep their place, and earlier ones wait under
  // Kept; both start afresh with each scan.
  const [kept, setKept] = useState<{ scan?: string | null; keys: string[] }>({
    keys: [],
  });
  const [keptShown, setKeptShown] = useState<string | null>(null);
  const shown = useRef("");
  // The list reads again whenever a scan or a choice changes it.
  useEffect(() => {
    if (!state.revision || shown.current === state.revision) return;
    shown.current = state.revision;
    let live = true;
    api.guided.glossaryReport(projectId).then(
      (value) => {
        if (!live) return;
        setReport(value);
        setError("");
      },
      (reason: unknown) => {
        if (live)
          setError(reason instanceof Error ? reason.message : String(reason));
      },
    );
    return () => {
      live = false;
    };
  }, [projectId, state.revision]);
  if (!state.scan) return null;
  if (!report)
    return error ? (
      <Notice tone="warning">{error}</Notice>
    ) : (
      <p className="muted">Loading…</p>
    );
  const choose: Choose = (feedbackKey, keys, choice, text) =>
    run(feedbackKey, async () => {
      const next = await api.guided.glossary(projectId, "choose", {
        keys,
        choice,
        ...(choice === "edit" && { text }),
      });
      shown.current = next.revision;
      setReport(next);
      if (choice === "keep")
        setKept((value) => ({
          scan: next.scan,
          keys: [...(value.scan === next.scan ? value.keys : []), ...keys],
        }));
    });
  const keptHere = new Set(kept.scan === report.scan ? kept.keys : []);
  const showKept = keptShown === report.scan;
  const groupedLines = glossaryGroups(report.found, keptHere);
  const { proposed, unproposed } = groupedLines;
  const listed = report.found.length;
  const unproposedOpen = unproposed.flatMap((group) =>
    group.lines.filter((line) => line.state === "open"),
  );
  const groups = (list: GlossaryGroup[]) =>
    list.map((group) => (
      <TermGroup
        key={group.key}
        group={group}
        disabled={disabled}
        feedback={feedback}
        choose={choose}
      />
    ));
  return (
    <section className="glossary-check" aria-label="Last check">
      <div className="check-results-heading">
        <div className="glossary-summary">
          {!report.lines
            ? "The game has no translated text yet; apply translations, then check again."
            : report.flagged
              ? `${report.flagged.toLocaleString()} of ${count(report.lines, "translated line", "translated lines")} lack the glossary's English for a term in their Japanese.`
              : `All ${count(report.lines, "translated line", "translated lines")} use the glossary's English for their terms.`}{" "}
          <HelpPopover label="How the check works">
            The check finds each glossary term in a line's Japanese and looks
            for the term's English in the line, allowing plurals, possessives
            and small words such as "of". When the game's own wording is the
            right one, change the glossary row instead and check again.
          </HelpPopover>
        </div>
        {!report.current && (
          <span className="muted">
            From before the game's text or glossary changed
          </span>
        )}
        {checkAgain}
      </div>
      {listed < report.flagged && (
        <p className="muted">
          The first {listed.toLocaleString()} are listed; check again once
          they're settled for the rest.
        </p>
      )}
      {error && <Notice tone="warning">{error}</Notice>}
      {proposed.length > 0 && (
        <section aria-label="With a proposal">
          <h3>
            With a proposal ·{" "}
            {proposed
              .reduce((total, group) => total + group.lines.length, 0)
              .toLocaleString()}
          </h3>
          <p className="muted">
            Each proposal writes the glossary's English over the words that
            render the term.
          </p>
          {groups(proposed)}
        </section>
      )}
      {unproposed.length > 0 && (
        <section aria-label="No proposal">
          <div className="check-results-heading">
            <h3>
              No proposal ·{" "}
              {unproposed
                .reduce((total, group) => total + group.lines.length, 0)
                .toLocaleString()}
            </h3>
            {unproposedOpen.length > 1 && (
              <ActionControl
                label={`Keep all ${unproposedOpen.length.toLocaleString()}`}
                variant="link"
                disabled={disabled}
                {...feedback("glossary-keep:unproposed", "Saving…")}
                onClick={() =>
                  choose(
                    "glossary-keep:unproposed",
                    unproposedOpen.map((line) => line.key),
                    "keep",
                  )
                }
              />
            )}
          </div>
          <p className="muted">
            Often an ordinary word written like the term, such as 回復 beside a
            skill named Heal, or a name the English says as “you”.
          </p>
          {groups(unproposed)}
        </section>
      )}
      {groupedLines.kept.length > 0 && (
        <section aria-label="Kept">
          <div className="check-results-heading">
            <h3>Kept · {groupedLines.kept.length.toLocaleString()}</h3>
            {!showKept && (
              <Button variant="link" onClick={() => setKeptShown(report.scan)}>
                Show
              </Button>
            )}
          </div>
          <p className="muted">
            Lines you kept as they are; the check lists one again once its text
            changes.
          </p>
          {showKept && groups(byTerms(groupedLines.kept))}
        </section>
      )}
    </section>
  );
}

/**
 * The lines that lack the same terms: the terms and their English, a choice
 * for all of them, then the first lines until the user asks for the rest.
 */
function TermGroup({
  group,
  disabled,
  feedback,
  choose,
}: {
  group: GlossaryGroup;
  disabled: boolean;
  feedback: Feedback;
  choose: Choose;
}) {
  const [all, setAll] = useState(false);
  const open = group.lines.filter((line) => line.state === "open");
  const proposals = open.filter((line) => line.proposal);
  const lines = all ? group.lines : group.lines.slice(0, groupPreview);
  const many = (key: string, keys: string[], choice: Choice, label: string) =>
    keys.length > 1 && (
      <ActionControl
        label={label}
        variant="link"
        disabled={disabled}
        {...feedback(key, "Saving…")}
        onClick={() => choose(key, keys, choice)}
      />
    );
  return (
    <div className="glossary-group">
      <div className="check-results-heading">
        <p className="glossary-terms">
          {group.terms.map((term, index) => (
            <span key={term.source}>
              {index > 0 && <span className="muted"> · </span>}
              <span lang="ja">{term.source}</span>
              <span className="muted"> → </span>
              {term.english}
            </span>
          ))}
          {group.lines.length > 1 && (
            <small>{count(group.lines.length, "line", "lines")}</small>
          )}
        </p>
        {many(
          "glossary-use:" + group.key,
          proposals.map((line) => line.key),
          "use",
          "Use the proposals",
        )}
        {many(
          "glossary-keep:" + group.key,
          open.map((line) => line.key),
          "keep",
          "Keep all",
        )}
      </div>
      <ActionList>
        {lines.map((line) => (
          <GlossaryRow
            key={line.key}
            line={line}
            disabled={disabled}
            feedback={feedback}
            choose={choose}
          />
        ))}
      </ActionList>
      {lines.length < group.lines.length && (
        <Button variant="link" onClick={() => setAll(true)}>
          Show all {group.lines.length.toLocaleString()}
        </Button>
      )}
    </div>
  );
}

/** What the user chose for a line, with Change to choose again. */
function Chosen({
  label,
  line,
  disabled,
  feedback,
  choose,
}: {
  label: string;
  line: GlossaryLine;
  disabled: boolean;
  feedback: Feedback;
  choose: Choose;
}) {
  const key = "glossary-clear:" + line.key;
  return (
    <span className="text-qa-choice">
      {label}
      <ActionControl
        label="Change"
        variant="link"
        inline
        disabled={disabled}
        {...feedback(key, "Saving…")}
        onClick={() => choose(key, [line.key], "clear")}
      />
    </span>
  );
}

/**
 * One line: its Japanese with the terms marked, its English and the
 * proposal or chosen fix, where it is, and the choices left.
 */
function GlossaryRow({
  line,
  disabled,
  feedback,
  choose,
}: {
  line: GlossaryLine;
  disabled: boolean;
  feedback: Feedback;
  choose: Choose;
}) {
  // A draft belongs to the line as it was when editing began, so a saved
  // fix, or any other change to the line, closes it.
  const version = [line.key, line.state, line.text ?? ""].join("\u0000");
  const [editing, setEditing] = useState<{ version: string; text: string }>();
  const draft = editing?.version === version ? editing.text : null;
  const setDraft = (text: string | null) =>
    setEditing(text === null ? undefined : { version, text });
  const editKey = "glossary-edit:" + line.key;
  const fix = line.state === "fix" ? line.text : line.proposal;
  const rows: LineChangeRow[] = [
    { label: "Japanese", text: line.source, lang: "ja", marks: line.terms },
    ...(fix !== undefined && line.state !== "kept" && draft === null
      ? [
          { label: "Now", text: line.live, change: "removed" as const },
          {
            label: line.choice === "edit" ? "Your fix" : "Proposal",
            text: fix,
            change: "added" as const,
          },
        ]
      : [{ label: "Now", text: line.live }]),
  ];
  const place = `${line.file} · ${textLocation(line.pointer)}`;
  return (
    <ActionRow
      label={
        <>
          <LineChange rows={rows} />
          {draft !== null && (
            <dl className="line-change glossary-fix">
              <dt>
                <label htmlFor={editKey}>Your fix</label>
              </dt>
              <dd>
                <textarea
                  id={editKey}
                  autoFocus
                  value={draft}
                  rows={Math.max(2, draft.split("\n").length)}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </dd>
            </dl>
          )}
          <small className="glossary-place">
            {place}
            {line.state === "open" && draft === null && (
              <Button
                variant="link"
                disabled={disabled}
                onClick={() => setDraft(line.proposal ?? line.live)}
              >
                Write a fix
              </Button>
            )}
          </small>
        </>
      }
    >
      {draft !== null ? (
        <>
          <ActionControl
            label="Save fix"
            disabled={disabled || draft === line.live}
            {...feedback(editKey, "Saving…")}
            onClick={() => choose(editKey, [line.key], "edit", draft)}
          />
          <Button disabled={disabled} onClick={() => setDraft(null)}>
            Cancel
          </Button>
        </>
      ) : line.state === "fix" ? (
        <Chosen
          label={
            line.choice === "edit" ? "Using your fix" : "Using the proposal"
          }
          line={line}
          disabled={disabled}
          feedback={feedback}
          choose={choose}
        />
      ) : line.state === "kept" ? (
        <Chosen
          label="Keeping the text"
          line={line}
          disabled={disabled}
          feedback={feedback}
          choose={choose}
        />
      ) : (
        <>
          {line.proposal && (
            <ActionControl
              label="Use proposal"
              disabled={disabled}
              {...feedback("glossary-use:" + line.key, "Saving…")}
              onClick={() =>
                choose("glossary-use:" + line.key, [line.key], "use")
              }
            />
          )}
          <ActionControl
            label="Keep text"
            disabled={disabled}
            {...feedback("glossary-keep:" + line.key, "Saving…")}
            onClick={() =>
              choose("glossary-keep:" + line.key, [line.key], "keep")
            }
          />
        </>
      )}
    </ActionRow>
  );
}
