import { useEffect, useRef } from 'react';

/**
 * Like `useDebouncedCallback`, but keyed: each key gets its own independent
 * timer, so debouncing edits to one row doesn't cancel a pending save for a
 * different row (a single shared timer would silently drop the earlier
 * edit's save the moment a second key is touched within the delay window).
 */
export function usePerKeyDebounce<Args extends unknown[]>(
  callback: (key: string, ...args: Args) => void,
  delayMs: number
) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const pendingArgs = useRef(new Map<string, Args>());

  useEffect(() => {
    const timersAtMount = timers.current;
    return () => {
      for (const timeout of timersAtMount.values()) clearTimeout(timeout);
    };
  }, []);

  function schedule(key: string, ...args: Args) {
    clearTimeout(timers.current.get(key));
    pendingArgs.current.set(key, args);
    const timeout = setTimeout(() => {
      pendingArgs.current.delete(key);
      timers.current.delete(key);
      callbackRef.current(key, ...args);
    }, delayMs);
    timers.current.set(key, timeout);
  }

  /** Runs a pending call for `key` immediately, if any. No-op otherwise. */
  function flush(key: string) {
    const args = pendingArgs.current.get(key);
    if (args === undefined) return;
    clearTimeout(timers.current.get(key));
    timers.current.delete(key);
    pendingArgs.current.delete(key);
    callbackRef.current(key, ...args);
  }

  /** Runs every pending call immediately, across all keys. */
  function flushAll() {
    for (const key of [...pendingArgs.current.keys()]) flush(key);
  }

  function cancel(key: string) {
    clearTimeout(timers.current.get(key));
    timers.current.delete(key);
    pendingArgs.current.delete(key);
  }

  return { schedule, flush, flushAll, cancel };
}
