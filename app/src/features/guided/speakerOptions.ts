export const speakerOptions: Record<string, { label: string; help: string }> = {
  NAMES: { label: "Character names", help: "Collect character names with the engine’s name parser for use as translation context." },
  FIRSTLINESPEAKERS: { label: "First-line names", help: "Treat the first line of a dialogue block as its speaker name when the game uses a separate name line." },
  INLINE401SPEAKERS: { label: "Inline names", help: "Detect a speaker name at the start of a dialogue line, before the spoken text (event code 401)." },
  FACENAME101: { label: "Face names", help: "Infer speaker names from face images attached to dialogue (event code 101). Enable only when the game’s face names identify its speakers." },
  AUTONAMEPOPUP101: { label: "AutoNamePopup", help: "Use the AutoNamePopup plugin’s face-to-name mapping for dialogue speakers." },
  SPEAKERS408: { label: "Comment speakers", help: "Collect speaker names from supported comment continuations (event code 408). Use this when the game stores speaker names in comments." },
};

export const commentTextHelp = "Include supported comment continuations (event code 408) in the speaker pass. Enable only when the game displays this comment text to the player.";
