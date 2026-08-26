import { diff, http } from './client';
import type { User, UserCreate } from './types';

export const usersApi = {
  list: () => http.get<User[]>('/users'),
  create: (payload: UserCreate) => http.post<User>('/users', payload),
  /** Sends only fields changed between `before` and `after` (PATCH-via-PUT semantics). */
  update: (id: string, before: User, after: User) =>
    http.patch<User>(`/users/${id}`, diff(before, after)),
};
