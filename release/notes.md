<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Context:** **Save context** and **Copy starting prompt** still froze the app for minutes on a big game where an earlier save had been interrupted, for example by closing DazedTL while it saved; they now finish at once.
- **Context:** a failed **Save context** or other file write now names the file and why (for example that it is read-only), and a leftover Git lock says another Git process is using the game instead of "The operation could not finish."
