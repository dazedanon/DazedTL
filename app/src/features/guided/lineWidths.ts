import type { LayoutWidths } from "../../api/contracts";

/**
 * What saving Line widths reports beside its control: the fit of the applied
 * text to them, or else the save itself, then a portrait width the save
 * lowered to Dialogue, since text beside a portrait is never wider.
 * `askedPortrait` is the With portrait width this visit's save asked for, or 0.
 */
export function widthsSaveNotice({
  fitted,
  saved,
  askedPortrait,
  widths,
}: {
  fitted: string;
  saved: string;
  askedPortrait: number;
  widths: LayoutWidths;
}) {
  const report = fitted || saved;
  const lowered =
    report &&
    askedPortrait > widths.faceWidth &&
    widths.faceWidth === widths.width;
  return lowered
    ? `${report} With portrait was lowered to ${widths.faceWidth} to match Dialogue.`
    : report;
}
