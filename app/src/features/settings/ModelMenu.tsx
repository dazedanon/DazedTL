import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type { Settings } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { Feedback } from "../../ui/Feedback";
import { Menu, MenuItem, MenuSearch, MenuSeparator } from "../../ui/Menu";
import { settingsSaved } from "./settingsChanges";

/**
 * Changes the active connection's model in place, so changing models mid-task
 * does not mean leaving the task. The list comes from the connection's last
 * check, and a typed model ID is accepted for models it does not list.
 */
export function ModelMenu({
  model,
  connection,
  disabled = false,
  manage,
}: {
  model: string;
  connection: string;
  disabled?: boolean;
  /** Opens Settings; absent when the menu already sits there. */
  manage?: () => void;
}) {
  const application = useApplication();
  const action = useAction({ after: application.settle });
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState("");
  const [query, setQuery] = useState("");
  const load = () => {
    setLoadError("");
    setQuery("");
    api
      .settings()
      .then(setSettings, (error: unknown) => setLoadError(messageOf(error)));
  };
  const active = settings?.connections.find(
    (item) => item.id === settings.activeConnectionId,
  );
  const models = active?.models ?? [];
  const typed = query.trim();
  const matches = models.filter((item) =>
    item.toLocaleLowerCase().includes(typed.toLocaleLowerCase()),
  );
  // Pending Settings edits stay theirs; the menu never overwrites them.
  const pending = !!settings?.draft;
  const choose = (next: string) =>
    void action.run(
      async () => {
        const current = await api.settings();
        if (current.draft)
          throw new Error(
            "Save or discard your Settings changes before switching models.",
          );
        await api.saveSettings({
          ...current,
          values: { ...current.values, model: next },
        });
        settingsSaved();
      },
      "",
      "model",
    );
  return (
    <>
      <Menu
        variant="link"
        label="Translation model"
        align="start"
        title={`${connection} · choose a model`}
        disabled={disabled || action.busy}
        onOpen={load}
        trigger={
          <>
            {model || "Choose a model"}
            <ChevronDown size={14} aria-hidden="true" />
          </>
        }
      >
        {!settings ? (
          <p className="menu-note" role="status">
            {loadError || "Loading models…"}
          </p>
        ) : pending ? (
          <p className="menu-note">
            Settings has unsaved changes. Save or discard them to switch models
            here.
          </p>
        ) : (
          <>
            {/* The search doubles as entry for a model ID the list lacks. */}
            <MenuSearch
              label="Search or enter a model ID"
              placeholder="Search or enter a model ID…"
              value={query}
              onChange={setQuery}
              // Enter takes the one match, or the typed ID when nothing
              // matches; with several matches, arrows choose among them.
              onSubmit={
                models.includes(typed) || matches.length === 1
                  ? () => choose(models.includes(typed) ? typed : matches[0])
                  : !matches.length
                    ? () => choose(typed)
                    : undefined
              }
            />
            {matches.map((item) => (
              <MenuItem
                key={item}
                current={item === model}
                onSelect={() => choose(item)}
              >
                {item}
              </MenuItem>
            ))}
            {!!typed && !models.includes(typed) && (
              <MenuItem onSelect={() => choose(typed)}>Use “{typed}”</MenuItem>
            )}
            {!models.length && !typed && (
              <p className="menu-note">
                No model list for {active?.name || "this connection"} yet. Check
                the connection to load one, or enter a model ID.
              </p>
            )}
          </>
        )}
        {manage && (
          <>
            <MenuSeparator />
            <MenuItem onSelect={manage}>Manage connections…</MenuItem>
          </>
        )}
      </Menu>
      {action.key === "model" && (
        <Feedback
          loading={action.busy}
          loadingText="Switching model…"
          notice="Saved as your default model"
          error={action.error}
        />
      )}
    </>
  );
}
