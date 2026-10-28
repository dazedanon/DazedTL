<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Estimates:** the whole-game **Cost estimate** and an Assistant-led estimate waiting on **Progress** made before an update that corrects DazedTL's prices now show the corrected price the next time you see them, and approving approves that price, instead of keeping the old price until a setting changed. Claude estimates, which can't be priced again that way, ask you to **Estimate again** once. Runs you already approved keep the price you approved.
- **Settings:** for Anthropic and OpenRouter connections, **Thinking effort** now offers the levels the provider's own model list gives each model when you check the connection, and names OpenRouter's default level, so a model DazedTL's built-in list doesn't know can take an effort too; other providers keep DazedTL's built-in list, and a line under the choice says where its levels come from and how to refresh them. Check a connection again to read them.
