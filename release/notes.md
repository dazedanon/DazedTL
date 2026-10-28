<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** a Guided Live run now stops with one message when the provider rejects 3 requests in a row with the same error, such as a model it doesn't have or a key it doesn't accept, or refuses the run's thinking effort once, instead of sending each rejected request five times and going on through every file. A single rejected request among translated ones still lets the rest of the run translate, and it isn't sent again. Rejected requests aren't billed. Runs started before this update keep working as before.

### Fixed

- **Settings:** **Advanced model options** in **Translation defaults** now stays open when you switch to **API connections**, such as to check the connection again for its thinking effort levels, and come back.
