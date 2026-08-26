import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { authApi } from '../api/auth';
import type { CurrentUser } from '../api/types';
import { AuthContext } from './AuthContext';

type Status = 'loading' | 'authenticated' | 'unauthenticated';

/** Single route-level guard around the whole app tree — see ADR-0024 §7.
 * Resolves GET /auth/me once on mount; 401 redirects to /login, success
 * makes the user available to descendants via AuthContext. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');
  const [user, setUser] = useState<CurrentUser | null>(null);

  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus('authenticated');
      })
      .catch(() => {
        if (cancelled) return;
        setStatus('unauthenticated');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === 'loading') {
    return <div>Загрузка…</div>;
  }

  if (status === 'unauthenticated' || user == null) {
    return <Navigate to="/login" replace />;
  }

  return <AuthContext.Provider value={user}>{children}</AuthContext.Provider>;
}
