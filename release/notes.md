<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Settings:** a Claude model the price list doesn't know, named with OpenRouter's dotted version, such as `anthropic/claude-opus-4.5` or `anthropic/claude-opus-5.5`, now takes its own per-token price instead of an older Claude Opus's, and Claude 3 Opus's and Claude 3.5 Haiku's dated IDs, such as `claude-3-opus-20240229`, take theirs instead of Sonnet's or a newer Haiku's.
- **Translate:** a Claude model named as Vertex AI, Databricks or a Bedrock ARN name it, such as `vertex_ai/claude-sonnet-5-5`, `databricks-claude-sonnet-4` or `arn:aws:bedrock:...:inference-profile/us.anthropic.claude-...`, now counts as Claude, with Claude's prices and the note that its estimate leaves out thinking.
- **Translate:** a Claude connection whose address only holds Anthropic's name, such as `https://anthropic.company.example`, no longer sends Message Batches there or refuses another host's Claude name as Anthropic's own API would; only Anthropic's own address counts as its API.
- **Settings:** a Claude model ID in capitals, such as `Claude-Opus-5`, saved for Anthropic's own API is now refused with its lowercase ID named, such as `claude-opus-5`, since Anthropic lists its IDs in lower case, and a new run with one no longer starts; a run already created with one still resumes.
- **Translate:** Claude Opus 5.5, Sonnet 5.5, Fable 5.1 and Mythos 5.1 named with a dotted version, such as `claude-opus-5.5`, now price their cache reads at their own rate instead of a tenth of input, so their spending and quotes no longer read too high.
