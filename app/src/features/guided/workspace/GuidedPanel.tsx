import { PathInput } from "../../../ui/PathInput";
import { api } from "../../../api/client";
import { flushDrafts } from "../../../state/leaveGuards";
import { ActionBar } from "../../../ui/ActionBar";
import { ActionControl } from "../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../ui/ActionList";
import { Button } from "../../../ui/Button";
import { Feedback, Message } from "../../../ui/Feedback";
import { useOwnedFeedback } from "../../../ui/FeedbackOwners";
import { CheckField, FieldRow } from "../../../ui/FieldRow";
import { JobStatus } from "../../../ui/JobStatus";
import { DialogBody, DialogHeader } from "../../../ui/Dialog";
import { Modal } from "../../../ui/Modal";
import { Tabs } from "../../../ui/Tabs";
import { SpeakerNames } from "../ContextWorkspace";
import { EngineOptions } from "../EngineOptions";
import { FileSelection } from "../FileSelection";
import { SpeakerFindings } from "../SpeakerFindings";
import { TranslationOptions } from "../TranslationOptions";
import { retainOtherScope } from "../selection";
import { commentTextHelp, speakerOptions } from "../speakerOptions";
import { fileCount, panelTitles, phaseLabels, speakers } from "./model";
import type { GuidedWorkspace } from "./useGuidedWorkspace";

// Sheets with file lists or tables get the large size; the rest stay compact.
const wideSheets = new Set<string>(["files", "speaker-names"]);

