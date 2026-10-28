<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** a Guided Live run now stops with one message when the provider rejects 3 requests in a row with the same error, such as a model it doesn't have or a key it doesn't accept, or refuses the run's thinking effort once, instead of sending each rejected request five times and going on through every file. A single rejected request among translated ones still lets the rest of the run translate, and it isn't sent again. Rejected requests aren't billed, and what a file's requests cost before the stop still counts in its cost and the run's total. Runs started before this update keep working as before.

### Fixed

- **Translate:** a Guided Batch estimate and the whole-game estimate for GPT-5.6 or a later OpenAI model now include the prompt-cache writes OpenAI bills when the requests share no cached instructions, instead of showing a lower price without them, and the highest Batch price of a GPT-5.6 Pro or later Pro model no longer counts cache writes its Batch doesn't make. Estimates still waiting are priced again on their next view, or ask to be estimated again; approved and running work keeps its price.
- **Settings:** **Advanced model options** in **Translation defaults** now stays open when you switch to **API connections**, such as to check the connection again for its thinking effort levels, and come back.
- **Settings:** when a run stops because a Custom / local server refused a thinking effort that **Check an effort** had accepted, the check now reads refused and Settings stops offering that level until you check it again, instead of still reading "Accepted".
- **Translate:** a Translate estimate, whole-game estimate or Assistant-led estimate on a Claude model waiting for approval no longer reads out of date after an update that corrects only OpenAI Batch prices, such as this one, so you don't need to estimate it again, Claude token count included. Estimates on other models outside OpenAI's own Batch keep their prices too.
