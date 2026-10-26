<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Context:** **Save context** and **Copy starting prompt** still froze the app for minutes on a big game where an earlier save had been interrupted, for example by closing DazedTL while it saved; they now finish at once.
- **Context:** a failed **Save context** shows its reason beside the button, and it and any other failed file write now name the file and why (for example that it is read-only), and a leftover Git lock says another Git process is using the game instead of "The operation could not finish."
- **Set up:** the first change DazedTL made to a big game whose version history wasn't set up yet froze the app for minutes while it saved the game's original files; it now saves them in the background as soon as you open the game, and a change that has to wait for them says so.
