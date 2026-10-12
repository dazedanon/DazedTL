import { Fragment, useState, type ReactNode } from "react";
import type { ReleaseNotes as Release } from "../../api/transport";
import { Button } from "../../ui/Button";

// The changelog shows a few versions at a time, from the newest.
const page = 5;

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

/** One version's notes, under its version and date. */
function Version({ release }: { release: Release }) {
  return (
    <section className="release-notes-release" aria-label={release.version}>
      <h3>
        {release.version}
        {release.date && (
          <span className="release-notes-date">{day(release.date)}</span>
        )}
      </h3>
      <Sections release={release} />
    </section>
  );
}

/**
 * Every release CHANGELOG.md lists, newest first and a page at a time: the
 * `recent` ones as what's new, in one release or since `since`, then the
 * earlier ones.
 */
export function ReleaseNotes({
  since,
  releases,
  recent,
}: {
  since: string;
  releases: Release[];
  recent: number;
}) {
  const [count, setCount] = useState(page);
  if (!releases.length) return null;
  const visible = releases.slice(0, count);
  const fresh = visible.slice(0, recent);
  const earlier = visible.slice(recent);
  const more = Math.min(page, releases.length - count);
  return (
    <div className="release-notes">
      {fresh.length > 0 && (
        <section
          className="release-notes-group"
          aria-labelledby="release-notes-new"
        >
          <h2 id="release-notes-new">
            {recent === 1
              ? `What's new in ${fresh[0].version}`
              : `What's new since ${since}`}
            {recent === 1 && fresh[0].date && (
              <span className="release-notes-date">{day(fresh[0].date)}</span>
            )}
          </h2>
          {recent === 1 ? (
            <Sections release={fresh[0]} />
          ) : (
            fresh.map((release) => (
              <Version key={release.version} release={release} />
            ))
          )}
        </section>
      )}
      {earlier.length > 0 && (
        <section
          className="release-notes-group"
          aria-labelledby="release-notes-earlier"
        >
          <h2 id="release-notes-earlier">Earlier versions</h2>
          {earlier.map((release) => (
            <Version key={release.version} release={release} />
          ))}
        </section>
      )}
      {more > 0 && (
        <Button variant="link" onClick={() => setCount(count + page)}>
          {`Show ${more} earlier ${more === 1 ? "version" : "versions"}`}
        </Button>
      )}
    </div>
  );
}
