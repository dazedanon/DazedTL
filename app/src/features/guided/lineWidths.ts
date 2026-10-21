import type { LayoutWidths } from "../../api/contracts";

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
