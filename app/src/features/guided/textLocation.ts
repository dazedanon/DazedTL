/**
 * Where a text sits in an RPG Maker data file, in the editor's terms, from
 * the engine's JSON-pointer locator. Unknown shapes keep their path.
 */
export function textLocation(locator: string) {
  const parts = locator.split("/").filter(Boolean);
  const number = (value: string | undefined) =>
    value !== undefined && /^\d+$/.test(value) ? Number(value) : null;
  const command = (index: number) => {
    const line = number(parts[index]);
    return parts[index - 1] === "list" && line !== null
      ? `command ${line + 1}`
      : null;
  };
  // Maps: /events/{event}/pages/{page}/list/{command}/...
  if (parts[0] === "events" && parts[2] === "pages" && parts[4] === "list") {
    const event = number(parts[1]);
    const page = number(parts[3]);
    const at = command(5);
    if (event !== null && page !== null && at)
      return `Event ${event} · page ${page + 1} · ${at}`;
  }
  const id = number(parts[0]);
  if (id !== null) {
    // Troops: /{troop}/pages/{page}/list/{command}/...
    if (parts[1] === "pages" && parts[3] === "list") {
      const page = number(parts[2]);
      const at = command(4);
      if (page !== null && at) return `Troop ${id} · page ${page + 1} · ${at}`;
    }
    // Common events: /{event}/list/{command}/...
    if (parts[1] === "list") {
      const at = command(2);
      if (at) return `Common event ${id} · ${at}`;
    }
    // Database entries: /{id}/{field}
    if (parts.length === 2) return `Entry ${id} · ${parts[1]}`;
  }
  return parts.join(" › ") || locator;
}
