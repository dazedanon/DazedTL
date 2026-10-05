/** Text for loosely typed run data; objects never render as "[object Object]". */
export function displayText(value: unknown, fallback = "") {
  return typeof value === "string"
    ? value
    : typeof value === "number" || typeof value === "bigint"
      ? String(value)
      : fallback;
}
