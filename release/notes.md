<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** a Guided Live run now stops with one message when the provider rejects 3 requests in a row with the same error, such as a model it doesn't have or a key it doesn't accept, or refuses the run's thinking effort once, instead of sending each rejected request five times and going on through every file. A single rejected request among translated ones still lets the rest of the run translate, and it isn't sent again. Rejected requests aren't billed, and what a file's requests cost before the stop still counts in its cost and the run's total. Runs started before this update keep working as before.

### Fixed

- **Translate:** a WOLF RPG Editor map that fails on its first event page now shows its own error, such as the provider's refusal or the run's stop, instead of "cannot access local variable 'tt'".
- **Assistant-led:** Live runs on OpenRouter, and on DeepSeek or Kimi with Thinking effort set to None, no longer fail every request with "unexpected keyword argument".
- **Translate:** when the provider rejects a request in a Guided Live run, the failed run's message now names the provider's own error, such as "Classes.json: The provider rejected the request: HTTP 400 - ...", instead of "API call failed: Error code: 400 - {'error': ...}. Fallback also failed: ...".
- **Translate:** after a failed run, a Database files or Maps & events file whose requests the provider rejected now says so in its status tooltip, instead of reading exactly like a file the run never sent; both still read Not started, since **Translate** sends them again.
- **Translate:** Inspect run's **Technical** view no longer counts files with nothing to translate as applied, as in "2 saved · 2 applied" after a run that applied nothing, and its **Run log** no longer repeats each failed request's error three times, its shortened end starting at a line instead of mid-word.
