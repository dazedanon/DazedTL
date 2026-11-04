import { HelpPopover } from "../../ui/HelpPopover";

/** What the assistant notes are, beside each method's editor of them. */
export function AssistantNotesNote() {
  return (
    <>
      Notes every assistant reads first and keeps current. Never sent with
      translation requests.{" "}
      <HelpPopover label="Assistant notes">
        Saved as AGENTS.md in the game folder and kept in the game&apos;s Git,
        so they reach other computers and assistants. Players never download
        them.
      </HelpPopover>
    </>
  );
}
