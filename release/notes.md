<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a WOLF RPG Editor map that fails on its first event page now shows its own error, such as the provider's refusal or the run's stop, instead of "cannot access local variable 'tt'".
- **Translate:** when the provider rejects a request in a Guided Live run, the failed run's message now names the provider's own error, such as "Classes.json: The provider rejected the request: HTTP 400 - ...", instead of "API call failed: Error code: 400 - {'error': ...}. Fallback also failed: ...".
- **Translate:** after a failed run, a Database files or Maps & events file whose requests the provider rejected now says so in its status tooltip, instead of reading exactly like a file the run never sent; both still read Not started, since **Translate** sends them again.
- **Translate:** Inspect run's **Technical** view no longer counts files with nothing to translate as applied, as in "2 saved · 2 applied" after a run that applied nothing, and its **Run log** no longer repeats each failed request's error three times, its shortened end starting at a line instead of mid-word.
