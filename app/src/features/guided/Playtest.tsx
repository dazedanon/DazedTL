/**
 * The release playtest as both methods show it: where it stands, each
 * problem with the task that fixes it and a capture when the tour saw it,
 * and what the tour reached. Guided shows it in its Text QA task, whose
 * assistant runs it, with the problems in a sheet of their own.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { PlaytestProblem, PlaytestState } from "../../api/contracts";
import { api } from "../../api/client";
import { languageTag } from "../../app/languages";
import { useLanguages } from "../../app/LanguagesProvider";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { Notice } from "../../ui/Notice";
import { StatusHeading } from "../../ui/StatusMark";
import { StatusPanel } from "../../ui/StatusPanel";
import type { DisplayState } from "../../ui/displayStatus";
import {
  playtestCoverage,
  playtestDisplay,
  playtestFix,
  playtestGroups,
  playtestPhase,
  playtestReach,
  playtestStopping,
  playtestSummary,
  playtestTitle,
  playtestWhere,
} from "./playtestView";

/** Rows a kind shows before its explicit Show all. */
const groupPreview = 10;

export function PlaytestWork({
  projectId,
  playtest,
  running,
  progress,
  failed = "",
  rerun = "Run the playtest again to check the current files.",
  idle = "DazedTL plays the game in a hidden window and writes nothing into it.",
  compact = false,
  stop,
  waiting = false,
  focus,
}: {
  projectId: string;
  playtest: PlaytestState;
  /** A playtest is playing the game now. */
  running: boolean;
  /** What the running playtest is doing, such as "Playing 3 of 9: Menu screens". */
  progress?: string;
  /** Why the last playtest started did not finish, when it did not. */
  failed?: string;
  /** How an outdated playtest runs again. */
  rerun?: string;
  /** What happens before the first playtest. */
  idle?: string;
  /** The problems open in a sheet from the coverage line, for a page that
   * shows the playtest beside other work. */
  compact?: boolean;
  /** Stops the running playtest, beside its progress. */
  stop?: ReactNode;
  /** A copied task's assistant plays the game again before it finishes. */
  waiting?: boolean;
  /** Text QA's focus, which a line QA can't take is outside of. */
  focus?: string;
}) {
  const phase = playtestPhase(playtest, running);
  // A report the game outgrew, or one stopped by a crash the assistant
  // fixes, waits for its next play.
  const stopped =
    phase === "blocked" &&
    !playtest.unreadable &&
    playtestStopping(playtest).length > 0;
  const state: DisplayState =
    waiting && (phase === "outdated" || stopped)
      ? "waiting"
      : playtestDisplay[phase];
  const [capture, setCapture] = useState<PlaytestProblem | null>(null);
  const [strings, setStrings] = useState<PlaytestProblem | null>(null);
  const [coverage, setCoverage] = useState(false);
  const [report, setReport] = useState(false);
  // While a playtest runs, the last report's problems are about to change.
  const { source } = useLanguages();
  const groups =
    playtest.unreadable || running
      ? []
      : playtestGroups(playtest.problems, source);
  const reached = playtestCoverage(playtest);
  const problems = (
    <PlaytestProblems
      groups={groups}
      since={!!playtest.since}
      focus={focus}
      onCapture={setCapture}
      onStrings={setStrings}
    />
  );
  return (
    <>
      <StatusPanel
        title="Playtest"
        state={state}
        progress={phase === "running" ? progress : undefined}
        description={
          phase === "not_started"
            ? idle
            : phase === "running"
              ? "DazedTL is playing the game; this takes a few minutes."
              : stopped && waiting
                ? "The game stops before the playtest can play it; your assistant fixes that and plays it again."
                : phase === "blocked"
                  ? playtest.unreadable ||
                    `The playtest could not play the game. ${playtest.gaps[0] || ""}`.trim()
                  : phase === "outdated"
                    ? `The game changed after this playtest. ${rerun}`
                    : playtestSummary(playtest)
        }
        help="It checks the game's files, then plays the title, New Game, every menu screen, a save and a load, a shop, a battle and the screens plugins add, with every item and skill on hand. Problems the tour saw come with a capture; the rest were found in the files. Problems in translated text go to Text QA's review."
      >
        {phase === "running" && stop && (
          <p className="playtest-coverage">{stop}</p>
        )}
        {/* A report that could not play the game reached no stops, and
            its problems found in the files still open. */}
        {phase !== "not_started" &&
          phase !== "running" &&
          !playtest.unreadable &&
          (reached || (compact && groups.length > 0)) && (
            <p className="playtest-coverage">
              {reached && (
                <>
                  <span>{reached}</span>
                  <Button variant="link" onClick={() => setCoverage(true)}>
                    {playtest.gaps.length
                      ? `${playtest.gaps.length.toLocaleString()} not reached`
                      : "Coverage"}
                  </Button>
                </>
              )}
              {compact && groups.length > 0 && (
                <Button variant="link" onClick={() => setReport(true)}>
                  Problems
                </Button>
              )}
            </p>
          )}
      </StatusPanel>
      {failed && !running && (
        <Notice tone="warning">
          <span>The last playtest did not finish: {failed}</span>
        </Notice>
      )}
      {!compact && problems}
      {report && groups.length > 0 && (
        <Modal
          label="Playtest problems"
          onDismiss={() => setReport(false)}
          size="lg"
        >
          <DialogHeader
            title="Playtest problems"
            description={playtestSummary(playtest)}
            onClose={() => setReport(false)}
          />
          <DialogBody>{problems}</DialogBody>
        </Modal>
      )}
      {capture && (
        <PlaytestCapture
          projectId={projectId}
          problem={capture}
          onClose={() => setCapture(null)}
        />
      )}
      {strings && (
        <PlaytestStrings problem={strings} onClose={() => setStrings(null)} />
      )}
      {coverage && (
        <PlaytestReach playtest={playtest} onClose={() => setCoverage(false)} />
      )}
    </>
  );
}

