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

/** A failed unmount save must remain retryable by navigation or crash recovery. */
export function retainDraft(session: { flush: () => Promise<void>; dispose: () => Promise<void> }) {
  let released = false;
  const unregister = registerLeaveGuard(async () => {
    await session.flush();
    if (released) unregister();
  });
  return async () => {
    released = true;
    await session.dispose();
    unregister();
  };
}
