const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export class ApiError extends Error {
  status: number;
  detail: unknown;
  /** Full parsed response body — detail is just its .detail field (or the
   * whole body, if that field is absent), kept for ErrorBanner's existing
   * string-message use. Structured 4xx bodies (e.g. ADR-0012's 409 conflict
   * payload) need the rest of the body too, hence keeping both. */
  body: unknown;

  constructor(status: number, body: unknown) {
    const detail =
      body != null && typeof body === 'object' && 'detail' in body
        ? (body as { detail: unknown }).detail
        : body;
    super(typeof detail === 'string' ? detail : `Request failed with status ${status}`);
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => undefined);
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const http = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

/**
 * Shallow diff between two objects, one level deep on plain-object values
 * (e.g. delivery_policy) so PUT payloads only carry fields the user actually
 * changed. Backend PATCH-semantics relies on unset fields being absent, not
 * present-as-unchanged — see CLAUDE.md and update_supplier/update_material.
 */
export function diff<T extends object>(before: T, after: T): Partial<T> {
  const changes: Partial<T> = {};

  for (const key of Object.keys(after) as (keyof T)[]) {
    const beforeValue = before[key];
    const afterValue = after[key];

    if (isPlainObject(beforeValue) && isPlainObject(afterValue)) {
      const nested = diff(beforeValue, afterValue);
      if (Object.keys(nested).length > 0) {
        changes[key] = { ...beforeValue, ...nested };
      }
      continue;
    }

    if (!Object.is(beforeValue, afterValue)) {
      changes[key] = afterValue;
    }
  }

  return changes;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
