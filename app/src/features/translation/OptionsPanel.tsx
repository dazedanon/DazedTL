import type {
  Project,
  TranslationOptions,
  TranslationState,
} from "../../api/contracts";
import { Button } from "../../ui/Button";
import { CheckField, CheckGroup, FieldRow } from "../../ui/FieldRow";
import { Notice } from "../../ui/Notice";
import { OptionCards, type OptionCard } from "../../ui/OptionCards";
import { GameLanguagesRow } from "../project/GameLanguages";
import { GameUpdatePanel } from "../project/GameUpdatePanel";
import { ModelMenu } from "../settings/ModelMenu";
import { qaChecksOnly, qaFocusesFor, useQaUsageNote } from "../guided/qaUsage";
import type { SettingsSection } from "../settings/Settings";

export type Mode = TranslationOptions["mode"];

export const modeLabels: Record<Mode, string> = {
  batch: "API Batch",
  live: "Live API",
  agent: "Assistant only",
};

/** Whether requests carry DazedTL's base glossary below the game's own. */
export function BaseGlossaryField({
  options,
  edit,
}: {
  options: TranslationOptions;
  edit: (key: "include_glossary_base", value: boolean) => void;
}) {
  return (
    <CheckField
      id="translation-glossary"
      label="DazedTL's base glossary"
      description="Common Japanese honorifics and interface words, added below the game's own glossary. Japanese games only."
      checked={options.include_glossary_base}
      onChange={(checked) => edit("include_glossary_base", checked)}
    />
  );
}

/**
 * Whether players get GameUpdate: Assistant-led's choice for its assistant,
 * or a Manual game's own, where `effect` says what ticking it does.
 */
export function GameUpdateField({
  state,
  checked,
  onChange,
  settings,
  effect,
}: {
  state: TranslationState;
  checked: boolean;
  onChange: (checked: boolean) => void;
  settings: (section?: SettingsSection) => void;
  effect?: string;
}) {
  const purpose = [
    "Lets players download your newest translation by running GameUpdate.",
    ...(effect ? [effect] : []),
  ].join(" ");
  return (
    <CheckField
      id="translation-gameupdate"
      label="GameUpdate"
      description={
        checked && state.gameUpdateNeedsOwner ? (
          <>
            {purpose} DazedTL sets it up once the owner of your patch
            repositories is set in Settings.{" "}
            <Button variant="link" onClick={() => settings("gameupdate")}>
              Open GameUpdate settings
            </Button>
          </>
        ) : (
          purpose
        )
      }
      checked={checked}
      onChange={onChange}
    />
  );
}

/**
 * The game's GameUpdate config below Options, once the game holds
 * GameUpdate and Settings name its owner; until then the GameUpdate choice
 * links Settings itself. Taking GameUpdate out unmounts the panel, so
 * adding it again shows no earlier notice.
 */
export function GameUpdateConfig({
  project,
  state,
  disabled,
  settings,
}: {
  project: Project;
  state: TranslationState;
  disabled: boolean;
  settings: (section?: SettingsSection) => void;
}) {
  if (["absent", "unconfigured"].includes(state.gameUpdate.state)) return null;
  return (
    <GameUpdatePanel
      key={project.id}
      projectId={project.id}
      status={state.gameUpdate}
      disabled={disabled}
      openSettings={() => settings("gameupdate")}
      releases={project.method !== "manual"}
    />
  );
}

/**
 * Who translates and pays: the user's API key in one Batch job or Live
 * requests, or, for Assistant-led (*agent*), the assistant itself.
 */
