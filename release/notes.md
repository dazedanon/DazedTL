<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a Gemini Batch, or the Batch that asks its refused lines again, that could not be sent because google-genai was missing no longer leaves the run waiting to be reconciled, such as at "Reconcile the clarification Batch submission."; nothing was sent, so it is sent once google-genai is installed.
