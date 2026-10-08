import { useState } from "react";
import { messageOf } from "../../../api/errors";
import { imagesApi } from "../../../api/images";
import { pluginsApi } from "../../../api/plugins";
import type {
  ImagePreview,
  Job,
  PluginPreview,
  Preview,
} from "../../../api/contracts";
import { useAction } from "../../../state/useAction";
import type { DisplayState } from "../../../ui/displayStatus";
import {
  applyOrder,
  type PendingPart,
  type PendingPartId,
  pendingSummary,
  reviewSignature,
} from "../pending";

/** A part of an open pending changes review, and how its apply went. */
export type PartReview = PendingPart & {
  preview?: Preview | ImagePreview | PluginPreview;
  state: DisplayState;
  message: string;
};

/** What a Guided text part previews: its action, options and files. */
export type GuidedRequest = {
  name: string;
  options: Record<string, unknown>;
  files?: string[];
};

/**
 * One review and one Apply for everything waiting to go into the game. Each
 * part keeps its own preview, validation and receipts; Apply runs the parts
 * in order and reports each one.
 */
export function usePendingChanges({
  projectId,
  settle,
  guided,
  preparePreview,
  execute,
  lastExecuted,
  whenFinished,
}: {
  projectId: string;
  settle: () => Promise<unknown>;
  /** The Guided preview each text part makes. */
  guided: (part: PendingPart) => GuidedRequest;
  preparePreview: (
    name: string,
    options: Record<string, unknown>,
    files?: string[],
  ) => Promise<Preview>;
  execute: (preview: Preview) => Promise<void>;
  lastExecuted: () => { token: string; job: Job } | null;
  whenFinished: (id: string) => Promise<{ status: string; message: string }>;
}) {
  const action = useAction({ after: settle });
  const [review, setReview] = useState<PartReview[] | null>(null);
  // Whether Apply ran on this review, which then reports its outcome.
  const [attempted, setAttempted] = useState(false);
  // The control that opened the review, the one that reports beside itself.
  const [origin, setOrigin] = useState("");
  const update = (id: PendingPartId, patch: Partial<PartReview>) =>
    setReview(
      (current) =>
        current &&
        current.map((part) => (part.id === id ? { ...part, ...patch } : part)),
    );
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
  const prepare = async (part: PendingPart) => {
    if (part.id === "plugins")
      return (await pluginsApi.action(projectId, "preview_apply")).preview;
    if (part.id === "images")
      return (
        await imagesApi.action(projectId, "preview_apply", {
          asset_ids: await readyImages(),
        })
      ).preview;
    const request = guided(part);
    return preparePreview(request.name, request.options, request.files);
  };
  const applyPart = async (part: PartReview) => {
    if (part.id === "plugins") {
      await pluginsApi.action(projectId, "apply", {
        token: (part.preview as PluginPreview).token,
      });
      return;
    }
    if (part.id === "images") {
      await imagesApi.action(projectId, "apply", {
        token: (part.preview as ImagePreview).token,
      });
      return;
    }
    const request = guided(part);
    // Text, rewraps and QA fixes share the Guided review, which keeps one
    // preview at a time, so each is previewed again just before it runs and
    // must match what was reviewed. Images and plugin files keep their own
    // one-use tokens.
    const fresh = await preparePreview(
      request.name,
      request.options,
      request.files,
    );
    if (reviewSignature(fresh) !== reviewSignature(part.preview as Preview))
      throw new Error(
        `${part.title} changed since you reviewed it. Review it again.`,
      );
    await execute(fresh);
    const ended = await whenFinished(lastExecuted()!.job.id);
    if (ended.status !== "complete")
      throw new Error(ended.message || `${part.title} did not finish.`);
  };
  /**
   * Prepares every part's review, in apply order. It opens once the action
   * and its refresh settle, so Apply all starts ready instead of meeting the
   * duplicate-submission guard; until then the clicked control shows the wait.
   */
  const open = (parts: PendingPart[], from = origin) => {
    setOrigin(from);
    return action
      .run(
        async () => {
          const reviewed: PartReview[] = [];
          for (const id of applyOrder) {
            const part = parts.find((item) => item.id === id);
            if (!part) continue;
            if (part.held) {
              reviewed.push({ ...part, state: "skipped", message: part.held });
              continue;
            }
            try {
              reviewed.push({
                ...part,
                preview: await prepare(part),
                state: "ready",
                message: "",
              });
            } catch (error) {
              reviewed.push({
                ...part,
                state: "blocked",
                message: messageOf(error),
              });
            }
          }
          return reviewed;
        },
        "",
        "pending:review",
      )
      .then((outcome) => {
        if (outcome.ok) {
          setAttempted(false);
          setReview(outcome.value);
        }
        return outcome;
      });
  };
  /** Applies the ready parts in order; a failed part leaves the rest going. */
  const apply = () =>
    action
      .run(
        async () => {
          const parts = (review || []).filter((part) => part.state === "ready");
          const done: PartReview[] = [];
          setAttempted(true);
          for (const part of parts) {
            update(part.id, { state: "working", message: "" });
            try {
              await applyPart(part);
              update(part.id, { state: "applied", message: "" });
              done.push(part);
            } catch (error) {
              update(part.id, { state: "blocked", message: messageOf(error) });
            }
          }
          // Everything applied: the review closes and says so once.
          if (done.length === parts.length) {
            setReview(null);
            return `${pendingSummary(done)} applied.`;
          }
          return "";
        },
        "",
        "pending:apply",
      )
      .then((outcome) => {
        if (outcome.ok && outcome.value)
          action.succeed(outcome.value, "pending:apply");
        return outcome;
      });
  /**
   * The parts a new review would retry: those not applied, except rewraps
   * and QA fixes held for parts that went in, which need a new check.
   */
  const applied = (review || []).some((part) => part.state === "applied");
  const remaining = (review || [])
    .filter((part) => part.state !== "applied")
    .filter((part) => !part.held || !applied);
  return {
    review,
    attempted,
    open,
    apply,
    remaining: remaining.length,
    /** Prepares a new review of the parts that did not apply. */
    retry: () =>
      open(
        remaining.map(
          ({ preview: _preview, state: _state, message: _message, ...part }) =>
            part,
        ),
      ),
    close: () => {
      setReview(null);
      action.clear();
    },
    busy: action.busy,
    key: action.key,
    error: action.error,
    notice: action.notice,
    /** Pending, failure and success for the control `from` that opened it. */
    feedback: (from: string) => {
      const own = origin === from;
      return {
        pending: own && action.busy && action.key === "pending:review",
        error:
          own &&
          (action.key === "pending:review" ||
            (action.key === "pending:apply" && !review))
            ? action.error
            : "",
        notice: own && action.key === "pending:apply" ? action.notice : "",
      };
    },
  };
}

export type PendingChanges = ReturnType<typeof usePendingChanges>;
