import type { ReactNode } from "react";
import {
  type DisplayState,
  displayLabels,
  displayMarks,
} from "./displayStatus";
import { StatusIcon } from "./StatusIcon";

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
 * it; the row's description lines up with the title.
 */
export function StatusHeading({
  state,
  title,
  pending = false,
}: {
  state: DisplayState;
  title: ReactNode;
  pending?: boolean;
}) {
  return (
    <span className="status-heading" data-state={state}>
      <StatusIcon status={pending ? "active" : displayMarks[state]} />
      <strong>{title}</strong>
      <span className="status-heading-state">{displayLabels[state]}</span>
    </span>
  );
}
