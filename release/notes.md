<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Database:** the currency unit after an amount of money, such as 円, and the variable names a plugin draws, such as LL_VariableWindow's label, are now translated in Guided and Assistant-led alike, while other variable names stay as they are, since plugins and scripts may look a variable up by its name; an already translated game shows them as lines left in System.json until its next Database run.
