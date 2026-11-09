import { useState } from "react";
import { api } from "../../api/client";
import type { Project, TranslationFileImport } from "../../api/contracts";
import { useApplication } from "../../app/ApplicationProvider";
import { useAction } from "../../state/useAction";
import { ActionBar } from "../../ui/ActionBar";
import { ActionControl } from "../../ui/ActionControl";
import { Button } from "../../ui/Button";
import { DialogBody, DialogHeader } from "../../ui/Dialog";
import { Modal } from "../../ui/Modal";
import { PageBody } from "../../ui/PageLayout";
import { PathText } from "../../ui/PathText";
import { Section } from "../../ui/Section";
import { StatusIcon } from "../../ui/StatusIcon";
import { plural } from "../../ui/displayText";

/** The name a game's exported file is offered under. */
export const exportName = (project: Project) =>
  `${project.name} translation.json`;

/**
 * Saves a project's translation file where the user chooses and says what it
 * holds, or nothing when the user cancels.
 */
export async function exportTranslation(project: Project) {
  const path = await window.dazedtl.saveTranslationFile(exportName(project));
  if (!path) return "";
  const saved = await api.translation.exportFile(project.id, path);
  const csv = saved.path.toLowerCase().endsWith(".csv");
  const translated =
    saved.lines && saved.translated === saved.lines
      ? "all"
      : saved.translated.toLocaleString();
  return `Saved ${plural(saved.lines, "line")} as ${csv ? "CSV" : "JSON"}, ${translated} translated${
    saved.glossary ? `, with ${plural(saved.glossary, "glossary term")}` : ""
  }.`;
}

/**
 * The Project page's Export/Import tab: the project's translation file, every
 * line with its translation, exported to edit or share, and a file's
 * translations imported back onto the same lines once the user has reviewed
 * what the import changes. Each result sits beside its button, so it never
 * changes a section's height.
 */
export function ExportImport({
  project,
  disabled,
}: {
  project: Project;
  disabled: boolean;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const [preview, setPreview] = useState<{
    path: string;
    value: TranslationFileImport;
  } | null>(null);
  const choose = () =>
    action.run(
      async () => {
        const path = await window.dazedtl.chooseTranslationFile();
        if (!path) return;
        setPreview({
          path,
          value: await api.translation.previewFile(project.id, path),
        });
      },
      "",
      "import",
    );
  return (
    <>
      <PageBody className="project-exchange">
        <Section title="Export">
          <p>
            Every line with its translation, and the game's glossary, as JSON or
            CSV to edit in your own tools or share.
          </p>
          <ActionControl
            inline
            label="Export…"
            disabled={disabled || action.busy}
            pending={action.busy && action.key === "export"}
            pendingText="Exporting…"
            error={action.key === "export" ? action.error : ""}
            notice={action.key === "export" ? action.notice : ""}
            onClick={async () => {
              const done = await action.run(
                () => exportTranslation(project),
                "",
                "export",
              );
              if (done.ok && done.value) action.succeed(done.value, "export");
            }}
          />
        </Section>
        <Section title="Import">
          <p>
            Take a JSON or CSV file's translations onto the same lines. You
            review what changes before anything is saved.
          </p>
          <ActionControl
            inline
            label="Import…"
            disabled={disabled || action.busy}
            pending={action.busy && action.key === "import"}
            pendingText="Checking…"
            error={action.key === "import" ? action.error : ""}
            notice={action.key === "import" ? action.notice : ""}
            onClick={() => void choose()}
          />
        </Section>
      </PageBody>
      <ActionBar feedback={null}>{null}</ActionBar>
      {preview && (
        <ImportReview
          project={project}
          path={preview.path}
          value={preview.value}
          close={() => setPreview(null)}
          imported={(message) => {
            setPreview(null);
            action.succeed(message, "import");
          }}
        />
      )}
    </>
  );
}

/** What an import changes, counted (translation_file.matched). */
export function ImportSummary({
  value,
  project,
}: {
  value: TranslationFileImport;
  project: Project;
}) {
  // Each count with its verb for one or for more.
  const rows = [
    [value.added, "line", "gets a translation", "get a translation"],
    [
      value.replaced,
      "line",
      "replaces the translation it has",
      "replace the translation they have",
    ],
    [
      value.unchanged,
      "line",
      "has this translation already",
      "have this translation already",
    ],
    [
      value.empty,
      "line",
      "has no translation in the file",
      "have no translation in the file",
    ],
    [
      value.glossary.added,
      "glossary term",
      "joins the game's glossary",
      "join the game's glossary",
    ],
    [
      value.glossary.differs,
      "glossary term",
      "differs from the game's glossary, which keeps its own",
      "differ from the game's glossary, which keeps its own",
    ],
  ] as const;
  const skipped = value.unknown + value.changed + value.refused;
  return (
    <div className="translation-import">
      <ul className="translation-import-counts">
        {rows
          .filter(([amount]) => amount > 0)
          .map(([amount, noun, one, many]) => (
            <li key={many}>
              <strong>{plural(amount, noun)}</strong>{" "}
              {amount === 1 ? one : many}
            </li>
          ))}
        {skipped > 0 && (
          <li className="translation-import-warning">
            <StatusIcon status="warning" size={14} />
            <span>
              <strong>{plural(skipped, "line")}</strong>{" "}
              {skipped === 1 ? "is" : "are"} skipped
              {value.skipped.length < skipped &&
                `, the first ${value.skipped.length} listed below`}
            </span>
          </li>
        )}
      </ul>
      {value.skipped.length > 0 && (
        <ul className="translation-import-skipped" aria-label="Skipped lines">
          {value.skipped.map((row) => (
            <li key={row.id}>
              <code>{row.id}</code>
              <span>{row.reason}</span>
            </li>
          ))}
        </ul>
      )}
      {project.method === "guided" && value.added + value.replaced > 0 && (
        <p className="muted">
          The translations go into your working copies. Apply them to the game
          in Translate.
        </p>
      )}
    </div>
  );
}

function ImportReview({
  project,
  path,
  value,
  close,
  imported,
}: {
  project: Project;
  path: string;
  value: TranslationFileImport;
  close: () => void;
  imported: (message: string) => void;
}) {
  const application = useApplication();
  const action = useAction({ observer: application });
  const lines = value.added + value.replaced;
  const terms = value.glossary.added;
  return (
    <Modal
      label="Import translations"
      size="md"
      dismissible={!action.busy}
      onDismiss={close}
    >
      <DialogHeader
        title="Import translations?"
        description={<PathText path={path} />}
      />
      <DialogBody>
        <ImportSummary value={value} project={project} />
      </DialogBody>
      <ActionBar feedback={null}>
        <Button disabled={action.busy} onClick={close}>
          Cancel
        </Button>
        <ActionControl
          variant="primary"
          label={
            lines
              ? `Import ${plural(lines, "translation")}`
              : terms
                ? `Import ${plural(terms, "glossary term")}`
                : "Nothing to import"
          }
          disabled={action.busy || !(lines || terms)}
          pending={action.busy}
          pendingText="Importing…"
          error={action.error}
          onClick={() =>
            void action.run(async () => {
              await api.translation.importFile(project.id, path, value.sha256);
              imported(
                `Imported ${[
                  lines && plural(lines, "translation"),
                  terms && plural(terms, "glossary term"),
                ]
                  .filter(Boolean)
                  .join(" and ")}.`,
              );
            })
          }
        />
      </ActionBar>
    </Modal>
  );
}
