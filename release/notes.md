<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a Custom connection with the Gemini-compatible protocol, such as a proxy, no longer sends its key straight to Google past the proxy: it runs Live only, with no Batch price in its estimates and quotes to approve and a waiting Batch quote on it reading outdated, since Gemini Batches move their files through Google's own API, and its requests go to its own address.
- **Translate:** a Gemini Batch sent on such a connection before this update still finishes, its status, results and cancellation read at Google where it runs instead of failing at the proxy, and a Gemini or Kimi Batch saved without a key's name is read only with the connection it was sent on instead of another one's key.
