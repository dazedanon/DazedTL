/** What a task has reviewed and ready to go into the game, from observed state. */

export type PendingPartId = "images";

export interface PendingPart {
  id: PendingPartId;
  title: string;
  /** The amount in words, such as "12 images". */
  summary: string;
}

/** Each task's work that is ready to apply. */
export type PendingInput = {
  /** Images reviewed and ready to apply. */
  images: number;
};

const parts: Record<
  PendingPartId,
  { title: string; one: string; many?: string }
> = {
  images: { title: "Images", one: "image" },
};

/** The part a task applies, or null while it has nothing ready. */
export function pendingPart(
  id: PendingPartId,
  input: PendingInput,
): PendingPart | null {
  const count = input[id];
  if (!count) return null;
  const { title, one, many = one + "s" } = parts[id];
  return {
    id,
    title,
    summary: `${count.toLocaleString()} ${count === 1 ? one : many}`,
  };
}
