<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Images:** an image your assistant's investigation excluded no longer reads Skipped once you tick it, so **Copy translation task** includes it instead of saying the translation skipped every image.
- **Images:** resuming an image Batch translation no longer stops with "This connection does not support provider batch jobs." while an OpenRouter connection's check has failed or a connection without Batch is selected; it keeps the settings it started with.
