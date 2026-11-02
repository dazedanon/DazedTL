/**
 * The sections of docs/user-guide.md the app's help links to, by their
 * heading's anchor. The guide tests check each one is still a heading.
 */
export const guideSections = [
  "api-keys-and-models",
  "assistant-led",
  "checkpoints-and-undo",
  "common-problems",
  "contributing",
  "publishing-with-gameupdate",
] as const;
export type GuideSection = (typeof guideSections)[number];
