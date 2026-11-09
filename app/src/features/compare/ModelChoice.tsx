import type { CompareChoice } from "../../api/contracts";

/** A column's model on one of Settings' connections, with the connection's
 * name and what the column changes from the game's settings. */
export type ChosenModel = CompareChoice & { connection: string };

/** The choice a comparison sends, without what only the page shows. */
export const sent = ({ connection: _name, ...choice }: ChosenModel) => choice;
