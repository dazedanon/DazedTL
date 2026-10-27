/**
 * Assistant-led Release: Guided's release form, which builds a clean game ZIP
 * or the assistant's patch ZIP where the user chooses.
 */

import { useState, type ReactNode } from "react";
import { FolderOpen } from "lucide-react";
import { api } from "../../api/client";
import type {
  AssistantRelease,
  AssistantReleaseForm,
  ReleaseArtifact,
  ReleasePreview,
  TranslationState,
} from "../../api/contracts";
import { flushDrafts } from "../../state/leaveGuards";
import type { useAction } from "../../state/useAction";
import { useDraft } from "../../state/useDraft";
import { useRead } from "../../state/useRead";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { childPath } from "../../ui/displayPath";
import { Message } from "../../ui/Feedback";
import { Modal } from "../../ui/Modal";
import { PageBody } from "../../ui/PageLayout";
import { ReleaseContent, ReleaseReview } from "../guided/Release";

const builds = { game: "release-build:game", patch: "release-build:patch" };

/** Why the patch can't be built yet, as far as the state tells, or "". The
 * patch's own checks say the rest when the build is reviewed. */
export const patchWaiting = (state: TranslationState) =>
  !state.git?.configured
    ? "Your assistant sets up the game's version tracking first."
    : state.progress?.phases.qa !== "complete"
      ? "The patch waits for your assistant's QA."
      : "";

/** Opens the folder a saved release ZIP is in. */
export function OpenReleaseFolder({
  artifact,
  action,
  feedbackKey,
}: {
  artifact: ReleaseArtifact;
  action: ReturnType<typeof useAction>;
  feedbackKey: string;
}) {
  return (
    <ActionControl
      label="Open folder"
      icon={<FolderOpen size={16} aria-hidden="true" />}
      disabled={!artifact.available || action.busy}
      feedbackKey={feedbackKey}
      pending={action.busy && action.key === feedbackKey}
      pendingText="Opening…"
      error={action.key === feedbackKey ? action.error : ""}
      onClick={() =>
        void action.run(
          () => window.dazedtl.openFolder("output", artifact.folder),
          "",
          feedbackKey,
        )
      }
    />
  );
}

