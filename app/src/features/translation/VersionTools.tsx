import { PathText } from "../../ui/PathText";
import { useState } from "react";
import type { ReactNode } from "react";
import type { TranslationState } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { Section } from "../../ui/Section";
import { FieldRow } from "../../ui/FieldRow";

export function VersionTools({
  state,
  disabled,
  browse,
  control,
}: {
  state: TranslationState;
  disabled: boolean;
  browse: (choose: (path: string) => void) => void;
  control: (
    action: string,
    label: string,
    args?: Record<string, unknown>,
    blocked?: boolean,
  ) => ReactNode;
}) {
  const [version, setVersion] = useState(state.git?.original_version || "");
  const [manifest, setManifest] = useState(
    ".dazedtl/len-method/work/patch-files.json",
  );
  const [untranslated, setUntranslated] = useState(false);
  const [original, setOriginal] = useState("");
  return (
    <div className="version-form">
      <p className="muted">
        These controls support an assistant-managed project. Your starting
        prompt normally handles them.
      </p>
      <Section title="Set up version tracking">
        <label>
          Original game version
          <input
            disabled={disabled}
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            placeholder="For example, 1.00"
          />
        </label>
        <label>
          Runtime patch manifest
          <input
            disabled={disabled}
            value={manifest}
            onChange={(event) => setManifest(event.target.value)}
          />
        </label>
        <label className="version-check">
          <input
            type="checkbox"
            disabled={disabled}
            checked={untranslated}
            onChange={(event) => setUntranslated(event.target.checked)}
          />
          The selected game has been checked and is untranslated.
        </label>
        {!untranslated && (
          <FieldRow
            id="version-matching-original"
            label="Matching untranslated original"
          >
            {(props) => (
              <div className="version-folder">
                <input
                  {...props}
                  disabled={disabled}
                  value={original}
                  onChange={(event) => setOriginal(event.target.value)}
                />
                <Button disabled={disabled} onClick={() => browse(setOriginal)}>
                  Choose folder
                </Button>
              </div>
            )}
          </FieldRow>
        )}
        <div className="actions">
          {["MVMZ", "ACE"].includes(state.engine) &&
            control("rpgmaker_prepare", "Prepare RPG Maker files")}
          {control(
            "git_setup",
            "Record game version",
            { version, manifest, untranslated, original },
            !version.trim() || (!untranslated && !original.trim()),
          )}
        </div>
      </Section>
      <Section title="Build a local patch">
        <div className="actions">
          {control(
            "package",
            "Build local patch",
            {},
            !state.git?.configured || state.progress?.phases.qa !== "complete",
          )}
        </div>
        {state.lifecycle.delivery && (
          <p className="translation-path">
            Last package: <PathText path={state.lifecycle.delivery.path} wrap />
          </p>
        )}
      </Section>
    </div>
  );
}
