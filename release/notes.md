<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Guide:** the user guide opens inside DazedTL from **Guide** in the sidebar, with its sections beside the text and a search; help on checkpoints, API keys, GameUpdate, speaker names and Assistant-led progress has a **Learn more** link to its section.
- **Settings:** a **Credits** tab thanks the people who built DazedTL and DazedMTLTool, the tool it grew from.
- **Sidebar:** **Share a fix** copies a task for your assistant to write up a fix it made in your game, to post on Discord so DazedTL can handle games like it by itself; the guide's new **Contributing** section explains it.

### Fixed

- **Images:** an image your assistant's investigation excluded no longer reads Skipped once you tick it, so **Copy translation task** includes it instead of saying the translation skipped every image.
- **Images:** resuming an image Batch translation no longer stops with "This connection does not support provider batch jobs." while an OpenRouter connection's check has failed or a connection without Batch is selected; it keeps the settings it started with.
- **Maps & events:** in a project set up by an older version, a speaker whose English name holds a `]` no longer leaves its `[Name]:` label at the start of the message, and an LL_GalgeChoiceWindow or LL_GalgeChoiceWindowMV choice that comes back with too few or too many answers no longer fails the map or writes the wrong choices, is not sent and paid for a second time in a run started after updating, and no longer writes one choice's translation inside another choice that holds its text, such as はい inside はいはい.
