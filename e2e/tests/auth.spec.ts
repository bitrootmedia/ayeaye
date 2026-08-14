import { expect, test } from "@playwright/test";

import { PASSWORD, signIn, signOut, signUp, uniqueEmail } from "./helpers";

test.describe("accounts", () => {
  test("sign up, sign out, sign back in", async ({ page }) => {
    const email = uniqueEmail("auth");
    await signUp(page, email);

    // The rail shows who you are, which is also proof `GET /me` created the
    // local user row rather than the shell rendering on a session alone.
    await expect(page.getByText(email)).toBeVisible();

    await signOut(page);
    await signIn(page, email);
    await expect(page.getByText(email)).toBeVisible();
  });

  test("a wrong password is refused", async ({ page }) => {
    const email = uniqueEmail("auth");
    await signUp(page, email);
    await signOut(page);

    await page.goto("/auth");
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill("Wrongpass123");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByText(/incorrect email and password/i)).toBeVisible();
    // Still on the auth screen, not half-way into the app.
    await expect(page).toHaveURL(/\/auth/);
  });

  test("signing in returns you to the organisation you were last in", async ({ page }) => {
    // The reason `lastOrg()` exists. Without it, every session starts on a
    // chooser you have to click through.
    const email = uniqueEmail("auth");
    await signUp(page, email);
    await page.getByRole("button", { name: "New organisation" }).first().click();
    await page.getByLabel("Name").fill("Recall test");
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.waitForURL(/\/orgs\/[0-9a-f-]+$/);
    const orgId = page.url().split("/orgs/")[1];

    await signOut(page);
    await signIn(page, email);
    await expect(page).toHaveURL(new RegExp(`/orgs/${orgId}`));
  });

  test("the password reset page is reachable without a session", async ({ page }) => {
    // A reset link arrives by email and is opened by someone who is, by
    // definition, locked out. It must not be behind the session gate, and the
    // SPA fallback has to serve the deep path.
    await page.goto("/auth/reset-password");
    await expect(page.getByText(/password/i).first()).toBeVisible();
  });

  test("forgot password accepts an address and says so", async ({ page }) => {
    const email = uniqueEmail("auth");
    await signUp(page, email);
    await signOut(page);

    await page.goto("/auth");
    await page.getByText(/forgot password/i).click();
    // Wait for the form to swap in — filling before it does silently writes
    // into the old one and submits an empty field.
    await expect(page.getByText("Reset your password", { exact: true })).toBeVisible();
    // Typed rather than filled, and asserted: this form re-mounts as it
    // animates in, and a `fill` that lands mid-swap is silently discarded —
    // the request then goes out with an empty field.
    const field = page.locator('input[name="email"]');
    await field.click();
    await field.pressSequentially(email);
    await expect(field).toHaveValue(email);
    await page.getByRole("button", { name: /email me/i }).click();
    await expect(page.getByText(/check your email|sent/i).first()).toBeVisible();
  });

  test("the password field is not readable on screen", async ({ page }) => {
    await page.goto("/auth");
    await expect(page.locator('input[name="password"]')).toHaveAttribute("type", "password");
    expect(PASSWORD.length).toBeGreaterThan(7);
  });
});
