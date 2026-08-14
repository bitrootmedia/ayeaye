/**
 * Where things are.
 *
 * There is exactly one origin — the SPA, the API, the auth routes and (later)
 * object storage all sit behind it, and Caddy routes by path. Everything here
 * therefore falls back to `window.location.origin`, which means the built
 * image carries no baked-in hostname and one image runs on any domain. That is
 * what makes self-hosting a `docker compose up` rather than a rebuild.
 *
 * The `VITE_*` overrides exist only for the odd case of pointing the dev server
 * at an API somewhere else; the normal dev path goes through Caddy too, so dev
 * and production have identical cookie and CORS behaviour.
 */
export const API_DOMAIN = import.meta.env.VITE_API_DOMAIN || window.location.origin;
export const WEBSITE_DOMAIN = import.meta.env.VITE_WEBSITE_DOMAIN || window.location.origin;

/** Everything the API exposes lives under /api, auth included. */
export const API_BASE = `${API_DOMAIN}/api`;

/** Where the login, signup and password-reset screens live. */
export const AUTH_BASE_PATH = "/auth";
