import { useEffect, useState } from "react";

/** The current time, updated each minute, so "47 min ago" stays current. */
export function useMinute() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}
