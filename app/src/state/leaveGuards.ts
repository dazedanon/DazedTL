const guards = new Set<() => Promise<void>>();
export function registerLeaveGuard(guard: () => Promise<void>) {
  guards.add(guard);
  return () => {
    guards.delete(guard);
  };
}
export async function flushDrafts() {
  for (const guard of [...guards]) await guard();
}
