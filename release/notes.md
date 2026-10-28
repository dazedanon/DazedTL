<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Estimates:** the whole-game **Cost estimate** and an Assistant-led estimate waiting on **Progress** made before an update that corrects DazedTL's prices now show the corrected price the next time you see them, and approving approves that price, instead of keeping the old price until a setting changed. Claude estimates, which can't be priced again that way, ask you to **Estimate again** once. Runs you already approved keep the price you approved.

### Fixed

- **Estimates:** OpenAI Batch estimates on GPT-4.1, GPT-4o, o1, o3, o4-mini, the -pro models and OpenAI's other models before GPT-5 no longer show a lower price for reused instructions, since OpenAI's Batch doesn't cache them on those models. A waiting estimate shows the corrected price the next time you see it; the price you approve was already the higher one and doesn't change.
