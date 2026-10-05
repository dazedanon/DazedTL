const guards = new Set<() => Promise<void>>();
export function registerLeaveGuard(guard: () => Promise<void>) {
  guards.add(guard);
  return () => {
    guards.delete(guard);
  };
}
export async function flushDrafts() {
  // Guards can unregister themselves while saving, so iterate a snapshot.
  for (const guard of Array.from(guards)) await guard();
}

/** A failed unmount save must remain retryable by navigation or crash recovery. */
export function retainDraft(session: {
  flush: () => Promise<void>;
  dispose: () => Promise<void>;
}) {
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
