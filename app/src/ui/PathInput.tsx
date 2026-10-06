import { useLayoutEffect, useRef, type ComponentProps } from "react";

/**
 * A path field that shows the end of a long path, where the folder or file
 * name is, whenever the reader is not editing it.
 */
export function PathInput(props: ComponentProps<"input">) {
  const input = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => {
    const element = input.current;
    if (element && document.activeElement !== element)
      element.scrollLeft = element.scrollWidth;
  }, [props.value]);
  return (
    <input
      {...props}
      ref={input}
      onBlur={(event) => {
        event.currentTarget.scrollLeft = event.currentTarget.scrollWidth;
        props.onBlur?.(event);
      }}
    />
  );
}