/** Problems by kind, each with where it is, the task that fixes it and
 * what the tour saw. */
function PlaytestProblems({
  groups,
  since,
  focus,
  onCapture,
  onStrings,
}: {
  groups: ReturnType<typeof playtestGroups>;
  /** The report compares with the playtest before it. */
  since: boolean;
  focus?: string;
  onCapture: (problem: PlaytestProblem) => void;
  onStrings: (problem: PlaytestProblem) => void;
}) {
  const { source } = useLanguages();
  const [expanded, setExpanded] = useState<string[]>([]);
  if (!groups.length) return null;
  return (
    <div className="playtest-problems">
      {groups.map((group) => (
        <section key={group.kind} aria-label={group.title}>
          <h3>
            {group.title} · {group.problems.length.toLocaleString()}
          </h3>
          <ActionList>
            {(expanded.includes(group.kind)
              ? group.problems
              : group.problems.slice(0, groupPreview)
            ).map((problem, index) => (
              <ActionRow
                key={index}
                label={
                  <>
                    <strong className="playtest-title">
                      {playtestTitle(problem, source)}
                      {problem.new && since && (
                        <span className="playtest-new">New</span>
                      )}
                    </strong>
                    <small>{problem.note}</small>
                    <small>
                      {[playtestWhere(problem), playtestFix(problem, focus)]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  </>
                }
              >
                {problem.seen?.capture && (
                  <Button variant="link" onClick={() => onCapture(problem)}>
                    View
                  </Button>
                )}
                {problem.texts && (
                  <Button variant="link" onClick={() => onStrings(problem)}>
                    Show strings
                  </Button>
                )}
              </ActionRow>
            ))}
          </ActionList>
          {group.problems.length > groupPreview &&
            !expanded.includes(group.kind) && (
              <Button
                variant="link"
                onClick={() => setExpanded((value) => [...value, group.kind])}
              >
                Show all {group.problems.length.toLocaleString()}
              </Button>
            )}
        </section>
      ))}
    </div>
  );
}

/** What the tour saw when it found a problem. */
function PlaytestCapture({
  projectId,
  problem,
  onClose,
}: {
  projectId: string;
  problem: PlaytestProblem;
  onClose: () => void;
}) {
  const { source } = useLanguages();
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  // The capture loads once when the sheet opens.
  const name = useRef(problem.seen!.capture!);
  useEffect(() => {
    api.guided.playtestCapture(projectId, name.current).then(
      (value) => setUrl(value.url),
      (reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
    );
  }, [projectId]);
  return (
    <Modal label="Playtest capture" onDismiss={onClose} size="lg">
      <DialogHeader
        title={playtestTitle(problem, source)}
        description={playtestWhere(problem)}
        onClose={onClose}
      />
      <DialogBody className="playtest-capture">
        {error && <Notice tone="warning">{error}</Notice>}
        {!url && !error && <p className="muted">Loading…</p>}
        {url && (
          <img
            src={url}
            alt={`The game on ${problem.seen?.scene || "screen"} when the playtest found this`}
          />
        )}
      </DialogBody>
    </Modal>
  );
}

/** A grouped problem's strings, each with whether it can show. */
function PlaytestStrings({
  problem,
  onClose,
}: {
  problem: PlaytestProblem;
  onClose: () => void;
}) {
  const languages = useLanguages();
  const source = languages.source;
  // A placeholder glyph is left in translated text.
  const lang = languageTag(
    problem.check === "placeholder-glyph" ? languages.target : source,
  );
  const texts = problem.texts || [];
  return (
    <Modal label="Strings" onDismiss={onClose} size="lg">
      <DialogHeader
        title={playtestTitle(problem, source)}
        description={problem.evidence || problem.note}
        onClose={onClose}
      />
      <DialogBody>
        <ul className="playtest-strings">
          {texts.map((text, index) => (
            <li key={index}>
              <span lang={lang}>{text.text}</span>
              <small>
                {[
                  text.line ? `Line ${text.line}` : text.pointer,
                  text.seen
                    ? `Seen on ${text.seen.scene || "screen"}`
                    : text.reach && playtestReach[text.reach],
                  !text.seen && text.evidence,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </li>
          ))}
        </ul>
        {(problem.count || 0) > texts.length && (
          <p className="muted">
            The first {texts.length.toLocaleString()} of{" "}
            {(problem.count || 0).toLocaleString()}; the report lists them all.
          </p>
        )}
      </DialogBody>
    </Modal>
  );
}

const stopStates: Record<string, DisplayState> = {
  done: "done",
  failed: "blocked",
  skipped: "skipped",
  "not-reached": "not_started",
  running: "working",
};

/** Where the tour went, and what it could not reach or read. */
function PlaytestReach({
  playtest,
  onClose,
}: {
  playtest: PlaytestState;
  onClose: () => void;
}) {
  return (
    <Modal label="What the playtest reached" onDismiss={onClose} size="md">
      <DialogHeader
        title="What the playtest reached"
        description={playtestCoverage(playtest)}
        onClose={onClose}
      />
      <DialogBody>
        <ActionList>
          {(playtest.coverage?.stops || []).map((stop) => (
            <ActionRow
              key={stop.id}
              label={
                <>
                  <StatusHeading
                    state={stopStates[stop.status]}
                    title={stop.title || stop.id}
                  />
                  {stop.note && <small>{stop.note}</small>}
                </>
              }
            />
          ))}
        </ActionList>
        {playtest.gaps.length > 0 && (
          <section className="playtest-gaps" aria-label="Not reached">
            <h3>Not reached</h3>
            <ul>
              {playtest.gaps.map((gap, index) => (
                <li key={index}>{gap}</li>
              ))}
            </ul>
          </section>
        )}
      </DialogBody>
    </Modal>
  );
}
