import { useEffect, useRef } from 'react';

export interface DebouncedCallback<Args extends unknown[]> {
  (...args: Args): void;
  /**
   * If a call is pending, runs it immediately (with its pending args) and
   * clears the timer. No-op if nothing is pending. Use before any action
   * that depends on the debounced write having actually happened — e.g. a
   * "Calculate" button must not just wait for in-flight requests, it must
   * also force out whatever edit is still sitting in the debounce window.
   */
  flush: () => void;
  /** Cancels a pending call without running it. */
  cancel: () => void;
}

/**
 * Returns a stable debounced wrapper around `callback`. Each call resets the
 * timer; the wrapped function only fires `delayMs` after the last call. Uses
 * a ref for the callback so the debounced function always sees the latest
 * closure without needing `callback` in a dependency array.
 */
export function useDebouncedCallback<Args extends unknown[]>(
  callback: (...args: Args) => void,
  delayMs: number
): DebouncedCallback<Args> {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pendingArgsRef = useRef<Args | null>(null);

  useEffect(() => {
    return () => clearTimeout(timeoutRef.current);
  }, []);

  const debounced = ((...args: Args) => {
    clearTimeout(timeoutRef.current);
    pendingArgsRef.current = args;
    timeoutRef.current = setTimeout(() => {
      pendingArgsRef.current = null;
      callbackRef.current(...args);
    }, delayMs);
  }) as DebouncedCallback<Args>;

  debounced.flush = () => {
    if (pendingArgsRef.current === null) return;
    clearTimeout(timeoutRef.current);
    const args = pendingArgsRef.current;
    pendingArgsRef.current = null;
    callbackRef.current(...args);
  };

  debounced.cancel = () => {
    clearTimeout(timeoutRef.current);
    pendingArgsRef.current = null;
  };

  return debounced;
}
