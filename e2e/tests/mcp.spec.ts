import { expect, test } from "@playwright/test";

import { createOrg, signUp, uniqueEmail } from "./helpers";

/**
 * Access tokens, from the screen that makes them.
 *
 * The protocol itself is covered by `scripts/e2e-mcp.sh`, which drives the
 * endpoint as a client would. What only a browser can check is the promise
 * this screen makes: the secret appears once and is never recoverable.
 */
test.describe("access tokens", () => {
  test("the secret is shown once, and only once", async ({ page }) => {
    await signUp(page, uniqueEmail("tok"));
    await createOrg(page, `Tokens ${Date.now()}`);
    await page.goto("/account");

    const card = page.getByRole("region", { name: "Access tokens" });
    await card.getByLabel("What is it for").fill("Claude on my laptop");
    await card.getByRole("button", { name: "Create token" }).click();

    await expect(page.getByText(/won.t be shown again/)).toBeVisible();
    const secret = await page.locator("code").filter({ hasText: /^ayc_/ }).first().innerText();
    expect(secret.startsWith("ayc_")).toBe(true);

    // Gone on reload, and not recoverable from anywhere — only a hash is kept.
    await page.reload();
    await expect(page.getByText(secret)).toHaveCount(0);
    await expect(card.getByText("Claude on my laptop")).toBeVisible();
    await expect(card.getByRole("status").or(card.locator("[data-slot=badge]")).filter({ hasText: "Read only" })).toBeVisible();
  });

  test("a write token says what it can do, and revoking removes it", async ({ page }) => {
    await signUp(page, uniqueEmail("tok"));
    await createOrg(page, `Tokens ${Date.now()}`);
    await page.goto("/account");

    const card = page.getByRole("region", { name: "Access tokens" });
    await card.getByLabel("What is it for").fill("Writes things");
    await card.getByLabel("Access").selectOption("write");
    await card.getByRole("button", { name: "Create token" }).click();
    await expect(card.locator("[data-slot=badge]").filter({ hasText: "Can change things" })).toBeVisible();

    await card.getByRole("button", { name: "Revoke Writes things" }).click();
    await expect(card.getByText("Writes things")).toHaveCount(0);
  });
});
