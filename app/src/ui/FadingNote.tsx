import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

/** How long a note reads before it fades, and each of its two steps, the fade and the fold. */
const SHOWN_MS = 6000;
const STEP_MS = 200;

/**
 * A short confirmation, such as "Report copied.", that fades out and folds
 * away by itself, so it does not linger beside its control. It stays while it
 * is pointed at or holds focus, so a link in it can be reached; mounting it
 * again shows it afresh. Failures never use it: they stay beside
 * their action.
 */
export function FadingNote({
  className,
  onGone,
  children,
}: {
  className?: string;
  onGone: () => void;
  children: ReactNode;
}) {
  const [pointed, setPointed] = useState(false);
  const [focused, setFocused] = useState(false);
  const [fading, setFading] = useState(false);
  const held = pointed || focused;
  // A caller's inline callback must not restart the timer on each render.
  const gone = useRef(onGone);
  useLayoutEffect(() => {
    gone.current = onGone;
  });
  useEffect(() => {
    if (held) return;
    const timer = window.setTimeout(
      fading ? () => gone.current() : () => setFading(true),
      fading ? 2 * STEP_MS : SHOWN_MS,
    );
    return () => window.clearTimeout(timer);
  }, [held, fading]);
  return (
    <div
      className="fading-note"
      data-fading={fading || undefined}
      style={{ "--fading-note-step": `${STEP_MS}ms` } as CSSProperties}
      // Only a pointer that moves holds it: the sidebar grows upward, so the
      // note often appears under a pointer resting where its button was.
      onPointerMove={() => {
        if (pointed) return;
        setPointed(true);
        setFading(false);
      }}
      onPointerLeave={() => setPointed(false)}
      onFocus={() => {
        setFocused(true);
        setFading(false);
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          setFocused(false);
      }}
    >
      <p className={className} role="status">
        {children}
      </p>
    </div>
  );
}
