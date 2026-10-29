<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a file that fails after some of its requests were answered, such as on a later request's error or a missing Batch result, now keeps what those requests cost in its cost and the run's total, which left them out.
