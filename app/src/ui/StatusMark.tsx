import type { ReactNode } from "react";
import {
  type DisplayState,
  displayLabels,
  displayMarks,
} from "./displayStatus";
import { StatusIcon } from "./StatusIcon";
import { useOutcomeHeading } from "./FeedbackOwners";

/**
 * A work item's state as its mark and word, the same on every screen. A
 * feature's own reason belongs beside it, in the item's detail.
 */
export function StatusMark({
  state,
  size = 14,
  pending = false,
}: {
  state: DisplayState;
  size?: number;
  /** Shows the working mark while an action on the item runs. */
  pending?: boolean;
}) {
  return (
    <span className="status-mark" data-state={state}>
      <StatusIcon
        status={pending ? "active" : displayMarks[state]}
        size={size}
      />
      <span>{displayLabels[state]}</span>
    </span>
  );
}

/**
 * A list row's title led by its state's mark, with the state's word after
 * it; the row's description lines up with the title. A row whose state the
 * app cannot observe keeps the mark's space blank, so titles still align.
 * `quiet` keeps the word for screen readers and the mark's tooltip only,
 * for a row whose panel already shows the same state.
 */
export function StatusHeading({
  state,
  title,
  pending = false,
  quiet = false,
  outcomeOf,
}: {
  state?: DisplayState;
  title: ReactNode;
  pending?: boolean;
  quiet?: boolean;
  /**
   * The action key whose result this heading shows, such as the build an
   * archive came from. While it says Done or Applied, that action's control
   * leaves out a success that would say it again.
   */
  outcomeOf?: string;
}) {
  useOutcomeHeading(outcomeOf, pending ? "working" : state);
  return (
    <span
      className="status-heading"
      data-state={state}
      title={quiet && state ? displayLabels[state] : undefined}
    >
      {state ? (
        <StatusIcon status={pending ? "active" : displayMarks[state]} />
      ) : (
        <span className="status-heading-blank" aria-hidden="true" />
      )}
      <strong>{title}</strong>
      {state && (
        <span className={quiet ? "sr-only" : "status-heading-state"}>
          {displayLabels[state]}
        </span>
      )}
    </span>
  );
}
