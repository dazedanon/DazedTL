<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a Custom connection with the Gemini-compatible protocol, such as a proxy, no longer sends its key straight to Google past the proxy: a Gemini Batch on it is refused before anything is sent, asking for Live or a Google Gemini connection, since Gemini Batches move their files through Google's own API, and its other requests go to its own address.
- **Translate:** an OpenRouter cost estimate, or an Assistant-led quote waiting for approval, with Live rates set by hand now also keeps its OpenRouter Batch price while the connection's check has failed, where it was priced again as Live-only with Batch at half its Live price, and a Batch estimate no longer disappears then; approving such a quote, starting Translate from such an estimate or estimating it again asks for the connection to be checked instead of saying its settings or inputs changed or pricing it as Live-only.
