import { expect, test } from "@playwright/test";

import { signUp, uniqueEmail } from "./helpers";

/**
 * The auth screens are somebody else's markup, restyled with our tokens
 * through a shadow root. Both halves of that are fragile in ways nothing else
 * would catch: a SuperTokens upgrade can rename a `data-supertokens` hook, and
 * the theme only reaches the shadow DOM because custom properties inherit
 * through it.
 */
test.describe("the auth screens wear the product's clothes", () => {
  test("the primary button uses the product's primary colour", async ({ page }) => {
    await page.goto("/auth?show=signup");
    await page.getByText("Sign Up", { exact: true }).first().waitFor();

    const { button, appPrimary } = await page.evaluate(() => {
      const root = (document.querySelector("#supertokens-root") as HTMLElement & {
        shadowRoot: ShadowRoot;
      }).shadowRoot;
      const btn = root.querySelector('[data-supertokens~="button"]')!;
      return {
        button: getComputedStyle(btn).backgroundColor,
        // What the rest of the product would paint with.
        appPrimary: getComputedStyle(document.documentElement).getPropertyValue("--primary").trim(),
      };
    });

    // Not a hard-coded hex on either side: the assertion is that the auth
    // button resolves to the *same* token everything else uses, so a palette
    // change can't leave this screen behind.
    expect(button).toContain("oklch");
    expect(button.replace(/\s+/g, "")).toBe(appPrimary.replace(/\s+/g, ""));
  });

  test("it follows dark mode, chosen while signed in", async ({ page }) => {
    // The failure this prevents: someone who works in dark mode signs out and
    // gets a full-brightness page. `useTheme` only runs inside the shell, so
    // the saved preference has to be applied before React mounts.
    await signUp(page, uniqueEmail("th"));
    await page.getByRole("button", { name: "Dark" }).click();
    await expect(page.getByRole("button", { name: "Light" })).toBeVisible();

    // Sign out rather than navigating to /auth: an authenticated visit gets
    // redirected straight back into the app, and signing out is the actual
    // moment this used to go wrong.
    await page.getByRole("button", { name: "Log out" }).click();
    await page.waitForURL(/\/auth/);
    await page.getByText("Sign In", { exact: true }).first().waitFor();

    const dark = await page.evaluate(() =>
      document.documentElement.classList.contains("dark"),
    );
    expect(dark).toBe(true);
  });

  test("the SuperTokens styling hooks still exist", async ({ page }) => {
    // A canary for the upgrade that renames one of these: the screen would
    // quietly revert to stock rather than break, which is exactly the kind of
    // regression nobody notices.
    await page.goto("/auth?show=signup");
    await page.getByText("Sign Up", { exact: true }).first().waitFor();

    const found = await page.evaluate(() => {
      const root = (document.querySelector("#supertokens-root") as HTMLElement & {
        shadowRoot: ShadowRoot;
      }).shadowRoot;
      return ["container", "headerTitle", "input", "button", "inputWrapper", "link"].filter(
        (hook) => root.querySelector(`[data-supertokens~="${hook}"]`),
      );
    });
    expect(found).toEqual(["container", "headerTitle", "input", "button", "inputWrapper", "link"]);
  });
});
