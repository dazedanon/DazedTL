<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Settings:** **Thinking effort** under the model options picks how hard the model thinks, for Claude, OpenAI, Gemini, DeepSeek, Kimi and Mistral models and those models on OpenRouter. It offers only the levels each model takes, and **Provider default**, which sends none as every run did before, stays the default and names the provider's own level where DazedTL knows it. The cost review before you approve a Guided or Assistant-led run shows the effort it sends, the note about unestimated thinking tokens follows it, and a provider that refuses the effort stops the run with one message instead of failing every request.

### Changed

- **Estimates:** the whole-game **Cost estimate** and an Assistant-led estimate waiting on **Progress** made before an update that corrects DazedTL's prices now show the corrected price the next time you see them, and approving approves that price, instead of keeping the old price until a setting changed. Claude estimates, which can't be priced again that way, ask you to **Estimate again** once. Runs you already approved keep the price you approved.

### Fixed

- **OpenAI on OpenRouter or a Custom / local host:** Live cache hits and cache writes of OpenAI models now cost what OpenAI bills for them on its own API, for example half the input price on GPT-4o, a quarter on GPT-4.1 and a twentieth on GPT-6.1 Sol and Terra, with cache writes at 1.25 times input on GPT-5.6 and later, instead of a tenth for every read and the input price for writes. The cost of new Guided runs and Assistant-led's **Spent** and **Recorded usage**, earlier runs included, show the corrected figures; costs Guided already recorded and OpenRouter Batch prices stay as they were.
