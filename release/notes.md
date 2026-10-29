<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a server that refuses the run's thinking effort with HTTP 422, or by saying the model takes no reasoning or thinking, now stops a Guided Live run at the first refused request with "refused thinking effort", as **Check an effort** reads such a reply, instead of after three requests with "The provider rejected 3 requests in a row"; a Guided Batch the provider refused for its effort ends with the same message instead of "No successful Batch responses".
- **Settings:** a thinking effort that **Check an effort** accepted now reads refused after a Guided Batch the server refused it in, and after an Assistant-led run that it refused while DazedTL was closed, not only after a Live run.
