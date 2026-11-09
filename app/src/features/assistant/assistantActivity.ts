/** An assistant active this recently may still be at work in the game folder. */
const RECENT_MINUTES = 15;

/**
 * Whether an assistant last active at `at` may still be at work, so a
 * dialog that sets its work aside asks the user to stop its session first.
 */
export function mayStillBeWorking(at: string | null | undefined, now: number) {
  return !!at && now - Date.parse(at) < RECENT_MINUTES * 60_000;
}
