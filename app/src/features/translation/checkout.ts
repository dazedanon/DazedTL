import type { TranslationState } from "../../api/contracts";

/** Why the game's tracked files, such as its guidance, can't be saved now;
 * the page's notice says what the checkout needs, and edits stay drafts. */
export const checkoutRefusal = (
  state: Pick<TranslationState, "checkoutIssue">,
) => (state.checkoutIssue ? "Resolve the game folder notice above first." : "");
