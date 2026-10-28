<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Assistant-led:** **Spent** and **Recorded usage** of a Claude Live run on OpenRouter or a **Custom / local** host now price its cache as Guided and Anthropic do, cache reads at 0.05 times input instead of 0.1 and cache writes at 1.25 times instead of 1, and earlier runs show the corrected figure when you open them again.
- **OpenAI:** cache hits on OpenAI's own API now cost what OpenAI bills for each model, half the input price on GPT-4o, GPT-4o mini, o1 and o3-mini, a quarter on GPT-4.1, o3 and o4-mini and a twentieth on GPT-6.1 Sol and Terra, instead of a tenth on every model. The cost of new Guided runs, new OpenAI Batch estimates and Assistant-led's **Spent** and **Recorded usage**, earlier runs included, show the corrected figures; costs Guided already recorded stay as they were.
