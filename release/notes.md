<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **DeepSeek:** what a run spent, Assistant-led's **Spent** and **Recorded usage** and Guided's cost, no longer charges the peak price for every request: requests DeepSeek answered outside its peak hours now cost half, as DeepSeek bills them; requests recorded before this update keep the peak price.
- **Assistant-led:** an API Batch on OpenAI no longer sends its Batches one at a time, each as big as the whole Batch token allowance, which made a big game slow and could leave it waiting for capacity until a Guided Batch on the same connection finished: each Batch now takes at most a quarter of the allowance, as Guided's do, and several run at once; after one fails, those already sent still finish, and no further one is sent until **Resume saved run**. Runs approved before this update keep sending one at a time.
- **Recorded cost:** what a Guided Live run spent now charges prompt text the provider's cache answered at its cache price, as DeepSeek, OpenAI, Kimi and others bill it and as Assistant-led's **Spent** does, instead of the full input price, and counts Gemini's thinking as output; runs recorded before this update keep their cost.