/** The open tool sheet: file choice, options and task tools. */
export function GuidedPanel({ w }: { w: GuidedWorkspace }) {
  const {
    project,
    state,
    action,
    speakerAction,
    draft,
    values,
    panel,
    setPanel,
    speakerTab,
    setSpeakerTab,
    fileScope,
    running,
    preserved,
    baseline,
    findings,
    scan,
    scanOptionsDirty,
    eventFiles,
    pickerFiles,
    pickerSelected,
    phase,
    release,
    edit,
    editRelease,
    save,
    disabled,
    feedback,
    operationJob,
    task,
    workingFileActions,
    copyTask,
    closePanel,
    widths,
    formatActions,
    applySpeakerControl,
    review,
  } = w;
  const owned = useOwnedFeedback(action.key);
  if (!panel) return null;
  const findingsReady = ["ready", "applied"].includes(findings.status);
  // The editor search reports [name, path] pairs.
  const editorResult = operationJob("editors")?.result?.editors;
  const foundEditors = Array.isArray(editorResult)
    ? editorResult.filter(
        (item): item is [string, string] =>
          Array.isArray(item) &&
          typeof item[0] === "string" &&
          typeof item[1] === "string",
      )
    : undefined;
  // Name translation is optional paid work; its review shows files and cost.
  const nameTranslationBlocked: string | boolean = !scan.names.length
    ? findingsReady
      ? "No names to translate yet."
      : true
    : !baseline
      ? "Save the version baseline first."
      : !eventFiles.length
        ? "Choose event files to translate first."
        : !state.provider.ready
          ? "Choose a connection and model in Settings first."
          : !state.provider.enabled
            ? "Provider execution is off for this launch."
            : "";
  // Panels that edit the options draft say whether it is saved.
  const draftPanel =
    ["widths", "translation-context"].includes(panel) ||
    (panel === "speakers" && speakerTab === "settings");
  const title =
    panel === "translation-context"
      ? `${phaseLabels[phase]} options`
      : panelTitles[panel];
  const savePanel = (label = "Save & close") => (
    <ActionControl
      label={label}
      variant="primary"
      disabled={disabled || (panel === "speakers" && !draft.dirty)}
      {...feedback("save-options", "Saving…")}
      onClick={() =>
        action.run(
          async () => {
            await save();
            setPanel(null);
          },
          "Options saved.",
          "save-options",
        )
      }
    />
  );
  const panelActions =
    panel === "files" ? (
      <>
        <Button disabled={action.busy} onClick={closePanel}>
          Cancel
        </Button>
        <ActionControl
          label={`Use ${fileCount(pickerSelected.length)}`}
          variant="primary"
          disabled={disabled}
          {...feedback("files:save", "Saving selection…")}
          onClick={() =>
            action.run(
              async () => {
                await save();
                setPanel(null);
              },
              "File selection saved.",
              "files:save",
            )
          }
        />
      </>
    ) : (
      <>
        {panel === "speaker-names" && (
          <>
            <ActionControl
              label="Translate names with API…"
              disabled={disabled || !!nameTranslationBlocked}
              disabledReason={
                typeof nameTranslationBlocked === "string"
                  ? nameTranslationBlocked
                  : ""
              }
              onClick={() => {
                // The paid review replaces this dialog rather than stacking on it.
                setPanel(null);
                void review("start", { mode: "speakers" });
              }}
            />
            <ActionControl
              label={scan.available ? "Scan again" : "Run local scan"}
              disabled={disabled || running || !findingsReady}
              disabledReason={findingsReady ? "" : findings.message}
              {...feedback("speaker-scan", "Starting local scan…")}
              pending={
                (action.busy && action.key === "speaker-scan") ||
                (!!scan.job && ["ready", "running"].includes(scan.job.status))
              }
              notice={
                scan.job?.status === "complete" && scan.available
                  ? `${scan.names.length} names saved.`
                  : ""
              }
              job={
                scan.job &&
                ["failed", "interrupted", "stopped", "canceled"].includes(
                  scan.job.status,
                )
                  ? scan.job
                  : undefined
              }
              onClick={async () => {
                const result = await action.run(
                  async () => {
                    await save();
                    return api.translation.speakers(project.id, true);
                  },
                  "",
                  "speaker-scan",
                );
                if (
                  result.ok &&
                  result.value.available &&
                  result.value.job?.status === "complete"
                )
                  action.succeed("Names saved.", "speaker-scan");
              }}
            />
          </>
        )}
        {["speakers", "widths", "tools", "translation-context"].includes(
          panel,
        ) &&
          (panel !== "speakers" || speakerTab === "settings") && (
            <>
              {draft.dirty && (
                <ActionControl
                  label="Discard engine options"
                  disabled={disabled}
                  {...feedback("discard-options", "Discarding…")}
                  onClick={() =>
                    action.run(
                      draft.discard,
                      "Engine options restored.",
                      "discard-options",
                    )
                  }
                />
              )}
              {savePanel()}
            </>
          )}
      </>
    );
  return (
    <Modal
      label={title}
      size={wideSheets.has(panel) ? "lg" : "md"}
      className={`guided-sheet${panel === "translation-context" ? " translation-options" : ["speakers", "speaker-names"].includes(panel) ? " context-sheet" : ""}`}
      dismissible={!action.busy}
      onDismiss={closePanel}
    >
      <DialogHeader
        title={title}
        description={
          panel === "files"
            ? "Selections stay checked when you filter, switch phases or return later."
            : undefined
        }
        onClose={closePanel}
        closeDisabled={action.busy}
      />
      {panel === "files" ? (
        <FileSelection
          state={{ ...state, files: pickerFiles }}
          selected={pickerSelected}
          change={(names) =>
            edit(
              "selected",
              fileScope
                ? retainOtherScope(values.selected, pickerFiles, names)
                : names,
            )
          }
          disabled={disabled}
        />
      ) : (
        <DialogBody>
          {panel === "speakers" && (
            <>
              <div className="context-detection-tabs">
                <Tabs
                  id="detection"
                  label="Speaker detection views"
                  value={speakerTab}
                  onChange={setSpeakerTab}
                  disabled={disabled}
                  items={[
                    { id: "findings", label: "Saved findings" },
                    { id: "settings", label: "Settings" },
                  ]}
                />
              </div>
              <div
                role="tabpanel"
                id={`detection-panel-${speakerTab}`}
                aria-labelledby={`detection-tab-${speakerTab}`}
              >
                {speakerTab === "findings" ? (
                  <>
                    {findings.reportId ? (
                      <SpeakerFindings
                        findings={findings}
                        values={values.engine_options}
                      />
                    ) : (
                      <p className="muted">{findings.message}</p>
                    )}
                    {findings.status === "stale" && (
                      <p className="muted">{findings.message}</p>
                    )}
                    {applySpeakerControl}
                  </>
                ) : (
                  <>
                    <div className="context-detection-settings">
                      <CheckField
                        id="guided-comment-text"
                        label="Comment text"
                        help={commentTextHelp}
                        disabled={disabled}
                        checked={values.phase1_comments}
                        onChange={(checked) => edit("phase1_comments", checked)}
                      />
                      <EngineOptions
                        state={state}
                        values={values.engine_options}
                        keys={speakers}
                        descriptions={speakerOptions}
                        disabled={disabled}
                        change={(key, value) =>
                          edit("engine_options", {
                            ...values.engine_options,
                            [key]: value,
                          })
                        }
                      />
                    </div>
                    {!!findings.overrides.length && (
                      <ActionControl
                        label="Use investigation recommendations"
                        disabled={
                          disabled ||
                          draft.dirty ||
                          !!state.optionsDraft ||
                          !["ready", "applied"].includes(findings.status)
                        }
                        pending={speakerAction.busy}
                        pendingText="Applying rules…"
                        error={speakerAction.error}
                        notice={speakerAction.notice}
                        onClick={() =>
                          speakerAction.run(
                            () => draft.applySpeakers(true),
                            "Investigation recommendations restored.",
                            "apply",
                          )
                        }
                      />
                    )}
                  </>
                )}
              </div>
            </>
          )}
          {panel === "speaker-names" && (
            <>
              <SpeakerNames scan={scan} />
              {scan.available && (!scan.current || scanOptionsDirty) && (
                <p className="muted">
                  Showing the saved scan. Scan again to collect names with the
                  current files and settings.
                </p>
              )}
              {scan.job && ["ready", "running"].includes(scan.job.status) && (
                <JobStatus
                  compact
                  job={{ ...scan.job, label: "Local speaker scan" }}
                />
              )}
            </>
          )}
          {panel === "widths" && (
            <>
              {widths}
              <ActionList>
                <ActionRow
                  title="Measure from the game"
                  description="Your assistant measures the message windows and saves verified limits here."
                >
                  {copyTask("wrap", "Copy width-measurement task")}
                </ActionRow>
              </ActionList>
            </>
          )}
          {panel === "preparation" && (
            <ActionList>
              {formatActions.map((item) => (
                <ActionRow
                  key={item.id}
                  title={item.title}
                  description={item.hint}
                >
                  {task(
                    item.id,
                    item.id === "gameupdate"
                      ? "Recreate GameUpdate files"
                      : "Rerun " + item.title.toLowerCase(),
                    {},
                    !preserved,
                  )}
                </ActionRow>
              ))}
            </ActionList>
          )}
          {panel === "tools" && (
            <>
              <p className="muted">
                Settings are saved with this project. Install/update a plugin or
                apply settings to use them in the game.
              </p>
              <fieldset disabled={disabled}>
                {(
                  [
                    ["hotkey", "TL Inspector hotkey"],
                    ["forgeHotkey", "Forge hotkey"],
                  ] as const
                ).map(([key, label]) => (
                  <FieldRow key={key} id={`guided-tool-${key}`} label={label}>
                    {(props) => (
                      <input
                        {...props}
                        className="short-control"
                        value={release.tools[key]}
                        onChange={(event) =>
                          editRelease("tools", {
                            ...release.tools,
                            [key]: event.target.value,
                          })
                        }
                      />
                    )}
                  </FieldRow>
                ))}
                <FieldRow id="guided-tool-scale" label="Overlay scale">
                  {(props) => (
                    <select
                      {...props}
                      value={release.tools.uiScale}
                      onChange={(event) =>
                        editRelease("tools", {
                          ...release.tools,
                          uiScale: event.target.value,
                        })
                      }
                    >
                      {[
                        "auto",
                        "1",
                        "1.25",
                        "1.5",
                        "1.75",
                        "2",
                        "2.25",
                        "2.5",
                      ].map((value) => (
                        <option key={value} value={value}>
                          {value === "auto"
                            ? "Automatic"
                            : Number(value) * 100 + "%"}
                        </option>
                      ))}
                    </select>
                  )}
                </FieldRow>
                <FieldRow
                  id="guided-tool-editor"
                  label="Source editor"
                  help="Use auto for detection, or choose the editor executable."
                >
                  {(props) => (
                    <div className="guided-folder-field">
                      <PathInput
                        {...props}
                        value={release.tools.editorCmd}
                        onChange={(event) =>
                          editRelease("tools", {
                            ...release.tools,
                            editorCmd: event.target.value,
                          })
                        }
                      />
                      <Button
                        onClick={() =>
                          action.run(
                            async () => {
                              const path = await window.dazedtl.chooseEditor();
                              if (path)
                                editRelease("tools", {
                                  ...release.tools,
                                  editorCmd: path,
                                });
                            },
                            "",
                            "choose-editor",
                          )
                        }
                      >
                        Choose editor
                      </Button>
                    </div>
                  )}
                </FieldRow>
              </fieldset>
              <ActionList>
                <ActionRow
                  title="Installed editors"
                  description={
                    foundEditors
                      ? `${foundEditors.length} found on this computer.`
                      : "Find code editors installed on this computer."
                  }
                >
                  {task("editors", "Find installed editors")}
                </ActionRow>
                {foundEditors?.map(([name, path]) => (
                  <ActionRow key={path} title={name} description={path}>
                    <Button
                      disabled={disabled || release.tools.editorCmd === path}
                      onClick={() =>
                        editRelease("tools", {
                          ...release.tools,
                          editorCmd: path,
                        })
                      }
                    >
                      {release.tools.editorCmd === path ? "In use" : "Use"}
                    </Button>
                  </ActionRow>
                ))}
                <ActionRow
                  title="Installed plugins"
                  description="Write these settings into the installed TL Inspector and Forge."
                >
                  {task(
                    "playtest_apply",
                    "Apply settings to game",
                    {},
                    !baseline ||
                      (!state.tools?.inspector.installed &&
                        !state.tools?.forge.installed),
                  )}
                </ActionRow>
              </ActionList>
            </>
          )}
          {panel === "release-assets" && (
            <>
              <p>
                Applied images and tracked runtime assets are already included.
                Add other player images or fonts by exact game-relative path,
                one per line.
              </p>
              <label>
                Image and font paths
                <textarea
                  rows={7}
                  value={release.assets.join("\n")}
                  disabled={disabled}
                  onChange={(event) =>
                    editRelease("assets", event.target.value.split("\n"))
                  }
                />
              </label>
              <p className="muted">
                Use img/ or fonts/, including www/ layouts. Private files,
                missing files and symbolic links are rejected. Build reviews the
                exact current bytes.
              </p>
              <ActionControl
                label="Save runtime assets"
                variant="primary"
                disabled={disabled}
                {...feedback("release-assets:save", "Saving…")}
                onClick={() =>
                  action.run(
                    async () => {
                      const names = release.assets
                        .map((name) => name.trim())
                        .filter(Boolean);
                      editRelease("assets", [...new Set(names)]);
                      await flushDrafts();
                      await save();
                      setPanel(null);
                    },
                    "Runtime assets retained.",
                    "release-assets:save",
                  )
                }
              />
            </>
          )}

          {panel === "translation-context" && (
            <TranslationOptions
              state={state}
              phase={phase}
              values={values}
              disabled={disabled || running}
              change={edit}
              fileActions={workingFileActions()}
            />
          )}
        </DialogBody>
      )}
      <ActionBar
        feedback={
          action.error && !owned ? (
            <Message message={action.error} />
          ) : (
            draftPanel && <Feedback dirty={draft.dirty} />
          )
        }
      >
        {panelActions}
      </ActionBar>
    </Modal>
  );
}
