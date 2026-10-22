import { FolderOpen } from "lucide-react";
/** Release: build the game or patch archive. */
import type { ReactNode } from "react";
import { api } from "../../../../api/client";
import { ActionControl } from "../../../../ui/ActionControl";
import { ActionRow } from "../../../../ui/ActionList";
import { Button } from "../../../../ui/Button";
import { ReleaseContent } from "../../Release";
import { reloadBeforeApply } from "../../translationView";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";
import { StatusHeading } from "../../../../ui/StatusMark";
import { sinceLabel } from "../../../assistant/assistantTasks";
import { GameUpdatePanel } from "../../../project/GameUpdatePanel";
import { savedTranslations } from "../../translationView";

export function packageView(w: GuidedWorkspace): TaskView {
  const {
    project,
    state,
    action,
    form,
    setPanel,
    setPreview,
    setInspectRelease,
    baseline,
    release,
    releaseAction,
    releasePath,
    destinationError,
    destinationField,
    destinationPending,
    artifact,
    save,
    disabled,
    changed,
    feedback,
    task,
    chooseFolder,
    copyTask,
    localOperation,
    stopControl,
    handoff,
    translation,
    settings,
  } = w;
  // GameUpdate's config must be complete before a release; its repository is
  // set below the release's own options.
  const updaterBlocked = translation.gameUpdate.state === "needs_repo";
  const writing = handoff("walkthrough");
  // Why the destination blocks both reading and building the archive.
  const destinationReason =
    destinationField === "name"
      ? "Choose another archive name."
      : destinationError
        ? "Choose a destination the archive can be saved to."
        : "";
  let content: ReactNode;
  content = (
    <>
      <ReleaseContent
        value={release}
        destinationError={destinationError}
        destinationField={destinationField}
        disabled={disabled}
        artifact={artifact}
        unapplied={state.readiness.unapplied}
        apply={task(
          "export_selected",
          `Apply (${state.readiness.unapplied.length.toLocaleString()})`,
          {},
          !baseline ||
            !!state.collectionError ||
            (w.archiveRead && "Convert Ace data in Set up first.") ||
            reloadBeforeApply(state.readiness.unapplied, changed),
          "default",
          state.readiness.unapplied,
        )}
        edit={(change) =>
          form.session.edit((current) => ({
            ...current,
            release: { ...current.release, ...change },
          }))
        }
        chooseFolder={() => chooseFolder("release")}
        assets={() => setPanel("release-assets")}
        inspect={
          <ActionControl
            label="View files & exclusions"
            // A patch lists packed Ace data, so it waits for packing, which
            // the Native Ace data section above asks for.
            disabled={
              disabled ||
              !release.directory ||
              !release.name ||
              !!destinationError ||
              !!state.readiness.unapplied.length ||
              (release.kind === "patch" && !state.acePacking.current)
            }
            disabledReason={destinationReason}
            {...feedback("package:inspect", "Reading archive contents…")}
            onClick={() =>
              action.run(
                async () => {
                  await save();
                  setInspectRelease(true);
                  setPreview(
                    await api.preview(project.id, releaseAction, undefined, {
                      output: releasePath,
                    }),
                  );
                },
                "",
                "package:inspect",
              )
            }
          />
        }
        open={
          <ActionControl
            label="Open release folder"
            icon={<FolderOpen size={16} aria-hidden="true" />}
            disabled={!artifact?.available || action.busy}
            {...feedback("open-release", "Opening…")}
            onClick={() =>
              action.run(
                () => window.dazedtl.openFolder("output", artifact!.folder),
                "Release folder opened.",
                "open-release",
              )
            }
          />
        }
        packing={
          // Apply packs an Ace game's data; this catches ace_json edited
          // outside the app. An archive the game still reads has its own
          // notice on every task.
          w.acePackShown ? (
            <>
              {/* After a pack from this visit its notice says so. */}
              {!state.acePacking.current && (
                <p className="muted">{state.acePacking.message}</p>
              )}
              {task(
                "ace_pack",
                "Pack outside edits",
                {},
                !baseline || !state.files.length,
              )}
            </>
          ) : undefined
        }
        extras={
          <ActionRow
            label={
              <>
                {writing.waiting ? (
                  <StatusHeading state="waiting" title="Player walkthrough" />
                ) : writing.saved ? (
                  <StatusHeading state="done" title="Player walkthrough" />
                ) : (
                  <strong>Player walkthrough</strong>
                )}
                <small>
                  {writing.waiting
                    ? `${writing.detail || "Expecting WALKTHROUGH.html in the game folder"} · ${sinceLabel(writing.since)}`
                    : writing.saved
                      ? "Saved as WALKTHROUGH.html in the game folder."
                      : "Optional. Your coding assistant writes a portable walkthrough for players."}
                </small>
              </>
            }
          >
            {copyTask("walkthrough", "Copy walkthrough task")}
          </ActionRow>
        }
      />
      <GameUpdatePanel
        key={project.id}
        projectId={project.id}
        status={translation.gameUpdate}
        disabled={disabled}
        openSettings={() => settings("gameupdate")}
      />
    </>
  );
  const build = task(
    releaseAction,
    release.kind === "game"
      ? "Build clean game ZIP"
      : "Review & build patch ZIP",
    { output: releasePath },
    destinationReason ||
      updaterBlocked ||
      !baseline ||
      !release.directory.trim() ||
      !release.name.trim() ||
      destinationPending ||
      !state.acePacking.current ||
      !!state.readiness.unapplied.length,
    "primary",
  );
  // Building with no text applied packages the original text, even with
  // applied images; say so once, unless the destination must be fixed first.
  const actionContext = destinationError ? undefined : updaterBlocked ? (
    <span>
      GameUpdate needs this game&apos;s repository.{" "}
      <Button
        variant="link"
        onClick={() => {
          const field = document.getElementById("gameupdate-repo");
          field?.scrollIntoView({ block: "center" });
          field?.focus();
        }}
      >
        Set repository
      </Button>
    </span>
  ) : (
    !savedTranslations(state).applied.length &&
    !state.readiness.unapplied.length && (
      <span>
        No translated text applied yet: the ZIP keeps the original text.
      </span>
    )
  );
  // A running build reports its progress beside its own button.
  const secondary = localOperation && stopControl(localOperation, "Stop build");
  return { content, secondary, action: build, actionContext };
}
