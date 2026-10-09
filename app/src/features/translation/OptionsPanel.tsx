import type {
  Project,
  TranslationOptions,
  TranslationState,
} from "../../api/contracts";
import { Button } from "../../ui/Button";
import { CheckField, CheckGroup, FieldRow } from "../../ui/FieldRow";
import { Notice } from "../../ui/Notice";
import { OptionCards, type OptionCard } from "../../ui/OptionCards";
import { ModelMenu } from "../settings/ModelMenu";

export type Mode = TranslationOptions["mode"];

export const modeLabels: Record<Mode, string> = {
  batch: "API Batch",
  live: "Live API",
  agent: "Assistant only",
};

/**
 * How the assistant works on this game. The mode decides who pays for the
 * translation: the user's API key, or the assistant's own plan.
 */
export function OptionsPanel({
  project,
  state,
  options,
  edit,
  disabled,
  settings,
}: {
  project: Project;
  state: TranslationState;
  options: TranslationOptions;
  edit: <K extends keyof TranslationOptions>(
    key: K,
    value: TranslationOptions[K],
  ) => void;
  disabled: boolean;
  settings: () => void;
}) {
  const connected = !!state.connection?.model;
  // Batch unless the connection cannot run it, the default new projects get.
  const recommended: Mode =
    connected && !state.batchSupported ? "live" : "batch";
  const cards: OptionCard<Mode>[] = [
    {
      value: "batch",
      title: modeLabels.batch,
      badge: recommended === "batch" ? "Recommended" : undefined,
      description:
        "Your API key translates in one provider job, at half the Live price where the provider offers it. The job finishes on the provider's schedule, sometimes within minutes and at most within a day.",
    },
    {
      value: "live",
      title: modeLabels.live,
      badge: recommended === "live" ? "Recommended" : undefined,
      description:
        "Your API key sends one request at a time at the full price. Translations save as each reply arrives, and you can pause between requests.",
    },
    {
      value: "agent",
      title: modeLabels.agent,
      description:
        "No API key. Your assistant translates every line itself, which uses far more of its plan; a full game can run past a $20 plan's limits.",
    },
  ];
  return (
    <fieldset className="lens-options" disabled={disabled}>
      <p className="muted lens-options-note">
        Your assistant sets up, extracts and checks the game in one long session
        paid from its plan. On a limited plan, pick a smaller model or lower
        reasoning effort; if it stops at a limit, the same prompt picks up the
        saved work.
      </p>
      <div
        className="field-row"
        role="group"
        aria-labelledby="translation-mode-label"
      >
        <span className="field-label" id="translation-mode-label">
          Translation mode
        </span>
        <div className="field-control field-control--wide">
          <OptionCards
            label="Translation mode"
            value={options.mode}
            options={cards}
            onChange={(mode) => edit("mode", mode)}
          />
          {options.mode !== "agent" &&
            (state.connection ? (
              <dl className="translation-facts" aria-label="API connection">
                <div>
                  <dt>Connection</dt>
                  <dd>{state.connection.name}</dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd>
                    <ModelMenu
                      model={state.connection.model}
                      connection={state.connection.name}
                      disabled={disabled}
                      manage={settings}
                    />
                  </dd>
                </div>
              </dl>
            ) : (
              <Notice>
                <span>
                  No API connection yet. Your assistant prepares the game
                  without one and asks for it before translating.
                </span>
                <Button variant="link" onClick={settings}>
                  Add a connection
                </Button>
              </Notice>
            ))}
          {options.mode === "batch" && connected && !state.batchSupported && (
            <Notice tone="warning">
              This connection or model can't run Batch. Choose Live API, or a
              model that offers Batch.
            </Notice>
          )}
        </div>
      </div>
      <FieldRow
        id="translation-instructions"
        label="Instructions for your assistant"
        wide
      >
        {(props) => (
          <textarea
            {...props}
            rows={3}
            value={options.instructions}
            placeholder="Game-specific requirements, reference games, or a narrower task…"
            onChange={(event) => edit("instructions", event.target.value)}
          />
        )}
      </FieldRow>
      <CheckGroup id="translation-scope" label="Include">
        <CheckField
          id="translation-images"
          label="Image text"
          checked={options.include_images}
          onChange={(checked) => edit("include_images", checked)}
        />
        <CheckField
          id="translation-glossary"
          label="Base glossary"
          checked={options.include_glossary_base}
          onChange={(checked) => edit("include_glossary_base", checked)}
        />
      </CheckGroup>
      <CheckGroup id="translation-setup" label="Setup">
        {project.engine === "MVMZ" && (
          <CheckField
            id="translation-forge"
            label="Install Forge for playtesting"
            checked={options.install_forge}
            onChange={(checked) => edit("install_forge", checked)}
          />
        )}
        <CheckField
          id="translation-thorough"
          label="Thorough investigation"
          help="Three independent passes look for names, running jokes and speech habits instead of one. They find more, and that step uses about three times as much of your assistant's plan."
          checked={options.thorough_investigation}
          onChange={(checked) => edit("thorough_investigation", checked)}
        />
      </CheckGroup>
    </fieldset>
  );
}
