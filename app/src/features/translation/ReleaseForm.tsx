import { useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type { ReleaseLayout } from "../../api/contracts";
import { useRead } from "../../state/useRead";
import { ActionSlot } from "../../ui/ActionSlot";
import { Button } from "../../ui/Button";
import { FieldRow } from "../../ui/FieldRow";
import { OptionCards } from "../../ui/OptionCards";
import { PathInput } from "../../ui/PathInput";
import { Section } from "../../ui/Section";
import { releaseEffect, releasePlacement } from "./versionState";

/** The release being chosen; `version` and `kind` stay unset until the user
 * changes them, so the folder's own version and detected kind apply. */
export type ReleaseDraft = {
  folder: string;
  version: string | null;
  kind: ReleaseLayout["kind"] | null;
};
export const emptyRelease: ReleaseDraft = {
  folder: "",
  version: null,
  kind: null,
};
export type StageRequest = {
  official: string;
  version: string;
  patch: boolean;
};

// Typing a path pauses this long before the folder is read, so a partly typed
// path such as a whole drive is not walked on every keystroke.
const SETTLE_MS = 600;

/** The new official release's folder, whether it is a complete game or a
 * patch, and its version. */
export function ReleaseForm({
  projectId,
  value,
  onChange,
  disabled,
  browse,
  actionTarget,
  footer,
}: {
  projectId: string;
  value: ReleaseDraft;
  onChange: (value: ReleaseDraft) => void;
  disabled: boolean;
  browse: (choose: (path: string) => void) => void;
  actionTarget?: HTMLElement | null;
  /** The footer's actions, given the release to stage once it is complete. */
  footer: (release: StageRequest | null) => ReactNode;
}) {
  const folder = value.folder.trim();
  const [checked, setChecked] = useState(folder);
  useEffect(() => {
    const timer = setTimeout(() => setChecked(folder), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [folder]);
  const release = useRead(checked ? `${projectId}\n${checked}` : null, () =>
    api.translation.release(projectId, checked),
  );
  const settled = folder === checked;
  const inspection = settled ? release.value : undefined;
  const checking = !!folder && (!settled || release.pending);
  const error = settled && release.error ? messageOf(release.error) : "";
  const kind = value.kind ?? inspection?.detected;
  const layout = inspection && kind ? inspection[kind] : undefined;
  const version = value.version ?? inspection?.version ?? "";
  const placement = layout ? releasePlacement(layout) : "";
  const choose = (path: string) => {
    setChecked(path.trim());
    onChange({ ...value, folder: path, kind: null });
  };
  return (
    <Section title="Choose the new official release">
      <p>
        Choose the folder the developer released: the complete game, or a patch
        of files to copy over it. DazedTL compares a separate copy before it
        changes the game.
      </p>
      <fieldset className="version-form" disabled={disabled}>
        <FieldRow
          id="update-official-folder"
          label="New release folder"
          error={error}
        >
          {(props) => (
            <div className="version-folder">
              <PathInput
                {...props}
                value={value.folder}
                onChange={(event) =>
                  onChange({ ...value, folder: event.target.value, kind: null })
                }
              />
              <Button onClick={() => browse(choose)}>Choose folder</Button>
            </div>
          )}
        </FieldRow>
        {checking && <p className="muted">Checking the folder…</p>}
        {inspection && kind && (
          <OptionCards
            label="Release type"
            value={kind}
            onChange={(next) => onChange({ ...value, kind: next })}
            options={[
              {
                value: "game",
                title: "Complete game",
                description: releaseEffect(inspection.game),
                badge: inspection.detected === "game" ? "Detected" : undefined,
              },
              {
                value: "patch",
                title: "Patch",
                description: releaseEffect(inspection.patch),
                badge: inspection.detected === "patch" ? "Detected" : undefined,
              },
            ]}
          />
        )}
        {placement && <p className="muted">{placement}</p>}
        <FieldRow id="update-version" label="New game version">
          {(props) => (
            <input
              {...props}
              className="short-control"
              value={version}
              onChange={(event) =>
                onChange({ ...value, version: event.target.value })
              }
              placeholder="e.g. 1.10"
            />
          )}
        </FieldRow>
      </fieldset>
      <ActionSlot target={actionTarget}>
        {footer(
          layout && version.trim()
            ? {
                official: checked,
                version: version.trim(),
                patch: layout.kind === "patch",
              }
            : null,
        )}
      </ActionSlot>
    </Section>
  );
}
