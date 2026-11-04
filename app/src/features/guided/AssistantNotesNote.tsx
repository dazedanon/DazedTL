import { HelpPopover } from "../../ui/HelpPopover";
import { assistantNotes, guidanceTitle } from "./guidanceReview";

/** What the assistant notes are, beside each method's editor of them. */
export function AssistantNotesNote() {
  return (
    <>
      Notes every assistant reads first and keeps current. Never sent with
      translation requests.{" "}
      <HelpPopover label={guidanceTitle(assistantNotes)}>
        Saved as AGENTS.md in the game folder and kept in the game&apos;s Git,
        so they reach other computers and assistants. Players never download
        them.
      </HelpPopover>
    </>
  );
}
