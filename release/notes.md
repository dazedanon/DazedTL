<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** after you decline or close a cost review, clicking **Translate** again reuses that estimate while the files and settings are unchanged, instead of estimating every file again. Its window marks Estimate cost as Reused.
- **Context:** **Estimate again** in Cost estimate waits until something the estimate depends on changes, since it would give the same result. Updating DazedTL now also marks a saved estimate Outdated.

### Fixed

- **Translate:** Preview request in a Batch review pages through every request the Batch will submit. When names and labels were translated with Live first, it showed only those name requests, such as "Request 1 of 1", and none of the Batch's own.
