import { useState } from "react";
import type { EngineValue, EventTextState } from "../../api/contracts";
import { ActionControl } from "../../ui/ActionControl";
import { ActionList, ActionRow } from "../../ui/ActionList";
import { Button } from "../../ui/Button";
import { FieldRow } from "../../ui/FieldRow";
import { Message } from "../../ui/Feedback";
import {
  manualSources,
  sourceErrors,
  type SelectorKey,
} from "./eventTextSelection";

export function EventTextSources({
  state,
  values,
  disabled,
  change,
  openPicker,
  recommendations,
}: {
  state: EventTextState;
  values: Record<string, EngineValue>;
  disabled: boolean;
  change: (key: string, value: EngineValue) => void;
  openPicker: (key: SelectorKey) => void;
  recommendations: () => void;
}) {
  const manual = manualSources(state, values);
  const [selected, setSelected] = useState(state.rows[0]?.key || "");
  const row = state.rows.find((item) => item.key === selected) || state.rows[0];
  return (
    <>
      <ActionList>
        <ActionRow
          label={
            <>
              <strong>
                {state.status === "ready"
                  ? "Findings ready"
                  : "Manual source choices"}
              </strong>
              <small>Review coverage before enabling sources.</small>
            </>
          }
        >
          <ActionControl
            label="Use recommendations"
            disabled={disabled || state.status !== "ready"}
            disabledReason={
              state.status !== "ready"
                ? "Available once the investigation saves findings."
                : ""
            }
            onClick={recommendations}
          />
        </ActionRow>
      </ActionList>
      {values.AUTONAMEPOPUP101 === true && (
        <p className="muted">
          Saved AutoNamePopup speaker handling also processes supported
          actor-name changes, even with source 320 off. Review that inherited
          coverage with the actor context.
        </p>
      )}
      <div className="translation-sources-grid">
        <fieldset
          disabled={disabled}
          className="translation-source-list"
          aria-label="Event and plugin sources"
        >
          {state.rows.map((item) => (
            <div
              key={item.key}
              className={`translation-source-choice${row?.key === item.key ? " selected" : ""}`}
            >
              <input
                aria-label={`Enable ${item.label}`}
                type="checkbox"
                checked={values[item.key] === true}
                onChange={(event) => change(item.key, event.target.checked)}
              />
              <button
                aria-pressed={row?.key === item.key}
                onClick={() => setSelected(item.key)}
              >
                <strong>{item.label}</strong>
                <small>
                  {manual.includes(item.key)
                    ? "Manual choice · coverage confirmation needed"
                    : state.status === "ready"
                      ? item.decision === "enable" &&
                        item.confidence === "high" &&
                        item.coverageStatus === "safe"
                        ? "Recommended"
                        : "Keep off / review needed"
                      : "Not investigated"}
                </small>
              </button>
            </div>
          ))}
        </fieldset>
        {row && (
          <section className="translation-source-detail" aria-label={row.label}>
            <h3>{row.label}</h3>
            <p className="muted">{row.reason}</p>
            <details>
              <summary>Investigation summary</summary>
              <p>{state.message}</p>
              <p>
                Recommendations are staged for review. Uncertain or mixed
                coverage stays off. Manual choices require coverage
                confirmation.
              </p>
            </details>
            {row.key === "CODE122" && (
              <FieldRow id="event-text-variable-ids" label="Variable IDs">
                {(props) => (
                  <input
                    {...props}
                    type="text"
                    value={String(values.CODE122_VAR_RANGES || "")}
                    disabled={disabled || !values.CODE122}
                    onChange={(event) =>
                      change("CODE122_VAR_RANGES", event.target.value)
                    }
                    placeholder="35, 37-40, 402"
                  />
                )}
              </FieldRow>
            )}
            {row.selector && (
              <ActionList>
                <ActionRow
                  label={
                    <>
                      <strong>
                        {row.key === "CODE357"
                          ? "MZ plugin command filters"
                          : "Script text filters"}
                      </strong>
                      <small>
                        {Array.isArray(values[row.selector])
                          ? (values[row.selector] as string[]).length
                          : 0}{" "}
                        of {row.choices.length} registered entries selected
                        {!values[row.key] && " (source off)"}.{" "}
                        {state.builtinHits[row.key]?.length || 0} built-in
                        handlers detected in this scope.
                      </small>
                    </>
                  }
                >
                  <Button
                    disabled={disabled}
                    onClick={() => openPicker(row.selector as SelectorKey)}
                  >
                    Edit selection
                  </Button>
                </ActionRow>
              </ActionList>
            )}
            <details>
              <summary>Coverage, exclusions & evidence</summary>
              <p>{row.coverage}</p>
              {!!row.builtins.length && (
                <p>
                  Built-in coverage when enabled: {row.builtins.join(", ")}.
                  These have no individual switches.
                </p>
              )}
              {!!row.observations.length && (
                <ul>
                  {row.observations.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              )}
              {!!row.exclusions.length && (
                <>
                  <strong>Excluded or unsupported work</strong>
                  <ul>
                    {row.exclusions.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                  <p>
                    Listed exclusions are evidence. If they share enabled
                    handler coverage, the engine cannot isolate them; keep that
                    coverage off or review an explicit manual override.
                  </p>
                </>
              )}
              {!!row.evidence.length && (
                <ul>
                  {row.evidence.map((ref, index) => (
                    <li key={index}>
                      <span className="path">{ref.file}</span> - {ref.location}
                    </li>
                  ))}
                </ul>
              )}
            </details>
          </section>
        )}
      </div>
      {sourceErrors(state, values).map((error) => (
        <Message key={error} message={error} />
      ))}
    </>
  );
}
