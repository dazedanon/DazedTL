import { useStartEllipsis } from "./startEllipsis";

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
  const { ref, shown } = useStartEllipsis<HTMLSpanElement>(name);
  // The isolate keeps the name in reading order inside the right-to-left
  // box that moves the ellipsis to the start.
  return (
    <span
      ref={ref}
      className={`file-name ${className}`}
      data-shown={shown}
      title={title ?? name}
    >
      <bdi>{name}</bdi>
    </span>
  );
}
