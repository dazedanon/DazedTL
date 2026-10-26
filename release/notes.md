<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Context:** a failed **Save context** shows its reason beside the button, and it and any other failed file write now name the file and why (for example that it is read-only), and a leftover Git lock says another Git process is using the game instead of "The operation could not finish."
- **Inspect:** in **File contents**, every line after a message of more than one row showed beside another line's source text; each message now shows as one line beside its own source.
- **Playtest tools:** installing or removing TL Inspector or Forge no longer says so twice or makes the window jump.
- **Forge:** quick load (Ctrl+Q) no longer crashes some games with an error screen right after loading, such as "Cannot read properties of undefined (reading 'massCharacters')".
- **GameUpdate:** a game translated into Japanese shows players its "Translation update available" message in Japanese; Set up writes the text into the update check's plugin settings, where it can be edited.
