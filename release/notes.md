<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Glossary:** adding names to a game glossary whose characters are headed `# Game Characters · キャラクター` or `# game characters` no longer starts a second `# Game Characters` section, in Guided and Assistant-led: the next glossary write merges a category's duplicate or decorated sections into its first one, keeping its header and each row once. A database pass also no longer adds `ネーナ (Nena)` beside a hand-written `ニーナ / ネーナ (Nina)`, after which Assistant-led's glossary import refused the glossary as conflicting: the hand-written row stays, and the run log names the translation it kept out.
