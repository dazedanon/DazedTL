<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **OpenAI on OpenRouter or a Custom / local host:** Live cache hits and cache writes of OpenAI models now cost what OpenAI bills for them on its own API, for example half the input price on GPT-4o, a quarter on GPT-4.1 and a twentieth on GPT-6.1 Sol and Terra, with cache writes at 1.25 times input on GPT-5.6 and later, instead of a tenth for every read and the input price for writes. The cost of new Guided runs and Assistant-led's **Spent** and **Recorded usage**, earlier runs included, show the corrected figures; costs Guided already recorded and OpenRouter Batch prices stay as they were.
