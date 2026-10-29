<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a Custom connection with the Gemini-compatible protocol, such as a proxy, no longer sends its key straight to Google past the proxy: a Gemini Batch on it is refused before anything is sent, asking for Live or a Google Gemini connection, since Gemini Batches move their files through Google's own API, and its other requests go to its own address.