export function TranslationModeField({
  state,
  options,
  edit,
  disabled,
  settings,
  agent,
}: {
  state: TranslationState;
  options: TranslationOptions;
  edit: <K extends keyof TranslationOptions>(
    key: K,
    value: TranslationOptions[K],
  ) => void;
  disabled: boolean;
  settings: (section?: SettingsSection) => void;
  /** Whether Assistant only is offered. */
  agent: boolean;
}) {
  // Batch unless the connection cannot run it, the default new projects get.
  // `options` reads such a Batch as Live already (runnableMode), so the
  // card says why beside the choice instead; while whether it can isn't read
  // yet, Batch stays and the card says why it waits, where Live goes ahead.
  const unavailable = state.batchUnavailable;
  const recommended: Mode = unavailable ? "live" : "batch";
  const cards: OptionCard<Mode>[] = [
    {
      value: "batch",
      title: modeLabels.batch,
      badge: recommended === "batch" ? "Recommended" : undefined,
      disabled: !!unavailable,
      description:
        unavailable ||
        state.batchUnread ||
        "Your API key translates in one provider job, usually at half the Live price where the provider offers it. The job finishes on the provider's schedule, sometimes within minutes and at most within a day.",
    },
    {
      value: "live",
      title: modeLabels.live,
      badge: recommended === "live" ? "Recommended" : undefined,
      description: state.connection?.free
        ? "Your server translates one request at a time, at no cost. Translations save as each reply arrives, and you can pause between requests."
        : "Your API key sends one request at a time at the full price. Translations save as each reply arrives, and you can pause between requests.",
    },
    ...(agent
      ? [
          {
            value: "agent" as const,
            title: modeLabels.agent,
            description:
              "No API key. Your assistant translates every line itself, which uses far more of its plan; a full game can run past a $20 plan's limits.",
          },
        ]
      : []),
  ];
  return (
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
                    manage={() => settings("api")}
                  />
                </dd>
              </div>
            </dl>
          ) : (
            <Notice>
              <span>
                {agent
                  ? "No API connection yet. Your assistant prepares the game without one and asks for it before translating."
                  : "No API connection yet. Add one before you estimate the cost."}
              </span>
              <Button variant="link" onClick={() => settings("api")}>
                Add a connection
              </Button>
            </Notice>
          ))}
      </div>
    </div>
  );
}

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
  settings: (section?: SettingsSection) => void;
}) {
  return (
    <fieldset className="lens-options" disabled={disabled}>
      <p className="muted lens-options-note">
        Your assistant sets up, extracts and checks the game in one long session
        paid from its plan. On a limited plan, pick a smaller model or lower
        reasoning effort; if it stops at a limit, the same prompt picks up the
        saved work.
      </p>
      <GameLanguagesRow projectId={project.id} disabled={disabled} />
      <TranslationModeField
        state={state}
        options={options}
        edit={edit}
        disabled={disabled}
        settings={settings}
        agent
      />
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
      <CheckGroup id="translation-scope" label="Translate" stacked>
        <CheckField
          id="translation-images"
          label="Text in images"
          description="Your assistant also translates words drawn into the game's pictures, such as title screens and menu graphics."
          checked={options.include_images}
          onChange={(checked) => edit("include_images", checked)}
        />
        <BaseGlossaryField options={options} edit={edit} />
      </CheckGroup>
      {/* Your assistant installs or takes out each tool when it prepares
          the game. */}
      {(state.gameUpdateOffered || project.engine === "MVMZ") && (
        <CheckGroup id="translation-tools" label="Install in the game" stacked>
          {state.gameUpdateOffered && (
            <GameUpdateField
              state={state}
              checked={options.install_gameupdate}
              onChange={(checked) => edit("install_gameupdate", checked)}
              settings={settings}
            />
          )}
          {project.engine === "MVMZ" && (
            <>
              <CheckField
                id="translation-forge"
                label="Forge"
                description="An in-game cheat and editor menu for playtesting: switches, variables, items, gold and teleport. It ships with the translation."
                checked={options.install_forge}
                onChange={(checked) => edit("install_forge", checked)}
              />
              <CheckField
                id="translation-inspector"
                label="TL Inspector"
                description="Press its hotkey in the game to see which file and line the text on screen comes from. Stays on your computer."
                checked={options.install_tl_inspector}
                onChange={(checked) => edit("install_tl_inspector", checked)}
              />
            </>
          )}
        </CheckGroup>
      )}
      <CheckGroup id="translation-investigation" label="Investigation" stacked>
        <CheckField
          id="translation-thorough"
          label="Thorough investigation"
          description="Three passes instead of one look for names, running jokes and speech habits. Finds more, and that step uses about three times as much of your assistant's plan."
          checked={options.thorough_investigation}
          onChange={(checked) => edit("thorough_investigation", checked)}
        />
      </CheckGroup>
      <TextQaField
        projectId={project.id}
        engine={project.engine}
        value={options.text_qa}
        onChange={(value) => edit("text_qa", value)}
      />
    </fieldset>
  );
}

/**
 * What Text QA reviews after injection, as Guided's QA focus chooses, or
 * only its mechanical checks, with how much of the game the review reads.
 */
function TextQaField({
  projectId,
  engine,
  value,
  onChange,
}: {
  projectId: string;
  /** The game's engine, whose choices the select offers. */
  engine: string;
  value: TranslationOptions["text_qa"];
  onChange: (value: TranslationOptions["text_qa"]) => void;
}) {
  const usage = useQaUsageNote(projectId, value, true);
  return (
    <FieldRow
      id="translation-text-qa"
      label="Text QA"
      help={
        value === qaChecksOnly[0]
          ? usage
          : `${usage} Checks only skips the review and runs the quick mechanical checks.`
      }
    >
      {(props) => (
        <select
          {...props}
          value={value}
          onChange={(event) =>
            onChange(event.target.value as TranslationOptions["text_qa"])
          }
        >
          {[...qaFocusesFor(engine), qaChecksOnly].map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      )}
    </FieldRow>
  );
}
