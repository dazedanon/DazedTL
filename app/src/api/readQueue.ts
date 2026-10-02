/** Bound outstanding reads and discard obsolete queued work before transport. */
export function readQueue(limit: number) {
  let active = 0;
  const waiting: (() => void)[] = [];
  const pump = () => { while (active < limit && waiting.length) waiting.shift()!(); };
  return <T>(task: () => Promise<T>, current: () => boolean = () => true): Promise<T> => new Promise((resolve, reject) => {
    waiting.push(() => {
      if (!current()) { reject(new Error("Read canceled.")); pump(); return; }
      active++;
      void task().then(resolve, reject).finally(() => { active--; pump(); });
    });
    pump();
  });
}
