<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** a Guided Live run now stops with one message when the provider rejects 3 requests in a row with the same error, such as a model it doesn't have or a key it doesn't accept, or refuses the run's thinking effort once, instead of sending each rejected request five times and going on through every file. A single rejected request among translated ones still lets the rest of the run translate, and it isn't sent again. Rejected requests aren't billed. Runs started before this update keep working as before.

### Fixed

- **Translate:** a Guided Batch estimate and the whole-game estimate for GPT-5.6 or a later OpenAI model now include the prompt-cache writes OpenAI bills when the requests share no cached instructions, instead of showing a lower price without them, and the highest Batch price of a GPT-5.6 Pro or later Pro model no longer counts cache writes its Batch doesn't make. Estimates still waiting are priced again on their next view, or ask to be estimated again; approved and running work keeps its price.
- **Translate:** when the provider rejects a request in a Guided Live run, the failed run's message now names the provider's own error, such as "Classes.json: The provider rejected the request: HTTP 400 - ...", instead of "API call failed: Error code: 400 - {'error': ...}. Fallback also failed: ...".
- **Translate:** after a failed run, a Database files or Maps & events file whose requests the provider rejected now says so in its status tooltip, instead of reading exactly like a file the run never sent; both still read Not started, since **Translate** sends them again.
- **Translate:** Inspect run's **Technical** view no longer counts files with nothing to translate as applied, as in "2 saved · 2 applied" after a run that applied nothing, and its **Run log** no longer repeats each failed request's error three times, its shortened end starting at a line instead of mid-word.
- **Settings:** **Advanced model options** in **Translation defaults** now stays open when you switch to **API connections**, such as to check the connection again for its thinking effort levels, and come back.
- **Settings:** when a run stops because a Custom / local server refused a thinking effort that **Check an effort** had accepted, the check now reads refused and Settings stops offering that level until you check it again, instead of still reading "Accepted".
