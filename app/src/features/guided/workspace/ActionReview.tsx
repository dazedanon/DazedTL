import type { Phase } from "../../../api/contracts";
import { textLocation } from "../textLocation";
import { ActionBar } from "../../../ui/ActionBar";
import { Button } from "../../../ui/Button";
import { Message } from "../../../ui/Feedback";
import { DialogBody, DialogHeader } from "../../../ui/Dialog";
import { Modal } from "../../../ui/Modal";
import { VirtualList } from "../../../ui/VirtualList";
import { ReleaseReview } from "../Release";
import { TranslationCost } from "../TranslationReview";
import { actionKey, fileCount, pathKey, phaseLabels } from "./model";
import type { GuidedWorkspace } from "./useGuidedWorkspace";

/** Reviews a prepared action before it runs or spends money. */
export function ActionReview({ w }: { w: GuidedWorkspace }) {
  const {
    state,
    action,
    values,
    setPanel,
    preview,
    setPreview,
    previewRequest,
    inspectRelease,
    sourceBackup,
    enabledCodes,
    currentEstimate,
    disabled,
    execute,
    refreshPreview,
    previewUsed,
    cancelPreview,
    translateSelected,
  } = w;
  if (!preview) return null;
  const paid =
    preview?.action === "start" && preview.options.mode !== "estimate";
  const reviewEstimateCurrent =
    !paid ||
    preview?.options.mode === "speakers" ||
    (!!preview?.estimate &&
      currentEstimate(preview.options.phase as Phase)?.id ===
        preview.estimate.jobId);
  return (
    <Modal
      label={
        preview.action === "git_setup"
          ? "Review version baseline"
          : preview.action === "release_patch"
            ? inspectRelease
              ? "Archive contents"
              : "Review patch ZIP"
            : preview.action === "release"
              ? inspectRelease
                ? "Archive contents"
                : "Replace game ZIP"
              : "Review translation action"
      }
      size="md"
      className={`guided-sheet${paid ? " translation-review" : ""}${preview.action === "git_setup" ? " guided-baseline-review" : ["release", "release_patch"].includes(preview.action) ? " guided-release-review" : ""}`}
      dismissible={!action.busy}
      onDismiss={cancelPreview}
    >
      <DialogHeader
        title={
          ["release", "release_patch"].includes(preview.action)
            ? inspectRelease
              ? "Archive contents"
              : preview.action === "release_patch"
                ? "Review patch ZIP"
                : "Replace game ZIP"
            : preview.label
        }
        onClose={inspectRelease ? cancelPreview : undefined}
        closeDisabled={action.busy}
      />
      <DialogBody>
        {["release", "release_patch"].includes(preview.action) && (
          <ReleaseReview
            preview={preview}
            inspectOnly={inspectRelease}
            busy={action.busy}
            editAssets={() => {
              setPreview(null);
              setPanel("release-assets");
            }}
          />
        )}
        {preview.action === "git_setup" ? (
          <>
            <p>
              Check the version, original source and runtime files before
              saving.
            </p>
            <dl className="guided-baseline-summary">
              <div>
                <dt>Game version</dt>
                <dd>{String(preview.options.version)}</dd>
              </div>
              <div>
                <dt>Original source</dt>
                <dd>
                  {preview.options.untranslated
                    ? `This untranslated game, after preparation: ${preview.destination}`
                    : String(preview.options.original)}
                </dd>
              </div>
            </dl>
          </>
        ) : (
          !["release", "release_patch", "refresh_sources"].includes(
            preview.action,
          ) && <p className="path">{preview.destination}</p>
        )}
        {preview.action === "start" && (
          <>
            <p>Phase: {phaseLabels[preview.options.phase as Phase]}</p>
            {paid &&
              preview.paths.some((name) =>
                state.readiness.outputs.includes(name),
              ) && (
                <p>
                  Existing working outputs for this scope will be replaced as
                  results are saved. Earlier run copies remain in History; game
                  files change only after Apply.
                </p>
              )}
          </>
        )}
        {!["release", "release_patch"].includes(preview.action) &&
          !!preview.paths.length && (
            <>
              <p>
                {fileCount(preview.files || preview.paths.length)}{" "}
                {preview.action === "git_setup"
                  ? "in this baseline"
                  : "in this action"}
              </p>
              {preview.paths.length <= 8 ? (
                <ul
                  className="guided-preview-paths"
                  aria-label="Files in this action"
                >
                  {preview.paths.map((name) => (
                    <li key={name} className="guided-preview-path">
                      {name}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="guided-preview-files">
                  <VirtualList
                    items={preview.paths}
                    itemKey={pathKey}
                    label="Files in this action"
                    empty={null}
                  >
                    {(name) => (
                      <div className="guided-preview-path">{name}</div>
                    )}
                  </VirtualList>
                </div>
              )}
            </>
          )}
        {preview.action === "export_selected" && !!preview.options.run_id && (
          <p>
            Uses the saved files from this run. Reapplying makes no API
            requests.
          </p>
        )}
        {!!preview.additions?.length && (
          <p>
            {preview.additions.length} files are additions to the original
            baseline.
          </p>
        )}
        {preview.action === "backup_source" &&
          sourceBackup?.available === false && (
            <p>
              This saves current files. It cannot recover the missing original.
            </p>
          )}
        {preview.action === "refresh_sources" && (
          <p>
            Replace the selected working files with their current game-folder
            versions? Their translation progress will be replaced. Previous
            copies and run history are kept. Your game files won’t change.
          </p>
        )}
        {preview.action === "export_selected" && (
          <p>
            Fully overwrite these game files with the selected saved
            translations. Existing game edits will be replaced. Working copies
            and saved runs are retained.
          </p>
        )}
        {preview.action === "runtime_restore" && (
          <p>
            Return these files to the preserved bytes from before the chosen
            batch. Review the current and restored text below before continuing.
          </p>
        )}
        {preview.publication && preview.action !== "export_selected" && (
          <>
            <p>
              The whole batch is checked before publication. Exact before/after
              backups are retained; failure attempts rollback. Restore requires
              another review and rejects newer conflicting edits.
            </p>
            {preview.publication.map((row) => (
              <details className="text-publication" key={row.path}>
                <summary>
                  {row.path} · {row.size.toLocaleString()} bytes
                  {row.later_edits ? " · Replaces later game edits" : ""}
                </summary>
                <p className="path">{row.destination}</p>
                <small>
                  Current SHA-256 {row.before}
                  <br />
                  Candidate SHA-256 {row.after}
                </small>
                <strong>
                  Runtime changes
                  {row.truncated ? " (diff exceeds 16,000 characters)" : ""}
                </strong>
                <pre>
                  {row.diff || "Runtime bytes already match this candidate."}
                </pre>
                <details>
                  <summary>JSON context</summary>
                  <strong>
                    Current runtime JSON (first 16,000 characters)
                  </strong>
                  <pre>{row.before_text}</pre>
                  <strong>
                    Reviewed replacement JSON (first 16,000 characters)
                  </strong>
                  <pre>{row.after_text}</pre>
                </details>
              </details>
            ))}
          </>
        )}
        {paid && preview.estimate && (
          <section
            aria-label={
              reviewEstimateCurrent ? "Matching estimate" : "Previous estimate"
            }
          >
            <h3>
              {reviewEstimateCurrent
                ? "Matching estimate"
                : "Previous estimate"}
            </h3>
            <TranslationCost
              value={preview.estimate.value}
              mode={String(preview.options.mode)}
            />
            <p className="muted">
              {reviewEstimateCurrent
                ? "Selection, source, pricing, guidance, and layout match this estimate."
                : "This quote was calculated before the reviewed inputs changed."}
            </p>
          </section>
        )}
        {paid && !reviewEstimateCurrent && (
          <div role="alert">
            <p>Estimate needs refreshing. Reviewed inputs changed.</p>
            <Button
              disabled={disabled}
              onClick={() => {
                setPreview(null);
                translateSelected();
              }}
            >
              Refresh estimate
            </Button>
          </div>
        )}
        {paid && (
          <p>
            {preview.run?.connection || state.provider.connection} ·{" "}
            {preview.run?.model || state.provider.model} ·{" "}
            {preview.options.mode === "batch"
              ? "Prepare this scope for a separate Batch cost approval. Speaker translation can request its own approval."
              : "API requests may incur charges using this run’s frozen settings."}
          </p>
        )}
        {paid && preview.options.phase === "advanced" && (
          <>
            <p>Selected sources: {enabledCodes.join(", ")}</p>
            {values.engine_options.CODE122 === true && (
              <p>
                Variable IDs: {String(values.engine_options.CODE122_VAR_RANGES)}
              </p>
            )}
            {values.engine_options.CODE357 === true && (
              <p>
                Plugin handlers:{" "}
                {(
                  (values.engine_options.ENABLED_PLUGINS_357 as string[]) || []
                ).join(", ") || "None"}
              </p>
            )}
            {values.engine_options.CODE355655 === true && (
              <p>
                Script patterns:{" "}
                {(
                  (values.engine_options.ENABLED_PATTERNS_355655 as string[]) ||
                  []
                ).join(", ") || "None"}
              </p>
            )}
          </>
        )}
        {paid && preview.options.phase === "advanced" && (
          <>
            <p>
              {state.eventText.manual.length
                ? "Manual overrides: " +
                  state.eventText.manual.join(", ") +
                  ". Reason: " +
                  state.eventText.manualReason
                : "Source choices match reviewed investigation recommendations."}
            </p>
            {state.eventText.rows
              .filter((row) => values.engine_options[row.key])
              .map((row) => (
                <details key={row.key}>
                  <summary>{row.label} · Actual coverage</summary>
                  <p>{row.coverage}</p>
                  {!!row.builtins.length && (
                    <p>Built-ins also enabled: {row.builtins.join(", ")}</p>
                  )}
                </details>
              ))}
          </>
        )}
        {paid &&
          preview.options.phase === "advanced" &&
          values.engine_options.AUTONAMEPOPUP101 === true && (
            <p>
              Saved AutoNamePopup handling also processes supported actor-name
              changes independently of source 320.
            </p>
          )}
        {paid && preview.options.phase === "variables" && (
          <p>
            Reviewed literal-based updates apply to all matching quoted literals
            in the selected code-111 expressions. Unmatched literals remain
            unchanged.
          </p>
        )}
        {preview.rewrap && (
          <>
            <p>
              {preview.rewrap.changes_found} fitting changes ·{" "}
              {preview.rewrap.overflow_skipped} protected overflows skipped
            </p>
            {preview.rewrap.previews.map((row, index) => (
              <details key={index}>
                <summary>
                  {row.file_name} · {textLocation(row.locator)}
                </summary>
                <strong>Before</strong>
                <pre>{row.before}</pre>
                <strong>After</strong>
                <pre>{row.after}</pre>
              </details>
            ))}
          </>
        )}
      </DialogBody>
      <ActionBar feedback={<Message message={action.error} />}>
        {!inspectRelease && (
          <Button disabled={action.busy} onClick={cancelPreview}>
            {preview.action === "git_setup" ? "Back" : "Cancel"}
          </Button>
        )}
        {!inspectRelease && (
          <Button
            variant="primary"
            disabled={
              !reviewEstimateCurrent || (previewUsed && !previewRequest)
            }
            pending={action.busy}
            onClick={() =>
              previewUsed
                ? refreshPreview()
                : action.run(
                    () => execute(preview),
                    "",
                    actionKey(preview.action, preview.options),
                  )
            }
          >
            {previewUsed && (!action.busy || action.key === "review:refresh")
              ? "Refresh preview"
              : preview.publication
                ? preview.action === "runtime_restore"
                  ? "Restore reviewed files"
                  : "Apply reviewed files"
                : preview.action === "git_setup"
                  ? "Save baseline & continue"
                  : paid && preview.options.mode === "translate"
                    ? "Approve and start Live API"
                    : paid && preview.options.mode === "batch"
                      ? "Prepare Batch for cost review"
                      : preview.action === "refresh_sources"
                        ? "Reload files"
                        : ["release", "release_patch"].includes(preview.action)
                          ? `${preview.overwrite ? "Replace & build" : "Build"} ${preview.action === "release_patch" ? "patch" : "game"} ZIP`
                          : preview.label || "Run this action"}
          </Button>
        )}
      </ActionBar>
    </Modal>
  );
}
