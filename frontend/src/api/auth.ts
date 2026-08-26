import { http } from './client';
import type { CurrentUser } from './types';

export const authApi = {
  me: () => http.get<CurrentUser>('/auth/me'),
  logout: () => http.post<void>('/auth/logout', undefined),
};
