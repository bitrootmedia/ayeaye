import { expect, test } from "@playwright/test";

import { signUp, uniqueEmail } from "./helpers";

/**
 * The one public screen. Three things about it can break, and two of them
 * break *quietly*.
 */
test.describe("the landing page", () => {
  test("a stranger at the root gets a way in, not a login wall", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "on your own server",
    );

    // The account CTA has to land on the sign-up tab, not on sign-in with a
    // link to find. `?show=signup` is SuperTokens' own query parameter, so
    // this also catches them changing it in an upgrade.
    await page.getByRole("link", { name: "Create an account" }).click();
    await page.waitForURL(/\/auth\?show=signup/);
    await expect(page.getByText("Sign Up", { exact: true }).first()).toBeVisible();
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
});
