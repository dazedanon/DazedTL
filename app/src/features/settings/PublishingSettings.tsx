import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { Forge, PublishingSettings as Values } from "../../api/contracts";
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
 * The translator's name in translated games' window titles, and where
 * players' GameUpdate downloads the published patches; each game adds its
 * own repository on its Project page.
 */
export default function PublishingSettings({
  values,
  dirty,
  busy,
  error,
  notice,
  edit,
  save,
  revert,
}: {
  values: Values;
  dirty: boolean;
  busy: boolean;
  error: string;
  notice: string;
  edit: (values: Values) => void;
  save: () => void;
  revert: () => void;
}) {
  const form = useRef<HTMLFormElement>(null);
  useSaveForm(form);
  const title = useWindowTitle(values.translator);
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
          Your name in every translated game&apos;s window title, and where
          players&apos; GameUpdate downloads your latest published patch. Each
          game&apos;s repository is set in its Release task, or on Options for
          Assistant-led and Manual.
        </p>
        <fieldset disabled={busy}>
          <FieldRow
            id="publishing-translator"
            label="Translator"
            help="Shown in each translated game's window title. Leave it empty to keep games' own titles."
            note={
              values.translator.trim()
                ? `Window title: ${title}`
                : "Window title: each game keeps its own."
            }
          >
            {(control) => (
              <input
                {...control}
                value={values.translator}
                maxLength={80}
                spellCheck={false}
                onChange={(event) =>
                  edit({ ...values, translator: event.target.value })
                }
              />
            )}
          </FieldRow>
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
            guide="publishing-with-gameupdate"
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
          title={`Save publishing settings (${shortcutLabel.save})`}
          aria-keyshortcuts={shortcutKeys.save}
          disabled={!dirty || busy}
        >
          Save publishing settings
        </Button>
      </ActionBar>
    </form>
  );
}

/**
 * The window title `translator` gives the open game, as the backend forms
 * it, read again a moment after typing stops.
 */
function useWindowTitle(translator: string) {
  const [title, setTitle] = useState("");
  useEffect(() => {
    if (!translator.trim()) return;
    let current = true;
    const timer = window.setTimeout(() => {
      api.windowTitle(translator).then(
        (value) => current && setTitle(value.title),
        () => undefined,
      );
    }, 150);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [translator]);
  return title;
}
