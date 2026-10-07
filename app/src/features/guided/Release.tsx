import { PathInput } from "../../ui/PathInput";
import type { ReactNode } from "react";
import type { GuidedForm, Preview, ReleaseArtifact } from "../../api/contracts";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { Section } from "../../ui/Section";
import { VirtualList } from "../../ui/VirtualList";
import { OptionCards } from "../../ui/OptionCards";
import { HelpPopover } from "../../ui/HelpPopover";

type Options = GuidedForm["release"];
const pathKey = (path: string) => path;
const size = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export function ReleaseContent({
  value,
  destinationError,
  edit,
  disabled,
  chooseFolder,
  inspect,
  assets,
  artifact,
  open,
  packing,
  unapplied,
  apply,
}: {
  value: Options;
  /** Why the archive cannot be saved at the chosen name and folder. */
  destinationError: string;
  edit: (change: Partial<Options>) => void;
  disabled: boolean;
  chooseFolder: () => void;
  inspect: ReactNode;
  assets: () => void;
  artifact?: ReleaseArtifact;
  open: ReactNode;
  packing?: ReactNode;
  unapplied: string[];
  apply: ReactNode;
}) {
  const kind = value.kind;
  return (
    <>
      <fieldset disabled={disabled}>
        <OptionCards
          label="Package type"
          value={kind}
          onChange={(key) =>
            edit({
              kind: key,
              name: value.names[key],
              names: { ...value.names, [kind]: value.name },
            })
          }
          options={[
            {
              value: "game",
              title: "Clean game ZIP",
              description: "Complete game folder, ready to extract and play.",
            },
            {
              value: "patch",
              title: "Patch ZIP",
              description: "Runtime patch for the matching original version.",
            },
          ]}
        />
        <div className="guided-package-fields">
          <label>
            Archive name
            <input
              value={value.name}
              aria-invalid={destinationError ? true : undefined}
              aria-describedby={
                destinationError ? "release-destination-error" : undefined
              }
              onChange={(event) =>
                edit({
                  name: event.target.value,
                  names: { ...value.names, [kind]: event.target.value },
                })
              }
            />
          </label>
          <label>
            Save in
            <div className="guided-folder-field">
              <PathInput
                aria-label="Save in"
                value={value.directory}
                aria-invalid={destinationError ? true : undefined}
                aria-describedby={
                  destinationError ? "release-destination-error" : undefined
                }
                onChange={(event) => edit({ directory: event.target.value })}
              />
              <Button onClick={chooseFolder}>Choose folder</Button>
            </div>
          </label>
          {destinationError && (
            <small
              className="field-error guided-package-error"
              id="release-destination-error"
              role="alert"
            >
              {destinationError}
            </small>
          )}
        </div>
      </fieldset>
      {!!unapplied.length && (
        <Section title="Apply saved outputs before building">
          <ActionList>
            <ActionRow
              label={
                <>
                  <strong>
                    {unapplied.length.toLocaleString()} selected{" "}
                    {unapplied.length === 1 ? "output needs" : "outputs need"}{" "}
                    Apply
                  </strong>
                  <small>
                    Apply these saved outputs to the game before building a ZIP.
                  </small>
                </>
              }
            >
              {apply}
            </ActionRow>
          </ActionList>
          {unapplied.length <= 8 ? (
            <ul
              className="guided-preview-paths"
              aria-label="Outputs awaiting Apply"
            >
              {unapplied.map((name) => (
                <li className="guided-preview-path" key={name}>
                  {name}
                </li>
              ))}
            </ul>
          ) : (
            <div className="guided-preview-files">
              <VirtualList
                items={unapplied}
                itemKey={pathKey}
                label="Outputs awaiting Apply"
                empty={null}
              >
                {(name) => <div className="guided-preview-path">{name}</div>}
              </VirtualList>
            </div>
          )}
        </Section>
      )}
      {packing && <Section title="Native Ace data">{packing}</Section>}
      <ActionList>
        <ActionRow
          label={
            <>
              <strong>
                Archive contents{" "}
                <HelpPopover label="Archive contents">
                  Known private and translator files are excluded. Inspect the
                  contents if you added other local material to the game.
                </HelpPopover>
              </strong>
              <small>
                {kind === "game"
                  ? "Current runtime data, plugins, assets and player documentation."
                  : "Reviewed runtime files and applied images for the matching original game."}
              </small>
            </>
          }
        >
          {inspect}
        </ActionRow>
        {kind === "patch" && (
          <ActionRow
            label={
              <>
                <strong>Additional images & fonts</strong>
                <small>
                  Applied images and tracked assets are included automatically.
                  Add other player assets by exact path.
                </small>
              </>
            }
          >
            <Button disabled={disabled} onClick={assets}>
              Edit runtime assets
            </Button>
          </ActionRow>
        )}
      </ActionList>
      {artifact && (
        <section className="guided-artifact" aria-label="Last saved archive">
          <ActionList>
            <ActionRow
              label={
                <>
                  <strong>
                    Last saved {kind === "game" ? "game" : "patch"} ZIP
                  </strong>
                  <small>
                    {artifact.size === null
                      ? "Size unavailable"
                      : size(artifact.size)}
                    {artifact.saved
                      ? ` · Saved ${new Date(artifact.saved).toLocaleString()}`
                      : ""}{" "}
                    ·{" "}
                    {!artifact.available
                      ? "Unavailable or changed on disk"
                      : artifact.current
                        ? "Up to date"
                        : artifact.current === false
                          ? "Game files changed since this build"
                          : "Available on disk"}
                  </small>
                  <small className="path">{artifact.path}</small>
                  {artifact.available && !artifact.current && (
                    <small>
                      {artifact.current === false
                        ? "Build again to include the changes."
                        : "Later game edits are included only when you build again."}
                    </small>
                  )}
                </>
              }
            >
              {open}
            </ActionRow>
          </ActionList>
        </section>
      )}
    </>
  );
}

