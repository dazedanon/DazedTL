<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Recorded cost:** what a Guided Live run spent now charges prompt text the provider's cache answered at its cache price, as DeepSeek, OpenAI, Kimi and others bill it and as Assistant-led's **Spent** does, instead of the full input price, and counts Gemini's thinking as output; runs recorded before this update keep their cost.
- **DeepSeek:** what a run spent, Assistant-led's **Spent** and **Recorded usage** and Guided's cost, no longer charges the peak price for every request: requests DeepSeek answered outside its peak hours now cost half, as DeepSeek bills them; requests recorded before this update keep the peak price.
