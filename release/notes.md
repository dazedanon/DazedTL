<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Estimates:** an API estimate made before this update and not yet approved may read as outdated once, in Guided and Assistant-led, because its Batch price now comes only from the provider's own Batch discount; estimate again to approve it. Runs already approved or sent keep running, collecting and resuming without a new approval.

### Fixed

- **DeepSeek:** what a run spent, Assistant-led's **Spent** and **Recorded usage** and Guided's cost, no longer charges the peak price for every request: requests DeepSeek answered outside its peak hours now cost half, as DeepSeek bills them; requests recorded before this update keep the peak price.
- **Recorded cost:** what a Guided Live run spent now charges prompt text the provider's cache answered at its cache price, as DeepSeek, OpenAI, Kimi and others bill it and as Assistant-led's **Spent** does, instead of the full input price, and counts Gemini's thinking as output; runs recorded before this update keep their cost.
- **Assistant-led:** after a guidance edit, your assistant can again correct a line that organizing kept from an earlier run: the newest run takes the correction, where before both runs refused it. A correction now also keeps the review of each line it leaves unchanged.
- **Assistant-led:** an API Batch on OpenAI no longer sends its Batches one at a time, each as big as the whole Batch token allowance, which made a big game slow and could leave it waiting for capacity until a Guided Batch on the same connection finished: each Batch now takes at most a quarter of the allowance, as Guided's do, and several run at once; after one fails, those already sent still finish, and no further one is sent until **Resume saved run**. When one's sending is left uncertain, for example by a dropped connection, or its results do not match its requests, those already sent still finish too, and the run then waits for that Batch to be attached with **Attach provider job**. Runs approved before this update keep sending one at a time.
