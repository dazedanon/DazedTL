import type { ContextSetup } from "../../api/contracts";

/** Whether Guidance has every core document saved, and the titles of
 * those it still needs, by each document's definition. */
export function guidanceAvailability(documents: ContextSetup["documents"]) {
  const core = Object.values(documents).filter(
    (document) => document.kind === "core",
  );
  const missing = core
    .filter((document) => !document.exists)
    .map((document) => document.title);
  return {
    complete: !!core.length && !missing.length,
    missing,
    total: core.length,
  };
}
