/**
 * Which organisation you were last looking at.
 *
 * The URL is the truth — every organisation-scoped screen carries the id, so a
 * link always lands where it says it will. This is only the tiebreaker for
 * arriving at `/` with no organisation named, so that signing in drops you back
 * where you were instead of on a list you have to click through every time.
 *
 * Brand-free key, same reasoning as `theme.ts`: a key with the product name in
 * it silently resets everyone's state the day the name changes.
 */

const KEY = "last-org";

export function rememberOrg(id: string) {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    // Private browsing, or storage full. Losing the shortcut is not worth
    // failing a render over.
  }
}

export function lastOrg(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function forgetOrg(id: string) {
  try {
    if (localStorage.getItem(KEY) === id) localStorage.removeItem(KEY);
  } catch {
    /* see above */
  }
}
