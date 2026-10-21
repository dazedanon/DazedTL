import type { Job, LayoutWidths } from "../../api/contracts";

/**
 * What saving Line widths reports beside its control: the fit of the applied
 * text to them, or else the save itself, then a portrait width the save
 * lowered to Dialogue, since text beside a portrait is never wider.
 * `asked` holds the widths this visit's save asked for; widths saved later
 * another way, such as measured ones, have their own Dialogue.
 */
export function widthsSaveNotice({
  fitted,
  saved,
  asked,
  widths,
}: {
  fitted: string;
  saved: string;
  asked: LayoutWidths | null;
  widths: LayoutWidths;
}) {
  const report = fitted || saved;
  const lowered =
    report &&
    asked &&
    asked.width === widths.width &&
    asked.faceWidth > widths.faceWidth &&
    widths.faceWidth === widths.width;
  return lowered
    ? `${report} With portrait was lowered to ${widths.faceWidth} to match Dialogue.`
    : report;
}

/**
 * Whether a fit of the applied text to new Line widths is under way. The
 * read that starts a fit names it before it lists it among the operations,
 * so a fit named since this visit opened that no operation shows yet runs,
 * as does a listed one that has not ended.
 */
export function fitRunning({
  named,
  opened,
  listed,
}: {
  named: string | null;
  opened: string | null;
  listed: Pick<Job, "id" | "status"> | undefined;
}) {
  if (listed && listed.id === named)
    return ["ready", "running", "waiting"].includes(listed.status);
  return !!named && named !== opened;
}
