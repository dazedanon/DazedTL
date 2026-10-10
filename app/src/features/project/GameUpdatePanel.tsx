import { useState } from "react";
import { api } from "../../api/client";
import type { GameUpdateStatus } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { FieldRow } from "../../ui/FieldRow";
import { Notice } from "../../ui/Notice";
import { Section } from "../../ui/Section";
import { StatusIcon, type StatusKind } from "../../ui/StatusIcon";

const CONFIG = "gameupdate/patch-config.txt";
const fieldNames = {
  forge: "forge",
  host: "host",
  owner: "owner",
  repo: "repository",
  branch: "branch",
} as const;

type Values = NonNullable<GameUpdateStatus["values"]>;
const listed = (values: Values, fields: (keyof Values)[]) =>
  fields.map((field) => `${fieldNames[field]} ${values[field]}`).join(", ");

/** Where the game's GameUpdate config stands, in one row. */
function summary(status: GameUpdateStatus): {
  mark: StatusKind;
  title: string;
  detail: string;
} {
  switch (status.state) {
    case "needs_repo":
      return {
        mark: "warning",
        title: "Needs its repository",
        detail:
          "Enter the repository players download from. Releases wait for it.",
      };
    case "pending":
      return {
        mark: "idle",
        title: "Not written yet",
        detail: `Save writes ${CONFIG}.`,
      };
    case "edited":
      return {
        mark: "review",
        title: "Changed outside DazedTL",
        detail: `${CONFIG} has ${listed(status.file!, status.differences)}, but DazedTL would write ${listed(status.values!, status.differences)}.`,
      };
    case "unavailable":
      return {
        mark: "failed",
        title: "Status unavailable",
        detail: status.message,
      };
    // The panel shows no summary for these two.
    case "absent":
    case "unconfigured":
    case "ready":
      return status.committed
        ? {
            mark: "done",
            title: "Ready to publish",
            detail: `${CONFIG} is committed on ${status.file!.branch}.`,
          }
        : {
            mark: "idle",
            title: "Not committed yet",
            detail: `The next translation version commits ${CONFIG}.`,
          };
  }
}

/**
 * Where players' GameUpdate downloads this game's patch, and whether the
 * published translation carries that configuration.
 */
export function GameUpdatePanel({
  projectId,
  status,
  disabled,
  openSettings,
  onCheckpoint,
}: {
  projectId: string;
  status: GameUpdateStatus;
  disabled: boolean;
  openSettings: () => void;
  /** Opens the Guided translation checkpoint review, which commits the
   * config; absent while the version panel already offers it. */
  onCheckpoint?: () => void;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [typed, setTyped] = useState<string | null>(null);
  const repo = typed ?? (status.repo || status.suggested);
  const busy = disabled || action.busy;
  const choose = (
    key: string,
    choice: "save" | "keep" | "replace" | "defaults",
    notice: string,
  ) =>
    action.run(
      async () => {
        await api.translation.gameUpdate(
          projectId,
          choice,
          choice === "save" ? repo.trim() : undefined,
        );
        if (choice === "save") setTyped(null);
      },
      notice,
      key,
    );
  const control = (
    key: string,
    label: string,
    choice: "save" | "keep" | "replace" | "defaults",
    notice: string,
    blocked = false,
    variant: "default" | "link" = "default",
    inline = variant === "link",
  ) => (
    <ActionControl
      label={label}
      variant={variant}
      inline={inline}
      disabled={busy || blocked}
      pending={action.busy && action.key === key}
      pendingText="Saving…"
      error={action.key === key ? action.error : ""}
      notice={action.key === key ? action.notice : ""}
      onClick={() => choose(key, choice, notice)}
    />
  );
  if (status.state === "absent") return null;
  if (status.state === "unconfigured")
    return (
      <Section title="GameUpdate" className="gameupdate-panel">
        <Notice>
          <span>
            DazedTL writes GameUpdate&apos;s configuration once the owner of
            your patch repositories is set in Settings.
          </span>
          <Button variant="link" onClick={openSettings}>
            Open GameUpdate settings
          </Button>
        </Notice>
      </Section>
    );
  const values = status.values;
  // What players get: the file's values, or what Save would write.
  const target = typed === null && status.file ? status.file : values;
  const shownRepo =
    typed === null && status.file ? status.file.repo : repo.trim();
  const row = summary(status);
  const unsaved =
    !!repo.trim() &&
    (repo.trim() !== status.repo ||
      ["pending", "needs_repo"].includes(status.state));
  const own = status.overrides.map((field) => fieldNames[field]);
  return (
    <Section title="GameUpdate" className="gameupdate-panel">
      {status.state !== "unavailable" && (
        <FieldRow
          id="gameupdate-repo"
          label="Repository"
          help={
            target && shownRepo
              ? `Players download ${target.host}/${target.owner}/${shownRepo}, branch ${target.branch}.`
              : values
                ? `Its name under ${values.host}/${values.owner}.`
                : ""
          }
        >
          {(props) => (
            <div className="gameupdate-repo">
              <input
                {...props}
                value={repo}
                spellCheck={false}
                placeholder="repository-name"
                disabled={busy}
                onChange={(event) => {
                  if (action.key === "save") action.clear();
                  setTyped(event.target.value);
                }}
              />
              {control(
                "save",
                "Save",
                "save",
                "Repository saved.",
                !unsaved,
                "default",
                true,
              )}
            </div>
          )}
        </FieldRow>
      )}
      {!!own.length && (
        <div className="gameupdate-note">
          <span>This game sets its own {own.join(" and ")}.</span>
          {control(
            "defaults",
            "Follow Settings",
            "defaults",
            "Following Settings.",
            false,
            "link",
          )}
        </div>
      )}
      <ActionList>
        <ActionRow
          label={
            <>
              <span className="gameupdate-state">
                <StatusIcon status={row.mark} size={14} />
                <strong>{row.title}</strong>
              </span>
              <small>{row.detail}</small>
            </>
          }
        >
          {status.state === "edited" && (
            <>
              {control("keep", "Keep the file", "keep", "Kept for this game.")}
              {control(
                "replace",
                "Rewrite the file",
                "replace",
                `${CONFIG} rewritten.`,
              )}
            </>
          )}
          {status.state === "ready" && !status.committed && onCheckpoint && (
            <Button disabled={busy} onClick={onCheckpoint}>
              Review translation checkpoint
            </Button>
          )}
        </ActionRow>
      </ActionList>
      {status.remote && (
        <Notice tone="warning">
          <span>{status.remote}</span>
        </Notice>
      )}
    </Section>
  );
}
