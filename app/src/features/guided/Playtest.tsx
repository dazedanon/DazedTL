/**
 * The release playtest as both methods show it: where it stands, each
 * problem with the task that fixes it and a capture when the tour saw it,
 * and what the tour reached.
 */

import { useEffect, useRef, useState } from "react";
import type { PlaytestProblem, PlaytestState } from "../../api/contracts";
import { api } from "../../api/client";
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
}: {
  projectId: string;
  playtest: PlaytestState;
  /** A playtest is playing the game now. */
  running: boolean;
  /** What the running playtest is doing, such as "Playing 3 of 9: Menu screens". */
  progress?: string;
  /** Why the last playtest started did not finish, when it did not. */
  failed?: string;
  /** How the user has an outdated playtest run again. */
  rerun?: string;
}) {
  const phase = playtestPhase(playtest, running);
  const [capture, setCapture] = useState<PlaytestProblem | null>(null);
  const [strings, setStrings] = useState<PlaytestProblem | null>(null);
  const [coverage, setCoverage] = useState(false);
  const [expanded, setExpanded] = useState<string[]>([]);
  // While a playtest runs, the last report's problems are about to change.
  const groups =
    playtest.unreadable || running ? [] : playtestGroups(playtest.problems);
  const reached = playtestCoverage(playtest);
  return (
    <>
      <StatusPanel
        title="Playtest"
        state={playtestDisplay[phase]}
        progress={phase === "running" ? progress : undefined}
        description={
          phase === "not_started"
            ? "DazedTL plays the game in a hidden window and writes nothing into it."
            : phase === "running"
              ? "DazedTL is playing the game; this takes a few minutes."
              : phase === "blocked"
                ? playtest.unreadable ||
                  `The playtest could not play the game. ${playtest.gaps[0] || ""}`.trim()
                : phase === "outdated"
                  ? `The game changed after this playtest. ${rerun}`
                  : playtestSummary(playtest)
        }
        help="It checks the game's files, then plays the title, New Game, every menu screen, a save and a load, a shop, a battle and the screens plugins add, with every item and skill on hand. Problems the tour saw come with a capture; the rest were found in the files. Problems in translated text go to Text QA's review."
      >
        {phase !== "not_started" &&
          phase !== "running" &&
          !playtest.unreadable &&
          reached && (
            <p className="playtest-coverage">
              <span>{reached}</span>
              <Button variant="link" onClick={() => setCoverage(true)}>
                {playtest.gaps.length
                  ? `${playtest.gaps.length.toLocaleString()} not reached`
                  : "Coverage"}
              </Button>
            </p>
          )}
      </StatusPanel>
      {failed && !running && (
        <Notice tone="warning">
          <span>The last playtest did not finish: {failed}</span>
        </Notice>
      )}
      {groups.length > 0 && (
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
                          {playtestTitle(problem)}
                          {problem.new && playtest.since && (
                            <span className="playtest-new">New</span>
                          )}
                        </strong>
                        <small>{problem.note}</small>
                        <small>
                          {[playtestWhere(problem), playtestFix(problem)]
                            .filter(Boolean)
                            .join(" · ")}
                        </small>
                      </>
                    }
                  >
                    {problem.seen?.capture && (
                      <Button
                        variant="link"
                        onClick={() => setCapture(problem)}
                      >
                        View
                      </Button>
                    )}
                    {problem.texts && (
                      <Button
                        variant="link"
                        onClick={() => setStrings(problem)}
                      >
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
                    onClick={() =>
                      setExpanded((value) => [...value, group.kind])
                    }
                  >
                    Show all {group.problems.length.toLocaleString()}
                  </Button>
                )}
            </section>
          ))}
        </div>
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
        title={playtestTitle(problem)}
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
  const texts = problem.texts || [];
  return (
    <Modal label="Strings" onDismiss={onClose} size="lg">
      <DialogHeader
        title={playtestTitle(problem)}
        description={problem.evidence || problem.note}
        onClose={onClose}
      />
      <DialogBody>
        <ul className="playtest-strings">
          {texts.map((text, index) => (
            <li key={index}>
              <span lang="ja">{text.text}</span>
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
