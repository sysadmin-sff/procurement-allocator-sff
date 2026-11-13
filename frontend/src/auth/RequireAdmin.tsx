import { Navigate } from 'react-router-dom';
import { useCurrentUser } from './AuthContext';

/** Route guard for admin-only screens (ADR-0055): an employee who opens
 * /prices, /categories or /users by URL lands on the
 * projects list instead of an error banner. UI convenience only — the
 * backend routers enforce the same rule (require_role("admin")). */
export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const user = useCurrentUser();
  if (user.role !== 'admin') {
    return <Navigate to="/projects" replace />;
  }
  return <>{children}</>;
}
