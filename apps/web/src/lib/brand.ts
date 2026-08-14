/**
 * The product name, in one place.
 *
 * Every user-visible mention of it comes from here, so a rename is this file
 * plus two other spots rather than a search across the repo:
 *
 * 1. `index.html`'s `<title>` — static HTML, read before any JS runs.
 * 2. `BRAND_NAME` in the API (`core/config.py`), for the email subjects,
 *    the `From:` address, the OpenAPI title and the SuperTokens app name.
 *
 * Deliberately NOT the source of anything a rename would break: storage keys
 * are brand-free (see `theme.ts`), because a key with the product name in it
 * silently resets everyone's saved preferences the day the name changes.
 */

export const BRAND = {
  /** As written in running text and headings. Lower-case is intentional. */
  name: "ayeayecaptain",
  /** For anywhere the domain is shown rather than linked. */
  domain: "ayeayecaptain.io",
  /** One line, used wherever the product introduces itself. */
  tagline: "Projects and tasks, on your own server.",
} as const;
