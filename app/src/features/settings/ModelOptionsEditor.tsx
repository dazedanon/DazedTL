import type { Connection, ModelOptions, Settings } from "../../api/contracts";
import { Section } from "../../ui/Section";
import { FieldRow } from "../../ui/FieldRow";
import { Button } from "../../ui/Button";
import { useModelDefaults } from "./useModelDefaults";

const automatic: ModelOptions = {
  entriesPerRequest: null,
  batchInputTokens: null,
  pricing: "automatic",
  inputRate: null,
  outputRate: null,
};
const amount = (value: number) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(value);

export default function ModelOptionsEditor({
  config,
  connection,
  edit,
}: {
  config: Settings;
  connection?: Connection;
  edit: (model: string, value: ModelOptions) => void;
}) {
  const model = config.values.model.trim();
  const defaults = useModelDefaults(
    config.activeConnectionId,
    model,
    connection?.check.checkedAt,
    connection?.openrouter_host,
  );
  const openrouter = connection?.provider === "openrouter";
  const value = {
    ...automatic,
    ...(Object.hasOwn(config.modelOptions, model)
      ? config.modelOptions[model]
      : {}),
  };
  const change = (patch: Partial<ModelOptions>) =>
    edit(model, { ...value, ...patch });
  if (!model)
    return (
      <p className="settings-note">
        Choose a model to see its request and pricing options.
      </p>
    );
  const resolved = defaults.value;
  const catalogDate = resolved?.updatedAt
    ? new Date(resolved.updatedAt).toLocaleDateString()
    : "";
  const source =
    resolved?.source === "catalog"
      ? `${openrouter && connection?.openrouter_host ? "Selected host" : "Model catalog"}${resolved.stale ? " (outdated cache)" : ""}${catalogDate ? ` · ${catalogDate}` : ""}`
      : "Built-in engine rates";
  return (
    <>
      <p className="settings-note model-options-scope">
        {connection
          ? `Saved for ${model} on ${connection.name}.`
          : `Saved for the ${model} estimate model.`}
      </p>
      <Section title="Requests">
        <FieldRow
          id="request-size-mode"
          label="Entries per request"
          help="Use fewer entries for less capable models, or more if your model handles them reliably."
        >
          {(control) => (
            <select
              {...control}
              value={value.entriesPerRequest === null ? "default" : "custom"}
              onChange={(event) =>
                change({
                  entriesPerRequest:
                    event.target.value === "default"
                      ? null
                      : config.defaultEntriesPerRequest,
                })
              }
            >
              <option value="default">
                Default ({config.defaultEntriesPerRequest})
              </option>
              <option value="custom">Custom</option>
            </select>
          )}
        </FieldRow>
        {value.entriesPerRequest !== null && (
          <FieldRow id="request-size-custom" label="Custom entry limit">
            {(control) => (
              <input
                {...control}
                className="short-control"
                type="number"
                min={1}
                max={100}
                step={1}
                required
                value={value.entriesPerRequest ?? ""}
                onChange={(event) =>
                  change({
                    entriesPerRequest:
                      event.target.value === ""
                        ? ""
                        : Number(event.target.value),
                  })
                }
              />
            )}
          </FieldRow>
        )}
        <FieldRow
          id="output-token-allowance"
          label="Output token allowance"
          help="Maximum generated tokens per request, including reasoning. Lower model or host limits take precedence. Blank uses the default. Applies to new runs."
        >
          {(control) => (
            <input
              {...control}
              className="short-control"
              type="number"
              min={1}
              max={Number.MAX_SAFE_INTEGER}
              step={1}
              placeholder={
                config.defaultOutputTokens == null
                  ? "Default"
                  : `Default (${Math.min(config.defaultOutputTokens, resolved?.maxOutputTokens ?? config.defaultOutputTokens).toLocaleString()})`
              }
              value={value.maxOutputTokens ?? ""}
              onPaste={(event) => {
                const pasted = event.clipboardData.getData("text").trim();
                if (!/^\d{1,3}(?:[,\u00a0\u202f ]\d{3})+$/.test(pasted)) return;
                event.preventDefault();
                change({
                  maxOutputTokens: Number(pasted.replace(/[,\s]/g, "")),
                });
              }}
              onChange={(event) =>
                change({
                  maxOutputTokens:
                    event.target.value === ""
                      ? null
                      : Number(event.target.value),
                })
              }
            />
          )}
        </FieldRow>
        {connection?.provider === "openai" && (
          <FieldRow
            id="batch-input-tokens"
            label="Batch token allowance"
            help="Total estimated input tokens across active Guided Batches on this connection and model. Available capacity is filled automatically. Leave headroom for other jobs sharing the account. Applies to new runs."
          >
            {(control) => (
              <input
                {...control}
                className="short-control"
                type="number"
                min={1}
                max={Number.MAX_SAFE_INTEGER}
                step={1}
                placeholder={
                  config.defaultBatchInputTokens == null
                    ? "Default"
                    : `Default (${config.defaultBatchInputTokens.toLocaleString()})`
                }
                value={value.batchInputTokens ?? ""}
                onPaste={(event) => {
                  const pasted = event.clipboardData.getData("text").trim();
                  if (!/^\d{1,3}(?:[,\u00a0\u202f ]\d{3})+$/.test(pasted))
                    return;
                  event.preventDefault();
                  change({
                    batchInputTokens: Number(pasted.replace(/[,\s]/g, "")),
                  });
                }}
                onChange={(event) =>
                  change({
                    batchInputTokens:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  })
                }
              />
            )}
          </FieldRow>
        )}
      </Section>
      <Section title="Pricing" hint="USD per million tokens">
        <FieldRow id="pricing-mode" label="Estimate rates">
          {(control) => (
            <select
              {...control}
              value={value.pricing}
              onChange={(event) =>
                change({
                  pricing: event.target.value as ModelOptions["pricing"],
                  inputRate: value.inputRate ?? resolved?.inputRate ?? null,
                  outputRate: value.outputRate ?? resolved?.outputRate ?? null,
                })
              }
            >
              <option value="automatic">Automatic</option>
              <option value="custom">Custom rates</option>
            </select>
          )}
        </FieldRow>
        {value.pricing === "custom" ? (
          <>
            <div className="paired-settings custom-rates">
              {(["inputRate", "outputRate"] as const).map((key) => (
                <FieldRow
                  key={key}
                  id={key}
                  label={
                    key === "inputRate"
                      ? openrouter
                        ? "Live input"
                        : "Input"
                      : openrouter
                        ? "Live output"
                        : "Output"
                  }
                >
                  {(control) => (
                    <input
                      {...control}
                      className="short-control"
                      type="number"
                      min={0}
                      max={1000000}
                      step="0.000001"
                      required
                      value={value[key] ?? ""}
                      onChange={(event) =>
                        change({
                          [key]:
                            event.target.value === ""
                              ? ""
                              : Number(event.target.value),
                        })
                      }
                    />
                  )}
                </FieldRow>
              ))}
            </div>
            <p className="settings-note">
              Custom rates override catalog and engine rates. Use 0 for a free
              model.
            </p>
          </>
        ) : (
          resolved && (
            <div className="effective-rates" role="status">
              {resolved.inputRate !== null && resolved.outputRate !== null ? (
                <>
                  <span>
                    {openrouter ? "Live input" : "Input"}{" "}
                    <strong>${amount(resolved.inputRate)}</strong>
                  </span>
                  <span>
                    {openrouter ? "Live output" : "Output"}{" "}
                    <strong>${amount(resolved.outputRate)}</strong>
                  </span>
                  <small>{source}</small>
                </>
              ) : (
                <p>
                  {openrouter
                    ? "Check the connection to load OpenRouter prices, or enter custom Live rates."
                    : "No rates are available for this model. Enter custom rates before estimating or translating."}
                </p>
              )}
            </div>
          )
        )}
        <p className="settings-note">
          {openrouter
            ? "Live rates apply to names and labels translated before a Batch. Actual charges depend on the serving host and account settings."
            : "Base rates before cache and batch adjustments. Custom servers may charge different rates."}
        </p>
      </Section>
      {openrouter && (
        <Section title="Batch pricing" hint="USD per million tokens">
          {resolved && !resolved.batchSupported && (
            <p className="settings-note">{resolved.batchReason}</p>
          )}
          <FieldRow id="batch-pricing-mode" label="Batch estimate rates">
            {(control) => (
              <select
                {...control}
                value={value.batchPricing ?? "automatic"}
                onChange={(event) =>
                  change({
                    batchPricing: event.target.value as "automatic" | "custom",
                    batchInputRate:
                      value.batchInputRate ?? resolved?.batchInputRate ?? null,
                    batchOutputRate:
                      value.batchOutputRate ??
                      resolved?.batchOutputRate ??
                      null,
                  })
                }
              >
                <option value="automatic">Automatic</option>
                <option value="custom">Custom rates</option>
              </select>
            )}
          </FieldRow>
          {value.batchPricing === "custom" ? (
            <div className="paired-settings custom-rates">
              {(["batchInputRate", "batchOutputRate"] as const).map((key) => (
                <FieldRow
                  key={key}
                  id={key}
                  label={
                    key === "batchInputRate" ? "Batch input" : "Batch output"
                  }
                >
                  {(control) => (
                    <input
                      {...control}
                      className="short-control"
                      type="number"
                      min={0}
                      max={1000000}
                      step="0.000001"
                      required
                      value={value[key] ?? ""}
                      onChange={(event) =>
                        change({
                          [key]:
                            event.target.value === ""
                              ? ""
                              : Number(event.target.value),
                        })
                      }
                    />
                  )}
                </FieldRow>
              ))}
            </div>
          ) : (
            resolved?.batchSupported && (
              <div className="effective-rates" role="status">
                {resolved.batchInputRate != null &&
                resolved.batchOutputRate != null ? (
                  <>
                    <span>
                      Batch input{" "}
                      <strong>${amount(resolved.batchInputRate)}</strong>
                    </span>
                    <span>
                      Batch output{" "}
                      <strong>${amount(resolved.batchOutputRate)}</strong>
                    </span>
                  </>
                ) : (
                  <p>
                    Batch prices are unavailable. Enter both custom Batch rates
                    before submitting.
                  </p>
                )}
              </div>
            )
          )}
          <p className="settings-note">
            These are the Batch rates; no additional 50% discount is applied.
            Custom prices do not enable an unsupported model or host.
          </p>
        </Section>
      )}
      {defaults.loading && (
        <p className="settings-note" role="status">
          Loading model defaults…
        </p>
      )}
      {defaults.error && (
        <div className="model-defaults-error" role="alert">
          <span>{defaults.error}</span>
          <Button onClick={defaults.retry}>Try again</Button>
        </div>
      )}
    </>
  );
}
