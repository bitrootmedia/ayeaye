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
 *
 * **There is no `tagline` any more, and that is a product decision.** The
 * front door's heading is the operator's to write — `instance_settings`,
 * editable from the panel and from `scripts/instance.sh headline` — and this
 * name is only what it falls back to. A tagline shipped in the bundle is one
 * every self-hosted installation is stuck with, and "Just another take on
 * the to-do app" was it.
 */

export const BRAND = {
  /** As written in running text and headings. */
  name: "AyeAyeCaptain",
  /** For anywhere the domain is shown rather than linked. */
  domain: "ayeayecaptain.io",
} as const;
