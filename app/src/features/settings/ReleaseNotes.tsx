import { Fragment, useState, type ReactNode } from "react";
import type { ReleaseNotes as Release } from "../../api/transport";
import { Button } from "../../ui/Button";

// Updating across many releases shows the newest few until asked for more.
const shown = 3;

/** A changelog line's **bold** and `code` spans; other text stays literal. */
function inline(text: string): ReactNode {
  return text
    .split(/(\*\*[^*]+\*\*|`[^`]+`)/)
    .map((part, index) =>
      part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? (
        <code key={index}>{part.slice(1, -1)}</code>
      ) : (
        <Fragment key={index}>{part}</Fragment>
      ),
    );
}

/** "2026-10-10" as the user's locale writes a date; a prerelease has none. */
function day(date: string) {
  const [year, month, dayOfMonth] = date.split("-").map(Number);
  return year
    ? new Date(year, month - 1, dayOfMonth).toLocaleDateString(undefined, {
        dateStyle: "long",
      })
    : "";
}

function Sections({ release }: { release: Release }) {
  return (
    <dl className="release-notes-sections">
      {release.sections.map(({ kind, items }) => (
        <div className="summary-row" key={kind}>
          <dt>{kind}</dt>
          <dd>
            <ul>
              {items.map((item, index) => (
                <li key={index}>{inline(item)}</li>
              ))}
            </ul>
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * What changed in `version`, from CHANGELOG.md. Notes spanning several
 * releases name each one, newest first.
 */
export function ReleaseNotes({
  version,
  releases,
}: {
  version: string;
  releases: Release[];
}) {
  const [all, setAll] = useState(false);
  if (!releases.length) return null;
  const single = releases.length === 1 && releases[0].version === version;
  const visible = all ? releases : releases.slice(0, shown);
  return (
    <section className="release-notes" aria-labelledby="release-notes-title">
      <h2 id="release-notes-title">
        What&apos;s new in {version}
        {single && releases[0].date && (
          <span className="release-notes-date">{day(releases[0].date)}</span>
        )}
      </h2>
      {single ? (
        <Sections release={releases[0]} />
      ) : (
        visible.map((release) => (
          <section
            className="release-notes-release"
            key={release.version}
            aria-label={release.version}
          >
            <h3>
              {release.version}
              {release.date && (
                <span className="release-notes-date">{day(release.date)}</span>
              )}
            </h3>
            <Sections release={release} />
          </section>
        ))
      )}
      {!single && releases.length > shown && (
        <Button variant="link" onClick={() => setAll((value) => !value)}>
          {all
            ? "Show fewer versions"
            : `Show ${releases.length - shown} earlier ${releases.length - shown === 1 ? "version" : "versions"}`}
        </Button>
      )}
    </section>
  );
}
