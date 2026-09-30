# Migration record

## Preserved source

The sibling `DazedMTLTool` repository remains the reference and fallback application.
Its existing working-tree changes were captured before creating this project.
The checkpoint contains a binary Git diff, copies of changed and untracked source/build files, and a file-hash manifest.
The checkpoint is retained under this repository's `.git/migration-reference/` directory.

The reference commit and checkpoint inventory are recorded in `migration-reference.json`.
The checkpoint does not contain credentials, user games, translation workspaces, or dependency caches.

## First migrated slice

- Clean Electron shell and approved Overview layout.
- Persistent project identity independent of translation method and navigation.
- A temporary, explicit connection to the existing Python implementation.
- Guided RPG Maker MV/MZ file import and the database/dialogue translation phases.
- Existing context documents, provider settings, estimates, live/batch execution, approvals, stop/resume, and guarded output handling.

This slice was built without running tests, as requested.
No provider translation was executed as part of creating it.
The code paths are connected to the real engine, but successful live translation is not claimed without an actual run.

## Next migrations

1. Review the new guided page and complete the remaining RPG Maker phases and preparation/export tooling.
2. Extract the RPG Maker engine and its required context/provider dependencies from the compatibility boundary.
3. Bring WOLF and Ace across through their existing engine-specific paths.
4. Integrate Len's Method with its existing skills and shared project services.
5. Add less-used manual engines where needed.
6. Revisit testing, packaging, updates, and distribution after the UX and boundaries settle.

Do not copy the previous UI, temporary workspaces, or retired compatibility screens wholesale.
Do not change engine translation rules as a side effect of moving files.