export function ReleaseTab({
  state,
  release,
  action,
  disabled,
  showOptions,
  copy,
}: {
  state: TranslationState;
  release: AssistantRelease;
  action: ReturnType<typeof useAction>;
  disabled: boolean;
  /** GameUpdate's repository is set in Options. */
  showOptions: () => void;
  /** The page's starting prompt. */
  copy: ReactNode;
}) {
  const projectId = state.projectId;
  const form = useDraft<AssistantReleaseForm>(
    "translation-release:" + projectId,
    {
      initial: { saved: release.form },
      report: action.report,
      persist: (value) => api.translation.releaseForm(projectId, value),
      autosave: true,
    },
  );
  const value = form.value || release.form;
  const kind = value.kind;
  const output = childPath(value.directory, value.name);
  // The destination is checked while it is typed, so Build never learns of
  // a rejected folder late; the name's own separator rule needs no read.
  const nameError = /[\\/]/.test(value.name)
    ? "Use a filename without folder separators. Choose the destination in Save in."
    : "";
  const destination = useRead(
    !nameError && value.directory.trim() && value.name.trim()
      ? `${projectId}\n${kind}\n${output}`
      : null,
    () => api.translation.releaseDestination(projectId, output, kind),
  );
  const destinationError = nameError || destination.value?.error || "";
  const destinationField = nameError ? "name" : destination.value?.field || "";
  const [review, setReview] = useState<{
    preview: ReleasePreview;
    inspect: boolean;
  } | null>(null);
  // The build this visit started reports beside its button.
  const [started, setStarted] = useState<Record<string, string>>({});
  const job = state.jobs.find((item) => item.id === started[kind]);
  const artifact = release.artifacts.find((item) => item.kind === kind);
  const edit = (change: Partial<AssistantReleaseForm>) =>
    form.session.edit((current) => ({ ...current, ...change }));
  const chooseFolder = () =>
    void action.run(
      async () => {
        const folder = await window.dazedtl.chooseFolder();
        if (folder) edit({ directory: folder });
      },
      "",
      "release-folder",
    );
  const reason =
    destinationField === "name"
      ? "Choose another archive name."
      : destinationError
        ? "Choose a destination the archive can be saved to."
        : !value.directory.trim() || !value.name.trim()
          ? "Choose the archive's name and folder."
          : state.gameUpdate.state === "needs_repo"
            ? "Enter this game's GameUpdate repository in Options first."
            : kind === "patch"
              ? patchWaiting(state)
              : "";
  const startBuild = async (preview: ReleasePreview) => {
    const built = await api.translation.releaseBuild(
      projectId,
      kind,
      preview.plan,
      preview.sha256,
    );
    setStarted((current) => ({ ...current, [kind]: built.id }));
    setReview(null);
  };
  // Building reads the archive's contents first: a patch is always
  // reviewed, a game ZIP only when it replaces one.
  const inspect = (only: boolean) =>
    void action.run(
      async () => {
        await flushDrafts();
        const preview = await api.translation.releasePreview(
          projectId,
          kind,
          output,
        );
        if (only || kind === "patch" || preview.overwrite)
          setReview({ preview, inspect: only });
        else await startBuild(preview);
      },
      "",
      only ? "release-inspect" : builds[kind],
    );
  const preview = review?.preview;
  return (
    <>
      <PageBody>
        <ReleaseContent
          value={value}
          destinationError={destinationError}
          destinationField={destinationField}
          edit={edit}
          disabled={disabled}
          chooseFolder={chooseFolder}
          artifact={artifact}
          build={builds[kind]}
          // Why it can't be built yet shows once, beside the build.
          outdatedNote={
            kind === "patch" && patchWaiting(state) ? null : undefined
          }
          inspect={
            <ActionControl
              label="View files & exclusions"
              // Why it waits shows once, beside the build.
              disabled={disabled || !!reason}
              feedbackKey="release-inspect"
              pending={action.busy && action.key === "release-inspect"}
              pendingText="Reading archive contents…"
              error={action.key === "release-inspect" ? action.error : ""}
              onClick={() => inspect(true)}
            />
          }
          open={
            artifact && (
              <OpenReleaseFolder
                artifact={artifact}
                action={action}
                feedbackKey="release-open"
              />
            )
          }
        />
        {state.gameUpdate.state === "needs_repo" && (
          <p className="muted">
            GameUpdate needs this game&apos;s repository.{" "}
            <Button variant="link" onClick={showOptions}>
              Set repository
            </Button>
          </p>
        )}
      </PageBody>
      <ActionBar feedback={null}>
        <ActionControl
          variant="primary"
          label={
            kind === "game"
              ? "Build clean game ZIP"
              : "Review & build patch ZIP"
          }
          disabled={disabled || !!reason}
          disabledReason={reason}
          feedbackKey={builds[kind]}
          pending={action.busy && action.key === builds[kind]}
          pendingText="Reading archive contents…"
          error={action.key === builds[kind] && !review ? action.error : ""}
          job={job}
          onClick={() => inspect(false)}
        />
        {copy}
      </ActionBar>
      {preview && (
        <Modal
          label={
            review.inspect
              ? "Archive contents"
              : kind === "patch"
                ? "Review patch ZIP"
                : "Replace game ZIP"
          }
          size="md"
          className="guided-sheet guided-release-review"
          dismissible={!action.busy}
          onDismiss={() => setReview(null)}
        >
          <DialogHeader
            title={
              review.inspect
                ? "Archive contents"
                : kind === "patch"
                  ? "Review patch ZIP"
                  : "Replace game ZIP"
            }
            onClose={review.inspect ? () => setReview(null) : undefined}
            closeDisabled={action.busy}
          />
          <DialogBody>
            <ReleaseReview
              preview={preview}
              inspectOnly={review.inspect}
              busy={action.busy}
            />
          </DialogBody>
          {!review.inspect && (
            <ActionBar
              feedback={
                <Message
                  message={action.key === builds[kind] ? action.error : ""}
                />
              }
            >
              <Button disabled={action.busy} onClick={() => setReview(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                pending={action.busy}
                onClick={() =>
                  void action.run(() => startBuild(preview), "", builds[kind])
                }
              >
                {`${preview.overwrite ? "Replace & build" : "Build"} ${kind === "patch" ? "patch" : "game"} ZIP`}
              </Button>
            </ActionBar>
          )}
        </Modal>
      )}
    </>
  );
}
