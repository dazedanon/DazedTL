/**
 * A file name that keeps its end visible when shortened: names in one folder
 * usually share a prefix and differ in their last words or numbers, so the
 * cut falls at the start.
 */
export function FileName({
  name,
  className = "",
  title,
}: {
  name: string;
  className?: string;
  title?: string;
}) {
  // The isolate keeps the name in reading order inside the right-to-left
  // box that moves the ellipsis to the start.
  return (
    <span className={`file-name ${className}`} title={title ?? name}>
      <bdi>{name}</bdi>
    </span>
  );
}
