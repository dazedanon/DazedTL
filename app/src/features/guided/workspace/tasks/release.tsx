/** Release: build the game or patch archive. */
import type { ReactNode } from "react";
import { api } from "../../../../api/client";
import { ActionControl } from "../../../../ui/ActionControl";
import { ReleaseContent } from "../../Release";
import type { GuidedWorkspace } from "../useGuidedWorkspace";
import type { TaskView } from "./view";

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
    destinationPending,
    artifact,
    editText,
    save,
    disabled,
    navigate,
    feedback,
    task,
    chooseFolder,
  } = w;
  let content: ReactNode, primary: ReactNode;
  content = (
    <ReleaseContent
      value={release}
      destinationError={destinationError}
      disabled={disabled}
      artifact={artifact}
      unapplied={state.readiness.unapplied}
      apply={
        <ActionControl
          label="Open Apply"
          disabled={disabled}
          {...feedback("release:apply", "Opening Apply…")}
          onClick={() =>
            action.run(
              async () => {
                editText("view", "apply");
                await navigate("apply", "apply");
              },
              "",
              "release:apply",
            )
          }
        />
      }
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
          disabled={
            disabled ||
            !release.directory ||
            !release.name ||
            !!destinationError ||
            !!state.readiness.unapplied.length
          }
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
        state.engine === "ACE" ? (
          <>
            <p className="muted">{state.acePacking.message}</p>
            {!state.aceAvailable && !state.acePacking.current && (
              <p>Native packing requires a supported Windows environment.</p>
            )}
            {task(
              "ace_pack",
              state.acePacking.current
                ? "Review native packing again"
                : "Review native Ace packing",
              {},
              !baseline || !state.aceAvailable || !state.files.length,
            )}
          </>
        ) : undefined
      }
    />
  );
  primary = task(
    releaseAction,
    release.kind === "game"
      ? "Build clean game ZIP"
      : "Review & build patch ZIP",
    { output: releasePath },
    destinationError
      ? "Choose a destination the archive can be saved to."
      : !baseline ||
          !release.directory.trim() ||
          !release.name.trim() ||
          destinationPending ||
          !state.acePacking.current ||
          !!state.readiness.unapplied.length,
    "primary",
  );
  // Building with nothing applied packages the original text; say so once,
  // unless the destination must be fixed first.
  const actionContext = !destinationError &&
    !state.readiness.applied.length &&
    !state.readiness.unapplied.length && (
      <span>Nothing applied yet: the ZIP keeps the original text.</span>
    );
  return { content, primary, actionContext };
}
