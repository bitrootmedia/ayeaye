/**
 * Remembered view toggles — board vs list, cards vs table.
 *
 * The URL stays the source of truth for a specific visit (so a link somebody
 * sends carries the view they meant, the same reasoning every other
 * URL-persisted filter in this product already follows) — this is only the
 * *default* for the next time you arrive with no `?view=` in the address bar
 * at all. Set only on an explicit toggle click, not on landing via a shared
 * link: following someone else's table-view link once shouldn't silently
 * become your own permanent default.
 *
 * Deliberately brand-free key, the same reasoning `lib/theme.ts` gives for
 * its own: a key with the product name in it resets everyone's saved
 * preference the day the name changes.
 */

const PREFIX = "view-";

export function rememberView(name: string, view: string): void {
  try {
    localStorage.setItem(PREFIX + name, view);
  } catch {
    // Storage unavailable (private browsing). Losing the shortcut isn't
    // worth failing anything over — the URL default still works.
  }
}

export function lastView(name: string): string | null {
  try {
    return localStorage.getItem(PREFIX + name);
  } catch {
    return null;
  }
}
