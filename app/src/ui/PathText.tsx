import { homeRelative } from "./displayPath";
import { useStartEllipsis } from "./startEllipsis";

/**
 * A read-only path shown home-relative, keeping its end in view when it is
 * shortened. Hovering shows the full path, and copying it copies the full
 * path rather than the shortened text.
 */
export function PathText({
  path,
  wrap = false,
  className = "",
}: {
  path: string;
  /** Wraps in running text instead of shortening, for reviews that confirm a destination. */
  wrap?: boolean;
  className?: string;
}) {
  const text = homeRelative(path);
  const { ref, shown } = useStartEllipsis<HTMLSpanElement>(text, !wrap);
  return (
    <span
      ref={ref}
      className={`path-text${wrap ? " path-text--wrap" : ""} ${className}`}
      data-shown={shown}
      title={path}
      onCopy={(event) => {
        const selection = document.getSelection();
        const box = event.currentTarget;
        if (
          !selection ||
          !box.contains(selection.anchorNode) ||
          !box.contains(selection.focusNode)
        )
          return;
        event.preventDefault();
        event.clipboardData.setData("text/plain", path);
      }}
    >
      {/* The isolate keeps the path in reading order inside the
          right-to-left box that moves the ellipsis to the start. */}
      <bdi>
        {wrap
          ? text.split(/(?<=[/\\])/).map((part, index) => (
              // A wrapped path breaks between its folders, never inside a
              // name such as a date stamp.
              <span key={index} className="path-text-part">
                {part}
                <wbr />
              </span>
            ))
          : text}
      </bdi>
    </span>
  );
}
