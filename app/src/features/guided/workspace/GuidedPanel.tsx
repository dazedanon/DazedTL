import { api } from "../../../api/client";
import { flushDrafts } from "../../../state/leaveGuards";
import { ActionBar } from "../../../ui/ActionBar";
import { ActionControl } from "../../../ui/ActionControl";
import { ActionList, ActionRow } from "../../../ui/ActionList";
import { Button } from "../../../ui/Button";
import { Message } from "../../../ui/Feedback";
import { useOwnedFeedback } from "../../../ui/FeedbackOwners";
import { FieldRow } from "../../../ui/FieldRow";
import { JobStatus } from "../../../ui/JobStatus";
import { DialogBody, DialogHeader } from "../../../ui/Dialog";
import { Modal } from "../../../ui/Modal";
import { Section } from "../../../ui/Section";
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
const wideSheets = new Set<string>([
  "files",
  "versions",
  "speaker-names",
  "name-translation",
  "options",
  "exclusions",
]);

/** The open tool sheet: file choice, options, tools and recovery utilities. */
export function GuidedPanel({ w }: { w: GuidedWorkspace }) {
  const {
    project,
    state,
    backups,
    versions,
    action,
    speakerAction,
    draft,
    values,
    stages,
    completed,
    taskId,
    panel,
    setPanel,
    speakerTab,
    setSpeakerTab,
    utilityActions,
    setUtilityActions,
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
    move,
    stepTask,
    feedback,
    operationJob,
    review,
    task,
    workingFileActions,
    copyTask,
    closePanel,
    widths,
    fileSummary,
    connection,
    formatActions,
    applySpeakerControl,
  } = w;
  const owned = useOwnedFeedback(action.key);
  if (!panel) return null;
  const title =
    panel === "translation-context"
      ? `${phaseLabels[phase]} options`
      : panelTitles[panel];
  const savePanel = (label = "Save & close") => (
    <ActionControl
      label={label}
      variant="primary"
      disabled={disabled}
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
        <div ref={setUtilityActions} className="action-bar-slot" />
        {panel === "speaker-names" && (
          <>
            <Button
              disabled={disabled}
              onClick={() => setPanel("name-translation")}
            >
              API name translation
            </Button>
            <ActionControl
              label={scan.available ? "Scan again" : "Run local scan"}
              disabled={
                disabled ||
                running ||
                !["ready", "applied"].includes(findings.status)
              }
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
        {[
          "speakers",
          "widths",
          "options",
          "tools",
          "translation-context",
        ].includes(panel) &&
          (panel !== "speakers" ||
            (speakerTab === "settings" && draft.dirty)) && (
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
          {panel === "tasks" && (
            <div className="guided-all-tasks">
              {stages.map((item) => (
                <section key={item.id}>
                  <h3>{item.title}</h3>
                  {item.tasks.map((entry) => (
                    <Button
                      key={entry.id}
                      variant="quiet"
                      aria-current={entry.id === taskId ? "step" : undefined}
                      onClick={() => move(item.id, entry.id)}
                    >
                      {entry.title}
                      {completed.has(entry.id) && (
                        <span
                          className="guided-completed"
                          aria-label="Complete"
                        >
                          ✓
                        </span>
                      )}
                    </Button>
                  ))}
                </section>
              ))}
            </div>
          )}
          {panel === "file-tools" && (
            <>
              <p>
                Working copies are managed automatically for this game.
                Reopening or changing selection keeps saved progress.
              </p>
              <ActionList>{workingFileActions()}</ActionList>
            </>
          )}
          {panel === "project-tools" && (
            <ActionList>
              <ActionRow
                label={
                  <>
                    <strong>Move to a newer game release</strong>
                    <small>
                      Bring a developer’s update into the game you’re
                      translating.
                    </small>
                  </>
                }
              >
                <Button onClick={() => setPanel("versions")}>
                  Game updates
                </Button>
              </ActionRow>
              <ActionRow
                label={
                  <>
                    <strong>Save or recover files</strong>
                    <small>
                      Manage backups and recover an earlier copy when you need
                      one.
                    </small>
                  </>
                }
              >
                <Button onClick={() => setPanel("backups")}>
                  Backups & recovery
                </Button>
              </ActionRow>
            </ActionList>
          )}
          {panel === "backups" && backups?.(utilityActions)}
          {panel === "versions" &&
            versions?.({
              backups: () => setPanel("backups"),
              prepare: () => stepTask("baseline"),
              checkpoint: () => {
                setPanel(null);
                void review("checkpoint");
              },
              target: utilityActions,
            })}
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
                      <FieldRow
                        id="guided-comment-text"
                        label="Comment text"
                        help={commentTextHelp}
                        helpDisplay="popover"
                      >
                        {(props) => (
                          <input
                            {...props}
                            type="checkbox"
                            disabled={disabled}
                            checked={values.phase1_comments}
                            onChange={(event) =>
                              edit("phase1_comments", event.target.checked)
                            }
                          />
                        )}
                      </FieldRow>
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
              {!["ready", "applied"].includes(findings.status) && (
                <p className="muted">{findings.message}</p>
              )}
              {scan.job && ["ready", "running"].includes(scan.job.status) && (
                <JobStatus
                  compact
                  job={{ ...scan.job, label: "Local speaker scan" }}
                />
              )}
            </>
          )}
          {panel === "name-translation" && (
            <>
              {fileSummary(eventFiles.length)}
              {connection}
              <p className="muted">
                Optional · creates provisional translated names using the API.
                Investigation and local scanning do not require this.
              </p>
              {task(
                "start",
                "Review paid name translation",
                { mode: "speakers" },
                !baseline ||
                  !eventFiles.length ||
                  !state.provider.ready ||
                  !state.provider.enabled,
              )}
            </>
          )}
          {panel === "widths" && (
            <>
              {widths}
              {copyTask("wrap", "Copy width-measurement task")}
            </>
          )}
          {panel === "options" && (
            <>
              <EngineOptions
                state={state}
                values={values.engine_options}
                keys={[
                  "IGNORETLTEXT",
                  "PRESERVEORIGINAL",
                  "FIXTEXTWRAP",
                  "BRFLAG",
                  "TLSYSTEMVARIABLES",
                  "TLSYSTEMSWITCHES",
                ]}
                disabled={disabled}
                change={(key, value) =>
                  edit("engine_options", {
                    ...values.engine_options,
                    [key]: value,
                  })
                }
              />
              <Button variant="quiet" onClick={() => setPanel("file-tools")}>
                Working file options
              </Button>
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
                <div className="guided-widths">
                  {(
                    [
                      ["hotkey", "TL Inspector hotkey"],
                      ["forgeHotkey", "Forge hotkey"],
                    ] as const
                  ).map(([key, label]) => (
                    <label key={key}>
                      {label}
                      <input
                        value={release.tools[key]}
                        onChange={(event) =>
                          editRelease("tools", {
                            ...release.tools,
                            [key]: event.target.value,
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
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
                      <input
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
              {task("editors", "Find installed editors")}
              {operationJob("editors")?.result && (
                <pre>
                  {JSON.stringify(operationJob("editors")!.result, null, 2)}
                </pre>
              )}
              <Section title="Installed plugins">
                {task(
                  "playtest_apply",
                  "Apply settings to game",
                  {},
                  !baseline ||
                    (!state.tools?.inspector.installed &&
                      !state.tools?.forge.installed),
                )}
              </Section>
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
          <Message message={action.error && !owned ? action.error : ""} />
        }
      >
        {panelActions}
      </ActionBar>
    </Modal>
  );
}
