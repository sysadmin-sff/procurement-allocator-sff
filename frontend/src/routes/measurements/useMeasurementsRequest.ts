import { useCallback, useEffect, useRef, useState } from 'react';

export type RequestState<T> =
  | { status: 'loading'; data: T | null; dataKey: string | null; error: null }
  | { status: 'ready'; data: T; dataKey: string; error: null }
  | { status: 'error'; data: null; dataKey: null; error: unknown };

/** Loads `load()` whenever `key` changes (the serialized query). A response for
 * an outdated key is dropped, so a quick filter change cannot show stale
 * numbers. `data` of the previous key is kept while loading — the screen keeps
 * the last measurer list and filters visible. `dataKey` names the key `data`
 * belongs to: right after a key change `data` is still the previous one. */
export function useMeasurementsRequest<T>(key: string, load: () => Promise<T>) {
  const [state, setState] = useState<RequestState<T>>({
    status: 'loading',
    data: null,
    dataKey: null,
    error: null,
  });
  const [attempt, setAttempt] = useState(0);
  // `load` is rebuilt every render; `key` is what identifies the request.
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ status: 'loading', data: prev.data, dataKey: prev.dataKey, error: null }));
    Promise.resolve()
      .then(() => loadRef.current())
      .then(
        (data) => {
          if (!cancelled) setState({ status: 'ready', data, dataKey: key, error: null });
        },
        (error: unknown) => {
          if (!cancelled) setState({ status: 'error', data: null, dataKey: null, error });
        },
      );
    return () => {
      cancelled = true;
    };
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, reload };
}
