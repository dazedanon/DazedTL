import { useState } from "react";

/**
 * Calls `onChange` during render when `value` changes. React applies state
 * updates made here before the screen updates, unlike resets in an effect.
 */
export function useOnChange<T>(
  value: T,
  onChange: (value: T, previous: T) => void,
) {
  const [previous, setPrevious] = useState(value);
  if (!Object.is(previous, value)) {
    setPrevious(value);
    onChange(value, previous);
  }
}
