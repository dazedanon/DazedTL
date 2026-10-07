import { useId, type ReactNode } from "react";
import type { ForeignWork as Saved } from "../api/contracts";
import { ActionRow } from "./ActionList";
import { countSummary } from "./displayText";
import { StatusMark } from "./StatusMark";

/** "a, b and c" */
const list = (items: string[]) =>
  items.length > 1
    ? `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`
    : items[0] || "";

/**
 * Work the game folder holds for another project: what it holds and the two
 * ways on, each beside what it keeps. Nothing is used or moved until the
 * user picks one.
 */
export function ForeignWork({
  title,
  work,
  counts,
  kept,
  noun,
  next,
  left,
  adopt,
  startOver,
}: {
  title: string;
  work: Saved;
  /** The work's own counts, in order; zeros are left out. */
  counts: [count: number, label: string][];
  /** What using it keeps besides applied items, such as "findings". */
  kept: string[];
  /** The applied items' plural noun, such as "files". */
  noun: string;
  /** What to do once it is used here. */
  next: string;
  /** What starting over leaves behind. */
  left: string;
  adopt: ReactNode;
  startOver: ReactNode;
}) {
  const heading = useId();
  const restore = !work.applied
    ? ""
    : work.restorable >= work.applied
      ? ", which can still be restored"
      : work.restorable
        ? `; ${work.restorable} of ${work.applied} can still be restored`
        : ", which can't be restored here";
  return (
    <section className="action-list foreign-work" aria-labelledby={heading}>
      <div className="foreign-work-header panel-header">
        <div className="foreign-work-title">
          <h3 id={heading}>{title}</h3>
          <StatusMark state="needs_review" />
        </div>
        <p>
          Another DazedTL project saved it, for example before this game was
          moved or copied, or in another profile. Nothing is used or moved until
          you choose.
        </p>
        <p>
          {[
            "Saved " + new Date(work.saved).toLocaleString(),
            countSummary(counts),
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      <ActionRow
        title="Use saved progress"
        description={
          work.blocked ||
          `Keeps ${list(work.applied ? [...kept, "applied " + noun] : kept)}${restore}. ${next}`
        }
      >
        {adopt}
      </ActionRow>
      <ActionRow
        title="Start over"
        description={`Moves it to ${work.archive} in the game folder and starts fresh.${left ? " " + left : ""}`}
      >
        {startOver}
      </ActionRow>
    </section>
  );
}
