<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** when a Guided Live run stops on rejected requests or a refused thinking effort, what the stopped file's requests cost before the stop now still counts in its cost and the run's total.
- **Translate:** a WOLF RPG Editor map that fails on its first event page now shows its own error, such as the provider's refusal or the run's stop, instead of "cannot access local variable 'tt'".
- **Assistant-led:** Live runs on OpenRouter, and on DeepSeek or Kimi with Thinking effort set to None, no longer fail every request with "unexpected keyword argument".
