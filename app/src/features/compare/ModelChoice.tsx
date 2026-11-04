import { useState } from "react";
import { ChevronDown, Plus, X } from "lucide-react";
import type { CompareChoice } from "../../api/contracts";
import { Button } from "../../ui/Button";
import { AddModels } from "./AddModels";
import { versusModels } from "./compareView";

/** A model on one of Settings' connections, with the connection's name. */
export type ChosenModel = CompareChoice & { connection: string };

/** The choice a comparison sends, without what only the page shows. */
export const sent = ({ connection: _name, ...choice }: ChosenModel) => choice;

/** Model vs model's models as chips, each removable, then Add model. */
export function ModelChips({
  models,
  change,
  disabled,
}: {
  models: readonly ChosenModel[];
  change: (models: ChosenModel[]) => void;
  disabled: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const room = versusModels - models.length;
  return (
    <div className="compare-setup-field" role="group" aria-label="Models">
      <span className="compare-setup-label">Models</span>
      {models.map((item) => (
        <span
          className="compare-chip"
          key={`${item.connection_id}:${item.model}`}
        >
          <span className="compare-chip-model">{item.model}</span>
          <span className="compare-connection">{item.connection}</span>
          <Button
            variant="quiet"
            className="compare-chip-remove"
            aria-label={`Remove ${item.model}`}
            title="Remove"
            disabled={disabled}
            onClick={() => change(models.filter((other) => other !== item))}
          >
            <X size={13} aria-hidden="true" />
          </Button>
        </span>
      ))}
      <Button
        variant="link"
        disabled={disabled || room <= 0}
        title={
          room <= 0
            ? `Only ${versusModels} models fit side by side.`
            : undefined
        }
        onClick={() => setAdding(true)}
      >
        <Plus size={14} aria-hidden="true" />
        Add model
      </Button>
      {adding && (
        <AddModels
          mode="many"
          chosen={models}
          room={room}
          add={(added) => change([...models, ...added])}
          close={() => setAdding(false)}
        />
      )}
    </div>
  );
}

/** Single model and Tune settings's one model, which opens the same list. */
export function ModelLink({
  model,
  change,
  disabled,
  label = "Model",
}: {
  model: ChosenModel | undefined;
  change: (model: ChosenModel) => void;
  disabled: boolean;
  /** The field's label beside the link; empty where a form labels it. */
  label?: string;
}) {
  const [choosing, setChoosing] = useState(false);
  return (
    <span className="compare-setup-field">
      {label && <span className="compare-setup-label">{label}</span>}
      <Button
        variant="link"
        className="compare-model-link"
        aria-label={
          model
            ? `${label || "Model"}: ${model.model} on ${model.connection}. Choose another`
            : "Choose a model"
        }
        disabled={disabled}
        onClick={() => setChoosing(true)}
      >
        {model ? (
          <>
            {model.model}
            <span className="compare-connection">{model.connection}</span>
          </>
        ) : (
          "Choose a model"
        )}
        <ChevronDown size={14} aria-hidden="true" />
      </Button>
      {choosing && (
        <AddModels
          mode="one"
          chosen={model ? [model] : []}
          add={([chosen]) => change(chosen)}
          close={() => setChoosing(false)}
        />
      )}
    </span>
  );
}
