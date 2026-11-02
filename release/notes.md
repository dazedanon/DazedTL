<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Maps & events:** an LL_GalgeChoiceWindowMV choice translated with a comma, such as "Sure, sure", no longer becomes two choices in the game and moves the choices after it onto the wrong branches, and the plugin command keeps its other text as it was; in a run started after updating, its choices are sent with the question their menu shows.
- **Translate:** a Gemini Batch sent before 2.52.4 on a Custom Gemini-compatible connection, whose replies held refusals, no longer stops at "Reconcile the clarification Batch submission."; its refused lines are asked again at Google, where that Batch was sent, with the same connection's key.
