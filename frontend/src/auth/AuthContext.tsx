import { createContext, useContext } from 'react';
import type { CurrentUser } from '../api/types';

export const AuthContext = createContext<CurrentUser | null>(null);

/** Current authenticated user — only ever rendered inside <RequireAuth>,
 * which resolves /auth/me before mounting its children, so a null value
 * here means "used outside RequireAuth", not "not logged in". */
export function useCurrentUser(): CurrentUser {
  const user = useContext(AuthContext);
  if (user == null) {
    throw new Error('useCurrentUser must be used within <RequireAuth>');
  }
  return user;
}
