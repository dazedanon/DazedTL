<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** Claude estimates now count input tokens the way Anthropic bills them. They used to count only the shared instructions that way and the rest with a generic count, so a large Batch estimate read about 10% low: 19.2 instead of 21.5 million input tokens on a 970-map game.
- **Assistant-led:** API estimates on Claude now count input tokens the way Anthropic bills them; a large estimate used to read about a third low.