export function ReleaseReview({
  preview,
  inspectOnly,
  busy,
  editAssets,
}: {
  preview: Preview;
  inspectOnly: boolean;
  busy: boolean;
  editAssets: () => void;
}) {
  const patch = preview.action === "release_patch";
  return (
    <div className="release-review">
      {patch && (
        <p>
          For the matching original game
          {preview.game_version ? `, version ${preview.game_version}` : ""}.
          Extract over that game.
        </p>
      )}
      {preview.overwrite && (
        <div className="release-overwrite">
          <strong>
            {inspectOnly
              ? "An archive already exists here"
              : "Replace an existing ZIP"}
          </strong>
          <p className="path">{preview.destination}</p>
          <small>
            The previous ZIP stays in place until the new archive is complete.
          </small>
        </div>
      )}
      {!preview.overwrite && <p className="path">{preview.destination}</p>}
      {/* Only a patch has assets to edit; a bare count needs no panel. */}
      {patch ? (
        <ActionList>
          <ActionRow
            label={
              <strong>
                {preview.paths.length.toLocaleString()} runtime files
              </strong>
            }
          >
            <Button disabled={busy} onClick={editAssets}>
              Edit runtime assets
            </Button>
          </ActionRow>
        </ActionList>
      ) : (
        <p>{preview.paths.length.toLocaleString()} runtime files</p>
      )}
      <div className="guided-preview-files">
        <VirtualList
          items={preview.paths}
          itemKey={pathKey}
          label="Archive runtime files"
          empty={<p>No runtime files included.</p>}
        >
          {(name) => <div className="guided-preview-path">{name}</div>}
        </VirtualList>
      </div>
      {!!preview.package?.generated?.length && (
        <details>
          <summary>Archive additions and repository metadata</summary>
          <ul>
            {preview.package.generated.map((name) => (
              <li className="guided-preview-path" key={name}>
                {name}
              </li>
            ))}
          </ul>
        </details>
      )}
      <details>
        <summary>
          Excluded files and folders
          {preview.package?.exclusions?.length
            ? ` (${preview.package.exclusions.length})`
            : ""}
        </summary>
        <div className="release-exclusions">
          {preview.package?.exclusions?.map((row) => (
            <p key={row.path}>
              <span className="guided-preview-path">{row.path}</span>
              <small>{row.reason}</small>
            </p>
          ))}
        </div>
        {!preview.package?.exclusions?.length && (
          <p>No selected entries were excluded.</p>
        )}
      </details>
      <p className="muted">{preview.package?.updater}</p>
      {patch && (
        <p className="muted">
          Build also saves the reviewed scope as a translation version and backs
          up the project first. No publication.
        </p>
      )}
    </div>
  );
}
