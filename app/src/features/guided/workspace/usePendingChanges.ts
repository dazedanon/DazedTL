import { useState } from "react";
import { messageOf } from "../../../api/errors";
import { imagesApi } from "../../../api/images";
import type { ImagePreview } from "../../../api/contracts";
import { type Observer, useAction } from "../../../state/useAction";
import type { PendingPart } from "../pending";

/** The part an open review applies, and why its last Apply failed. */
export type PartReview = PendingPart & {
  preview: ImagePreview;
  failure: string;
};

/**
 * One task's review and Apply of the work it has ready, with its own
 * preview, validation and receipts.
 */
export function usePendingChanges({
  projectId,
  observer,
}: {
  projectId: string;
  observer: Observer;
}) {
  const action = useAction({ observer });
  const [review, setReview] = useState<PartReview | null>(null);
  // The control that opened the review, the one that reports beside itself.
  const [origin, setOrigin] = useState("");
  // The translated images in the list to translate; one the user took out
  // of the list stays out of the game.
  const readyImages = async () => {
    const ids: string[] = [];
    for (let total = 1; ids.length < total;) {
      const page = await imagesApi.list(projectId, {
        filter: "ready",
        selected_only: true,
        offset: ids.length,
        limit: 500,
      });
      if (!page.items.length) break;
      ids.push(...page.items.map((asset) => asset.id));
      total = page.total;
    }
    return ids;
  };
  const prepare = async () =>
    (
      await imagesApi.action(projectId, "preview_apply", {
        asset_ids: await readyImages(),
      })
    ).preview;
  // Images keep their own one-use tokens.
  const applyPart = (part: PartReview) =>
    imagesApi.action(projectId, "apply", { token: part.preview.token });
  /**
   * Prepares the part's review; a failure reports beside the control that
   * asked. The review opens once the action and its refresh settle, so Apply
   * starts ready instead of meeting the duplicate-submission guard; until
   * then the clicked control shows the wait.
   */
  const open = (part: PendingPart, from = origin) => {
    setOrigin(from);
    return action
      .run(
        async (): Promise<PartReview> => {
          const preview = await prepare();
          if (!preview) throw new Error(`${part.title} has nothing to apply.`);
          return { ...part, preview, failure: "" };
        },
        "",
        "pending:review",
      )
      .then((outcome) => {
        if (outcome.ok) setReview(outcome.value);
        return outcome;
      });
  };
  /** Applies the reviewed part; a failure keeps the review open to retry. */
  const apply = () =>
    action
      .run(
        async () => {
          if (!review || review.failure) return "";
          try {
            await applyPart(review);
          } catch (error) {
            setReview({ ...review, failure: messageOf(error) });
            return "";
          }
          setReview(null);
          return `${review.summary} applied.`;
        },
        "",
        "pending:apply",
      )
      .then((outcome) => {
        if (outcome.ok && outcome.value)
          action.succeed(outcome.value, "pending:apply");
        return outcome;
      });
  return {
    review,
    open,
    apply,
    /** Prepares a new review of a part that did not apply. */
    retry: () => {
      if (!review) return;
      const { id, title, summary } = review;
      return open({ id, title, summary });
    },
    close: () => {
      setReview(null);
      action.clear();
    },
    busy: action.busy,
    key: action.key,
    error: action.error,
    /** Pending, failure and success for the control `from` that opened it. */
    feedback: (from: string) => {
      const own = origin === from;
      return {
        pending: own && action.busy && action.key === "pending:review",
        error:
          own && action.key === "pending:review" && !review ? action.error : "",
        notice: own && action.key === "pending:apply" ? action.notice : "",
      };
    },
  };
}

export type PendingChanges = ReturnType<typeof usePendingChanges>;
