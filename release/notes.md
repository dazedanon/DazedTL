<!-- The next release's notes; see docs/development.md#release-notes. -->

### Added

- **Settings:** a **Custom / local** connection, and a model of another provider that DazedTL doesn't know, can now take a **Thinking effort**: **Check an effort** sends the server one short request at that level, free on a local server and a fraction of a cent elsewhere, and runs can send a level once the server accepts it. A refused level shows the server's reason and stays unavailable, and changing the connection's address clears its checks.

### Fixed

- **Estimates:** an Assistant-led estimate, and a Guided estimate priced again after a model switch, for a model whose thinking effort levels came from the provider's model list now name that model's default effort and say that thinking tokens aren't estimated, as Guided's own estimates already did.
