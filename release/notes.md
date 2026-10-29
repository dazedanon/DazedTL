<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Settings:** a Claude model the price list doesn't know, named with OpenRouter's dotted version, such as `anthropic/claude-opus-4.5` or `anthropic/claude-opus-5.5`, now takes its own per-token price instead of an older Claude Opus's, and Claude 3 Opus's and Claude 3.5 Haiku's dated IDs, such as `claude-3-opus-20240229`, take theirs instead of Sonnet's or a newer Haiku's.
- **Translate:** a Claude model named as Vertex AI, Databricks or a Bedrock ARN name it, such as `vertex_ai/claude-sonnet-5-5`, `databricks-claude-sonnet-4` or `arn:aws:bedrock:...:inference-profile/us.anthropic.claude-...`, now counts as Claude, with Claude's prices and the note that its estimate leaves out thinking.
- **Translate:** a Claude connection whose address only holds Anthropic's name, such as `https://anthropic.company.example`, no longer sends Message Batches there or refuses another host's Claude name as Anthropic's own API would; only Anthropic's own address counts as its API.
- **Settings:** a Claude model ID in capitals, such as `Claude-Opus-5`, saved for Anthropic's own API is now refused with its lowercase ID named, such as `claude-opus-5`, since Anthropic lists its IDs in lower case, and a run saved with one no longer starts or resumes.
- **Translate:** an NScripter game's choices (`csel`) are now written with their own translation, where each choice was replaced with the dialogue line translated before it, and a file whose choices come before any dialogue no longer fails.
- **Translate:** an RPG Maker plugin file with a quest name (`QuestName`) before any `txtSubject` line, or after one without a line break, no longer fails, and a quest name's own line break is now sent as a space.
- **Translate:** a CSV file has no speaker column unless one is chosen, where the target column was read as each row's speaker, so a row whose target held text was sent with it as a speaker name and each row's translation was written to the next row; a speaker column set to the target column no longer shifts translations either.
