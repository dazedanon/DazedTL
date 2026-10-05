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
  const defaults = useModelDefaults(config.activeConnectionId, model);
  const value = { ...automatic, ...(Object.hasOwn(config.modelOptions, model) ? config.modelOptions[model] : {}) };
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
      ? `Model catalog${resolved.stale ? " (outdated cache)" : ""}${catalogDate ? ` · ${catalogDate}` : ""}`
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
        {connection?.provider === "openai" && <FieldRow
          id="batch-input-tokens"
          label="Batch token allowance"
          help="Total estimated input tokens across active Guided Batches on this connection and model. Available capacity is filled automatically. Leave headroom for other jobs sharing the account. Applies to new runs."
        >
          {(control) => <input {...control} className="short-control" type="number" min={1} max={Number.MAX_SAFE_INTEGER} step={1}
            placeholder={config.defaultBatchInputTokens == null ? "Default" : `Default (${config.defaultBatchInputTokens.toLocaleString()})`} value={value.batchInputTokens ?? ""}
            onPaste={event => {
              const pasted = event.clipboardData.getData("text").trim();
              if (!/^\d{1,3}(?:[,\u00a0\u202f ]\d{3})+$/.test(pasted)) return;
              event.preventDefault();
              change({ batchInputTokens: Number(pasted.replace(/[,\s]/g, "")) });
            }}
            onChange={event => change({ batchInputTokens: event.target.value === "" ? null : Number(event.target.value) })} />}
        </FieldRow>}
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
                  label={key === "inputRate" ? "Input" : "Output"}
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
                    Input <strong>${amount(resolved.inputRate)}</strong>
                  </span>
                  <span>
                    Output <strong>${amount(resolved.outputRate)}</strong>
                  </span>
                  <small>{source}</small>
                </>
              ) : (
                <p>
                  No rates are available for this model. Enter custom rates
                  before estimating or translating.
                </p>
              )}
            </div>
          )
        )}
        <p className="settings-note">
          Base rates before cache and batch adjustments. Custom servers may
          charge different rates.
        </p>
      </Section>
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
