import type { DocumentDrafts, Documents } from "../api/contracts";
import { documentNames, documentStatus } from "../state/documentState";
import { HelpPopover } from "./HelpPopover";
import { Notice } from "./Notice";
import { StatusIcon } from "./StatusIcon";
import { Tabs } from "./Tabs";

/**
 * The guidance documents' editor, the same in every method: a tab for each
 * document but the custom skills, which a select picks; beside each, its
 * file, or its description, and where it stands; then its text, or why
 * DazedTL can't read its file.
 */
export function DocumentEditor({
  documents,
  drafts,
  disabled,
  edit,
  selectedName,
  select,
  placeholders,
  formats,
}: {
  documents: Documents;
  drafts: DocumentDrafts;
  disabled: boolean;
  edit: (name: string, text: string, revision: string) => void;
  selectedName: string;
  select: (name: string) => void;
  /** What each empty document shows, such as the layout its file takes. */
  placeholders?: Record<string, string>;
  /** Help on the format of a document's file, beside its path. */
  formats?: Record<string, string>;
}) {
  const names = documentNames(documents, drafts);
  const name = names.includes(selectedName)
    ? selectedName
    : names[0] || selectedName;
  const document = documents[name];
  const draft = drafts[name];
  const status = documentStatus(document, draft);
  const warning = (key: string) =>
    ["unreadable", "changed"].includes(
      documentStatus(documents[key], drafts[key]),
    );
  const custom = names.filter((key) => documents[key]?.kind === "custom");
  const tabs = names.filter(
    (key) => documents[key]?.kind !== "custom" || key === name,
  );
  return (
    <fieldset
      disabled={disabled}
      className="document-editor document-editor--focused document-editor--fill"
    >
      {tabs.length > 1 && (
        <Tabs
          id="guidance-documents"
          label="Guidance documents"
          value={name}
          items={tabs.map((key) => ({
            id: key,
            label: (
              <>
                {documents[key]?.kind === "custom"
                  ? "Custom"
                  : documents[key]?.title || key}
                {drafts[key] && <span className="badge">Draft</span>}
              </>
            ),
            status: warning(key) ? (
              <StatusIcon
                status="warning"
                label={
                  documentStatus(documents[key], drafts[key]) === "changed"
                    ? "Changed on disk"
                    : "Can't read"
                }
              />
            ) : undefined,
          }))}
          onChange={select}
          disabled={disabled}
        />
      )}
      {document && (
        <div
          className="document-editor-content"
          role={tabs.length > 1 ? "tabpanel" : undefined}
          id={`guidance-documents-panel-${name}`}
          aria-labelledby={
            tabs.length > 1 ? `guidance-documents-tab-${name}` : undefined
          }
        >
          <div className="document-editor-state">
            {document.description ? (
              <span className="document-editor-note muted">
                {document.description}{" "}
                <HelpPopover label={document.title}>
                  {document.help}
                </HelpPopover>
              </span>
            ) : (
              <span className="document-editor-file">
                <span className="path">{document.file}</span>
                {formats?.[name] && (
                  <HelpPopover label={`${document.title} format`}>
                    {formats[name]}
                  </HelpPopover>
                )}
              </span>
            )}
            <span
              className={
                warning(name)
                  ? "document-editor-status document-editor-status--warning"
                  : "document-editor-status muted"
              }
            >
              {warning(name) && <StatusIcon status="warning" />}
              {status === "unreadable"
                ? "Can't read"
                : status === "changed"
                  ? "Changed on disk since your draft"
                  : status === "draft"
                    ? "Unsaved edits"
                    : status === "saved"
                      ? "Saved"
                      : document.kind === "core"
                        ? "Not saved yet"
                        : "None yet"}
            </span>
            {!!custom.length && (
              <select
                aria-label="Custom guidance"
                value={document.kind === "custom" ? name : ""}
                onChange={(event) => select(event.target.value)}
              >
                <option value="" disabled>
                  Custom guidance…
                </option>
                {custom.map((key) => (
                  <option key={key} value={key}>
                    {documents[key].title}
                  </option>
                ))}
              </select>
            )}
          </div>
          {status === "unreadable" ? (
            <>
              <Notice tone="warning">
                <span>
                  {document.reason}
                  {draft ? " Until then your draft stays here, read-only." : ""}
                </span>
              </Notice>
              {draft && (
                <textarea
                  aria-label={`${document.title} draft`}
                  rows={4}
                  spellCheck={false}
                  readOnly
                  value={draft.text}
                />
              )}
            </>
          ) : (
            <textarea
              aria-label={`${document.title} text`}
              rows={4}
              spellCheck={false}
              placeholder={placeholders?.[name]}
              value={(draft || document).text}
              onChange={(event) =>
                edit(name, event.target.value, (draft || document).revision)
              }
            />
          )}
        </div>
      )}
    </fieldset>
  );
}
