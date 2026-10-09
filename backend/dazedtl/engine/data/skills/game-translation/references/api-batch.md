# API Batch within one run

DazedTL's API Settings own provider/model/credentials, and Batches owns supported persisted jobs.
The same starting prompt covers preparation, cost review, submission, collection, QA and local delivery.
The assistant handles each transition; the user does not choose tasks or copy a second prompt.
Every engine follows the same route: `organize` compiles requests from the extractor's units, and the injector reads the results by unit ID.

## Before paid translation

1. Read the saved API settings and inspect existing translation records and persisted jobs.
   Reuse accepted work and resume known jobs instead of submitting duplicates.
   Build the remaining request set with its full scope accounted for; do not rebill completed work.
2. Inspect, extract and build shared guidance locally; these steps submit no translation requests.
   Save the source units and run the helper's `organize --complete` as `direct-workflow.md` describes.
   It compiles the complete request set and quotes only the work no saved result covers yet.
   If the user explicitly requested preparation only, stop at that requested boundary.
3. Inspect the run and its quote with `run --run ID`.
   Show the model/provider, source units, requests, estimated tokens and cost in the conversation.
   Missing pricing is not a $0 estimate; resolve missing settings or unsupported routes and request only the missing choice or access.
4. Use existing spending authorization only if it covers this exact run, provider/model and cost; otherwise request approval here once the estimate is ready.
   The user can also approve it on DazedTL's Progress tab, which starts the run.
   Start an approved run with `start --run ID --approve TOKEN`; changed inputs need a new organize and estimate.
5. Continue automatically through collection, accepted-result validation, injection, targeted QA and packaging.
   A cost approval is a decision within the run, not a request for a new translation prompt.
   Unsupported Batch routes must not silently fall back to full-price Live translation.

The quote uses the same token/pricing helpers as the application, with a 2.5× source-token output allowance and no assumed cache savings.
It is a planning estimate, not a guaranteed bill or a spending cap.
Inspect the displayed rates: the application's pricing table may use configured or built-in fallbacks.
Output shape, provider tokenization, retries and billed reasoning can change the actual cost.
Image work, coding-assistant work, QA and provider queue time are excluded and must remain separately scoped.
The initial quote does not authorize an unlimited retry loop or changes in model, scope or output contract.

The estimate is invalidated by changed source inputs, compiled requests, shared guidance, references, compiler/templates, scope or API settings.
Revalidate before reusing a saved authorized quote; do not ask again solely because the session resumed when the user's authorization and all dependencies still match.
Old project.json GUI approvals are not imported as authorization for a new request set.
Keys and raw private endpoint configuration never belong in the handoff or request plan.
Pricing lookup can consult the application's public pricing catalog; it does not submit translation requests.

## Execution and progress

Reuse the app's supported Batch submission, persisted IDs, reconciliation, collection and Batches UI instead of creating an unrelated provider queue.
The actual engine adapter must consume every compiled context field and retain request/source fingerprints with results.
Historical `llm-pipeline.md` examples need adaptation to this contract and current live application code.
A transport success is not an accepted translation: validate and save the returned units before counting them.
Record submitted/completed/failed request counts and provider wait status separately from translated/reviewed source-unit counts.
Provider request counters can remain unchanged while work is running; they do not establish completion percentage or a delivery ETA.
Before provider waits, save progress and job IDs and explain the next checkpoint.
Wait with the helper's `run --wait` instead of frequent polling, and continue independent work while the provider works.
Reconcile usage after collection and estimate remaining retries before additional paid work; keep within the user's authorization.
