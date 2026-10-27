<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Assistant-led:** an RPG Maker MV/MZ skill's battle messages, such as "%1 casts Fire!", now tell the model which characters and enemies use the skill, as Guided does, so it picks the right pronouns for them; an estimate still waiting for approval asks to be estimated again once.
- **Assistant-led:** when your assistant organizes the text again, such as after a glossary change or a game update, every line that already has a translation keeps it and the new estimate covers only the rest, as Guided does, and requests the provider would read word for word the same are sent once.

### Fixed

- **Assistant-led:** a line an API run left in Japanese because its translation failed counted as translated on **Progress** and was never sent again; it now reads as left, and your assistant's next estimate sends it on its own.
