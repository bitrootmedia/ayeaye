import { API_BASE } from "@/config";

/**
 * Shared fetch helper.
 *
 * The SuperTokens Session recipe patches `fetch` and attaches the session
 * automatically for API_BASE requests, so plain fetch is enough and there is
 * no token to thread through.
 *
 * There is no `X-App` header here and there shouldn't be one: this product has
 * a single surface, and what a person may do comes from their organisation
 * membership, never from which client they used.
 */
export async function api<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return (res.status === 204 ? null : await res.json()) as T;
}

/**
 * The same, but handing back the headers too.
 *
 * Only pagination needs them: `X-Total-Count` says what the page is a page
 * *of*, which is the difference between "Show more" being honest and being a
 * button that sometimes does nothing.
 */
export async function apiWithHeaders<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; headers: Headers }> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return { data: (await res.json()) as T, headers: res.headers };
}

/** Carries the status so callers can tell "not yours" (404) from "not at that
 *  level" (403) — the distinction the access model is built on. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`${status} ${body}`);
    this.name = "ApiError";
  }
}

export { API_BASE };
