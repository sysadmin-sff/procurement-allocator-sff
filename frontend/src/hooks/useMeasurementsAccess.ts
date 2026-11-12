import { useEffect, useState } from 'react';
import { measurementsApi } from '../api/measurements';

/** Whether the current user may open «Замеры» (ADR-0051 §2): admin or a grant,
 * which /auth/me does not express. Only a 200 from /measurements/access
 * counts; every failure (403, 404 when the module is off, 401, network, even
 * a synchronous throw) resolves to false here — never rethrown, never a
 * redirect, and no state update on failure, so callers stay unaffected. */
export function useMeasurementsAccess(): boolean {
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve()
      .then(() => measurementsApi.access())
      .then(
        (response) => {
          if (!cancelled && response?.access === true) setAllowed(true);
        },
        () => {
          /* hidden item is the whole reaction */
        },
      );
    return () => {
      cancelled = true;
    };
  }, []);

  return allowed;
}
