import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

import { signUp, uniqueEmail } from "./helpers";

/** The operator's own front door, set the only way it can be set: from a
 *  shell on the box, or from the panel. Same shape `instance.spec.ts` uses to
 *  grant itself the panel — the CLI and the routes are one service. */
const instance = (...args: string[]) =>
  execFileSync(path.resolve(process.cwd(), "../scripts/instance.sh"), args, { stdio: "pipe" });

/**
 * The one public screen, and most of what can break about it breaks
 * *quietly*: a pitch served in place of a permission boundary, a dead end at
 * `/auth`, a Create account button still on screen after an operator closed
 * the door.
 */
test.describe("the landing page", () => {
  test("a stranger at the root gets a way in, not a login wall", async ({ page }) => {
    await page.goto("/");

    // The default heading is the product's own name. An operator can replace
    // it (see the last test in this file), which is why this asserts the
    // fallback rather than any particular sentence.
    await expect(page.getByRole("heading", { level: 1 })).toContainText("AyeAyeCaptain");

    // The account CTA has to land on the sign-up tab, not on sign-in with a
    // link to find. `?show=signup` is SuperTokens' own query parameter, so
    // this also catches them changing it in an upgrade.
    await page.getByRole("link", { name: "Create an account" }).click();
    await page.waitForURL(/\/auth\?show=signup/);
    await expect(page.getByText("Sign Up", { exact: true }).first()).toBeVisible();
  });

  test("the auth screens carry the header and footer home", async ({ page }) => {
    // Those screens are SuperTokens' own routes, not nested under Root — see
    // AuthChrome in main.tsx. Without it /auth was a dead end: no rail, no
    // link back to "/", nothing but the browser's own Back button.
    await page.goto("/auth");
    await page.getByText("Sign In", { exact: true }).first().waitFor();

    await page.getByRole("link", { name: "AyeAyeCaptain" }).first().click();
    await page.waitForURL("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("AyeAyeCaptain");
  });

  test("a deep link while signed out still asks you to sign in", async ({ page }) => {
    // The load-bearing one. `Root` stands in front of every child route, so
    // getting its pathname test wrong would serve the landing page to someone
    // following a link into the app — losing the link they arrived on, and
    // looking like marketing rather than a permission boundary.
    await page.goto("/orgs/00000000-0000-0000-0000-000000000000/tasks");

    await page.waitForURL(/\/auth/);
    // And it remembers where they were going.
    expect(decodeURIComponent(page.url())).toContain("redirectToPath=/orgs/");
  });

  test("signed in, the root is the app", async ({ page }) => {
    await signUp(page, uniqueEmail("land"));
    await page.goto("/");

    await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
    // Not the shell *and* the pitch — the landing page must not render behind
    // or beside it.
    await expect(page.getByRole("link", { name: "Create an account" })).toHaveCount(0);
  });

  test("the operator's own front door: a heading, and a closed door", async ({ page }) => {
    // Both of these are what makes this page a self-hoster's rather than
    // ours, and neither is visible to any other layer: the HTTP suite proves
    // the server refuses a sign-up, and only a browser can say whether the
    // button that would start one is still on the screen.
    instance("headline", "Ops, at Acme");
    instance("close-signups");
    try {
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toContainText("Ops, at Acme");
      await expect(page.getByText("invitation only")).toBeVisible();
      // All three of them — the hero's, the header's and the footer's.
      await expect(page.getByRole("link", { name: /Create an? account/ })).toHaveCount(0);
      // Signing in is never the thing that gets closed.
      await expect(page.getByRole("link", { name: "Sign in" }).first()).toBeVisible();
    } finally {
      // Installation-wide state, so it is put back even if an assertion
      // above fails — otherwise one red test closes registration for every
      // suite that runs after it.
      instance("open-signups");
      instance("headline");
    }

    await page.goto("/");
    await expect(page.getByRole("link", { name: "Create an account" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("AyeAyeCaptain");
  });
});
