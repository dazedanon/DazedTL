<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Guided:** when a rerun resends lines between ones an earlier run translated, a request now always shows the model the lines just before them with their earlier translation, also when it holds a single stretch of the scene, so the voice and tense carry on from the reused English; runs started before this update send what they did.
- **Assistant-led:** in a Live run, each later part of a scene too long for one request now also sees the English already translated for the lines before it, as Guided's Live requests do, so the narration's tense and how characters address each other carry across the split.
- **Assistant-led:** on RPG Maker, a request now shows the model an actor's English name in place of `\N[n]`, and of a `\V[n]` the game sets to that name, as Guided does, when the actor's glossary row names its actor ID, so the English around it stays grammatical and fits the actor's gender; the game keeps its codes.

### Fixed

- **DeepSeek:** what a run spent, Assistant-led's **Spent** and **Recorded usage** and Guided's cost, no longer charges the peak price for every request: requests DeepSeek answered outside its peak hours now cost half, as DeepSeek bills them; requests recorded before this update keep the peak price.
