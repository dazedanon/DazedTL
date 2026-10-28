<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Settings:** **Thinking effort** under the model options picks how hard the model thinks, for Claude, OpenAI, Gemini, DeepSeek, Kimi and Mistral models and those models on OpenRouter. It offers only the levels each model takes, and **Provider default**, which sends none as every run did before, stays the default and names the provider's own level where DazedTL knows it. The cost review before you approve a Guided or Assistant-led run shows the effort it sends, the note about unestimated thinking tokens follows it, and a provider that refuses the effort stops the run with one message instead of failing every request.

### Fixed

- **Assistant-led:** **Spent** and **Recorded usage** of a Claude Live run on OpenRouter or a **Custom / local** host now price its cache as Guided and Anthropic do, cache reads at 0.05 times input instead of 0.1 and cache writes at 1.25 times instead of 1, and earlier runs show the corrected figure when you open them again.
- **OpenAI:** cache hits on OpenAI's own API now cost what OpenAI bills for each model, half the input price on GPT-4o, GPT-4o mini, o1 and o3-mini, a quarter on GPT-4.1, o3 and o4-mini and a twentieth on GPT-6.1 Sol and Terra, instead of a tenth on every model. The cost of new Guided runs, new OpenAI Batch estimates and Assistant-led's **Spent** and **Recorded usage**, earlier runs included, show the corrected figures; costs Guided already recorded stay as they were.
