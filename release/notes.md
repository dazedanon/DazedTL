<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Settings:** the Model menu no longer says "Settings has unsaved changes" after you change a Translation default and change it back, when there was nothing to save or revert.
- **GameUpdate:** players' GameUpdate and the in-game update check reach GitGud again; since 2 November GitGud answered them with "403" unless they sent a header it now asks apps for. A game set up before needs its GameUpdate files again, with **Recreate GameUpdate files** in Guided steps or by asking your assistant to install GameUpdate again, then a push; players whose GameUpdate still fails download that patch once from the repository page.
- **Updates:** DazedTL can download its own updates from GitGud again when GitHub can't be reached.
