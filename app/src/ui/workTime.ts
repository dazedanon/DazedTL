/** One reading of a counted step, such as files checked, at a moment. */
export type ProgressSample = { at: number; current: number };

/** Remaining time follows the pace over this recent stretch, so a slow first
file or a change of pace soon stops skewing it. */
const WINDOW_MS = 30_000;
/** Files differ widely in how long they take, so the pace is shown only
after this long, and once a twentieth of the files are done or the pace
has been measured for a quarter minute. */
const MIN_SPAN_MS = 5_000;
const MIN_SHARE = 0.05;
const SURE_SPAN_MS = 15_000;

/**
 * Seconds a counted step still needs at its recent pace, or undefined until
 * there is enough progress to judge it.
 */
export function remainingSeconds(
  samples: readonly ProgressSample[],
  total: number,
  now: number,
) {
  const last = samples.at(-1);
  if (!last || total <= 0 || last.current >= total) return undefined;
  // The newest reading at or before the window's start anchors the pace.
  let start = samples[0];
  for (const sample of samples)
    if (sample.at <= last.at - WINDOW_MS) start = sample;
  const span = last.at - start.at;
  const done = last.current - start.current;
  if (
    span < MIN_SPAN_MS ||
    done <= 0 ||
    (last.current < total * MIN_SHARE && span < SURE_SPAN_MS)
  )
    return undefined;
  const since = Math.max(0, now - last.at);
  const files = total - last.current;
  // Within a file's usual time (span / done) the next file is under way;
  // past it, the wait so far slows the pace, so a long file never reads as
  // nearly done.
  const left =
    since * done <= span
      ? (files * span) / done - since
      : (files * (now - start.at)) / done;
  return Math.max(0, left / 1000);
}

/** The readings with a new one added, keeping only what the pace needs. */
export function addSample(
  samples: readonly ProgressSample[],
  sample: ProgressSample,
) {
  const kept = [...samples, sample];
  let start = 0;
  kept.forEach((item, index) => {
    if (item.at <= sample.at - WINDOW_MS) start = index;
  });
  return kept.slice(start);
}

/** "12 s", "4 min 5 s", "1 h 20 min": how long a finished step took. */
export function formatDuration(seconds: number) {
  const whole = Math.max(0, Math.round(seconds));
  if (whole < 60) return `${whole} s`;
  const minutes = Math.floor(whole / 60);
  if (minutes < 60) {
    const rest = whole % 60;
    return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** "0:42", "12:05", "1:02:05": time spent so far, in a steady width. */
export function formatClock(seconds: number) {
  const whole = Math.max(0, Math.floor(seconds));
  const pad = (value: number) => String(value).padStart(2, "0");
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  return hours
    ? `${hours}:${pad(minutes)}:${pad(whole % 60)}`
    : `${minutes}:${pad(whole % 60)}`;
}

/**
 * A rounded remaining time: whole minutes from two minutes up and steps of
 * five seconds below, so the figure does not flicker between readings.
 */
export function formatRemaining(seconds: number) {
  if (seconds < 10) return "A few seconds left";
  if (seconds < 100) return `About ${Math.round(seconds / 5) * 5} s left`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `About ${minutes} min left`;
  return `About ${formatDuration(minutes * 60)} left`;
}
