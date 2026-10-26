<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Context:** a failed **Save context** shows its reason beside the button, and it and any other failed file write now name the file and why (for example that it is read-only), and a leftover Git lock says another Git process is using the game instead of "The operation could not finish."
- **Inspect:** in **File contents**, every line after a message of more than one row showed beside another line's source text; each message now shows as one line beside its own source.
- **Translate:** a stopped Batch that had nothing new to send for a file no longer kept Other event text open while every file read **Applied**, and the file's Lines show the run that translated it.
