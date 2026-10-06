/** Text for loosely typed run data; objects never render as "[object Object]". */
export function displayText(value: unknown, fallback = "") {
  return typeof value === "string"
    ? value
    : typeof value === "number" || typeof value === "bigint"
      ? String(value)
      : fallback;
}

const engines: Record<string, string> = {
  MVMZ: "RPG Maker MV / MZ",
  ACE: "RPG Maker VX Ace",
  WOLF: "WOLF RPG",
};
/** The player-facing engine name for a backend engine code. */
export function engineLabel(code: string) {
  return engines[code] || code;
}

/** "2 indexed · 1 examined": counts joined in order, leaving out zeros. */
export function countSummary(
  parts: [count: number | undefined, label: string][],
) {
  return parts
    .filter(([count]) => !!count)
    .map(([count, label]) => `${count!.toLocaleString()} ${label}`)
    .join(" · ");
}
