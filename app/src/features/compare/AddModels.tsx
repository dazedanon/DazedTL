import { useId, useState } from "react";
import { api } from "../../api/client";
import { messageOf } from "../../api/errors";
import type { Connection } from "../../api/contracts";
import { useRead } from "../../state/useRead";
import { ActionBar } from "../../ui/ActionBar";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import {
  noModelList,
  searchModels,
  typedChoice,
} from "../settings/modelSearch";
import { CompareFlag } from "./CompareGrid";
import type { ChosenModel } from "./ModelChoice";

/** Connections a comparison can send to: set up in Settings, with a key
 * or none needed. */
export const configured = (connection: Connection) =>
  !connection.needsSetup && (connection.has_secret || connection.keyless);

const key = (connection: string, model: string) =>
  JSON.stringify([connection, model]);

/** Says before a model is added when it has no price, since its estimate
 * would then fail. */
function PriceCheck({
  connection,
  model,
}: {
  connection: string;
  model: string;
}) {
  const info = useRead(key(connection, model), () =>
    api.compare.model(connection, model),
  );
  if (!info.value || info.value.priced) return null;
  return (
    <CompareFlag status="warning">
      No price for this model, so it can’t be estimated. Set its rates in
      Settings first.
    </CompareFlag>
  );
}

/**
 * Chooses models from Settings' connections: the connection first, then its
 * models, searched or typed as an ID the list lacks. Add model adds several
 * columns, up to what fits beside each other; a column's model menu chooses
 * one.
 */
export function AddModels({
  mode,
  chosen,
  room = 1,
  add,
  close,
}: {
  mode: "many" | "one";
  /** The models chosen now: kept in the list as added, or the one in use. */
  chosen: readonly ChosenModel[];
  /** How many more fit, for several. */
  room?: number;
  add: (models: ChosenModel[]) => void;
  close: () => void;
}) {
  const ids = useId();
  const settings = useRead("settings", () => api.settings());
  const connections = (settings.value?.connections ?? []).filter(configured);
  const [picked, setPicked] = useState<string>();
  const connection =
    connections.find((item) => item.id === picked) ||
    connections.find((item) => item.id === chosen[0]?.connection_id) ||
    connections.find(
      (item) => item.id === settings.value?.activeConnectionId,
    ) ||
    connections[0];
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ChosenModel[]>(() =>
    mode === "one" ? [...chosen] : [],
  );
  const models = connection?.models ?? [];
  const { typed, matches, custom } = searchModels(models, query);
  // A typed ID the list lacks comes first, and those already chosen stay.
  const extra = selected
    .filter(
      (item) =>
        item.connection_id === connection?.id &&
        !models.includes(item.model) &&
        item.model !== typed,
    )
    .map((item) => item.model);
  const rows = [...(custom ? [custom] : []), ...extra, ...matches];
  const added = (model: string) =>
    mode === "many" &&
    chosen.some(
      (item) => item.connection_id === connection?.id && item.model === model,
    );
  const isSelected = (model: string) =>
    selected.some(
      (item) => item.connection_id === connection?.id && item.model === model,
    );
  const full = mode === "many" && selected.length >= room;
  const toggle = (model: string, on: boolean) => {
    if (!connection) return;
    const choice = {
      connection_id: connection.id,
      model,
      connection: connection.name,
    };
    if (mode === "one") setSelected([choice]);
    else
      setSelected((items) =>
        on
          ? [...items, choice]
          : items.filter(
              (item) =>
                item.connection_id !== connection.id || item.model !== model,
            ),
      );
  };
  const summary =
    mode === "one"
      ? ""
      : `${selected.length} chosen · ${room} fit` +
        (full && rows.some((model) => !isSelected(model) && !added(model))
          ? " · uncheck one to choose another"
          : "");
  const title = mode === "many" ? "Add models" : "Choose a model";
  return (
    <Modal
      label={title}
      size="sm"
      className="compare-models-dialog"
      onDismiss={close}
    >
      <DialogHeader title={title} onClose={close} />
      {!settings.value ? (
        <DialogBody>
          <p className="muted" role="status">
            {settings.error ? messageOf(settings.error) : "Loading models…"}
          </p>
        </DialogBody>
      ) : !connection ? (
        <DialogBody>
          <p className="muted">
            No connection is set up yet. Add one in Settings, API connections.
          </p>
        </DialogBody>
      ) : (
        <>
          <div className="compare-models-search">
            <select
              aria-label="Connection"
              value={connection.id}
              onChange={(event) => setPicked(event.target.value)}
            >
              {connections.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <input
              type="search"
              aria-label="Search models or enter a model ID"
              placeholder={
                models.length
                  ? `Search ${models.length.toLocaleString()} ${models.length === 1 ? "model" : "models"} or enter a model ID…`
                  : "Enter a model ID…"
              }
              value={query}
              data-autofocus
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <DialogBody className="compare-models-list">
            {!models.length && !typed && (
              <p className="muted">
                {noModelList(connection.name, " in Settings")}
              </p>
            )}
            {models.length > 0 && !rows.length && (
              <p className="muted">No model matches “{typed}”.</p>
            )}
            {rows.map((model) => {
              const done = added(model);
              const on = done || isSelected(model);
              const id = `${ids}-${model}`;
              return (
                <div key={model} className="compare-model-row">
                  <input
                    id={id}
                    type={mode === "one" ? "radio" : "checkbox"}
                    name={mode === "one" ? `${ids}-model` : undefined}
                    checked={on}
                    disabled={done || (full && !on)}
                    title={
                      full && !on
                        ? `Only ${room + chosen.length} models fit side by side.`
                        : undefined
                    }
                    onChange={(event) => toggle(model, event.target.checked)}
                  />
                  <label htmlFor={id}>
                    {model === custom ? typedChoice(custom) : model}
                  </label>
                  {done && <small className="muted">Added</small>}
                  {on && !done && (
                    <PriceCheck connection={connection.id} model={model} />
                  )}
                </div>
              );
            })}
          </DialogBody>
        </>
      )}
      <ActionBar
        feedback={
          <div className="feedback" role="status">
            {summary}
          </div>
        }
      >
        <Button onClick={close}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!selected.length}
          onClick={() => {
            add(selected);
            close();
          }}
        >
          {mode === "one"
            ? "Use model"
            : selected.length
              ? `Add ${selected.length} ${selected.length === 1 ? "model" : "models"}`
              : "Add models"}
        </Button>
      </ActionBar>
    </Modal>
  );
}
