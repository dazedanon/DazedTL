<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** translating a file again after an earlier run translated part of it sends the remaining lines together, up to 50 per request, instead of one request for each gap between lines already translated. Large common events could become hundreds of requests of a few lines each, every one paying for the full instructions: one game's CommonEvents went from 415 requests to 142, with 57% fewer input tokens.
