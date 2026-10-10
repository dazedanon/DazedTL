import { useRef } from "react";
import type { Forge, GameUpdateDefaults } from "../../api/contracts";
import {
  shortcutKeys,
  shortcutLabel,
  useSaveForm,
} from "../../state/useShortcut";
import { PageBody } from "../../ui/PageLayout";
import { FieldRow } from "../../ui/FieldRow";
import { ActionBar } from "../../ui/ActionBar";
import { Feedback } from "../../ui/Feedback";
import { Button } from "../../ui/Button";

/** GameUpdate's forges, as its scripts name them, with their usual host. */
export const forges: { value: Forge; label: string; host: string }[] = [
  { value: "gitlab", label: "GitLab", host: "gitgud.io" },
  { value: "forgejo", label: "Forgejo or Gitea", host: "codeberg.org" },
  { value: "github", label: "GitHub", host: "github.com" },
];

/**
 * Where players' GameUpdate downloads the published patches. Each game adds
 * its own repository on its Project page.
 */
export default function GameUpdateSettings({
  values,
  dirty,
  busy,
  error,
  notice,
  edit,
  save,
  revert,
}: {
  values: GameUpdateDefaults;
  dirty: boolean;
  busy: boolean;
  error: string;
  notice: string;
  edit: (values: GameUpdateDefaults) => void;
  save: () => void;
  revert: () => void;
}) {
  const form = useRef<HTMLFormElement>(null);
  useSaveForm(form);
  const chooseForge = (forge: Forge) => {
    // A host left at the previous forge's usual one follows the new forge.
    const previous = forges.find((item) => item.value === values.forge);
    const next = forges.find((item) => item.value === forge)!;
    const host =
      !values.host.trim() || values.host.trim() === previous?.host
        ? next.host
        : values.host;
    edit({ ...values, forge, host });
  };
  return (
    <form
      ref={form}
      className="editor-form"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <PageBody>
        <p className="settings-intro">
          Players run GameUpdate to download your latest published patch. Each
          game&apos;s repository is on its Project page, under Game updates.
        </p>
        <fieldset disabled={busy}>
          <FieldRow id="gameupdate-forge" label="Forge">
            {(control) => (
              <select
                {...control}
                value={values.forge}
                onChange={(event) => chooseForge(event.target.value as Forge)}
              >
                {forges.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            )}
          </FieldRow>
          <FieldRow
            id="gameupdate-host"
            label="Host"
            help="The site's address without https://, such as gitgud.io."
          >
            {(control) => (
              <input
                {...control}
                value={values.host}
                spellCheck={false}
                onChange={(event) =>
                  edit({ ...values, host: event.target.value })
                }
              />
            )}
          </FieldRow>
          <FieldRow
            id="gameupdate-owner"
            label="Owner"
            help="The user or group your patch repositories belong to. Leave it empty if you don't publish with GameUpdate."
          >
            {(control) => (
              <input
                {...control}
                value={values.owner}
                spellCheck={false}
                onChange={(event) =>
                  edit({ ...values, owner: event.target.value })
                }
              />
            )}
          </FieldRow>
          <FieldRow
            id="gameupdate-branch"
            label="Branch"
            help="The branch players download."
          >
            {(control) => (
              <input
                {...control}
                required
                value={values.branch}
                spellCheck={false}
                onChange={(event) =>
                  edit({ ...values, branch: event.target.value })
                }
              />
            )}
          </FieldRow>
        </fieldset>
      </PageBody>
      <ActionBar
        feedback={
          <Feedback
            error={error}
            pending={busy}
            dirty={dirty}
            notice={notice}
          />
        }
      >
        <Button disabled={!dirty || busy} onClick={revert}>
          Revert
        </Button>
        <Button
          type="submit"
          variant="primary"
          title={`Save GameUpdate settings (${shortcutLabel.save})`}
          aria-keyshortcuts={shortcutKeys.save}
          disabled={!dirty || busy}
        >
          Save GameUpdate settings
        </Button>
      </ActionBar>
    </form>
  );
}
