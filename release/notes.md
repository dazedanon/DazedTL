<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a Batch that cannot be sent, such as a Gemini Batch, or the Batch that asks its refused lines again, when google-genai is missing, now fails the run with what to fix instead of "check_submit failed (RuntimeError)", and no longer leaves the run waiting to be reconciled, such as at "Reconcile the clarification Batch submission."; nothing was sent, so it is sent once the cause is fixed.
