import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * The dashboard and the account screen.
 *
 * The claim only a browser can check: what one person sets on their own
 * account shows up on somebody else's landing page. That is the entire point
 * of recording an absence rather than remembering it.
 */

async function otherPerson(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signUp(page, email);
  return page;
}

async function acceptInvite(page: Page, link: string) {
  await page.goto(link);
  await page.getByRole("button", { name: /^Join / }).click();
  await page.waitForURL(/\/orgs\/[0-9a-f-]+/);
}

const today = () => new Date().toISOString().slice(0, 10);
const inDays = (n: number) =>
  new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

test.describe("the dashboard", () => {
  test("is the organisation's home, and the roster has moved", async ({ page }) => {
    await signUp(page, uniqueEmail("db"));
    const orgId = await createOrg(page, `Dash ${Date.now()}`);

    // Creating an organisation lands you here.
    await expect(page).toHaveURL(new RegExp(`/orgs/${orgId}$`));
    await expect(page.getByRole("region", { name: "Announcements" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Out of office" })).toBeVisible();

    await page.getByRole("link", { name: "People" }).click();
    await page.waitForURL(/\/people$/);
    await expect(page.getByRole("button", { name: "Invite" })).toBeVisible();
  });

  test("an announcement reaches everyone, and only admins can post", async ({
    page,
    browser,
  }) => {
    const boss = uniqueEmail("dbown");
    const crew = uniqueEmail("dbmem");
    await signUp(page, boss);
    const orgId = await createOrg(page, `Dash ${Date.now()}`);
    const link = await inviteMember(page, orgId, crew);
    const them = await otherPerson(browser, crew);
    await acceptInvite(them, link);

    await page.goto(`/orgs/${orgId}`);
    await page.getByRole("button", { name: "Announcement" }).click();
    await page.getByRole("textbox", { name: "Announcement" }).fill("Yard closed Friday");
    await page.getByText("Pin to the top").click();
    await page.getByRole("button", { name: "Post" }).click();
    await expect(page.getByText("Yard closed Friday")).toBeVisible();
    await expect(page.getByText("Pinned")).toBeVisible();

    // The member reads it and has no way to write one.
    await them.goto(`/orgs/${orgId}`);
    await expect(them.getByText("Yard closed Friday")).toBeVisible();
    await expect(them.getByRole("button", { name: "Announcement" })).toHaveCount(0);
  });

  test("an absence set on your account appears on a colleague's dashboard", async ({
    page,
    browser,
  }) => {
    const boss = uniqueEmail("dbown");
    const crew = uniqueEmail("dbmem");
    await signUp(page, boss);
    const orgId = await createOrg(page, `Dash ${Date.now()}`);
    const link = await inviteMember(page, orgId, crew);
    const them = await otherPerson(browser, crew);
    await acceptInvite(them, link);

    await them.goto("/account");
    await them.getByLabel("From").fill(today());
    await them.getByLabel("Until (included)").fill(inDays(3));
    await them.getByLabel("Why").fill("sailing");
    await them.getByRole("button", { name: "Add", exact: true }).click();
    await expect(them.getByText("Away now")).toBeVisible();

    await page.goto(`/orgs/${orgId}`);
    const away = page.getByRole("region", { name: "Out of office" });
    await expect(away.getByText(crew)).toBeVisible();
    await expect(away.getByText("sailing")).toBeVisible();
    await expect(away.getByText("Right now")).toBeVisible();

    await them.context().close();
  });

  test("a password change needs the current password", async ({ page }) => {
    await signUp(page, uniqueEmail("db"));
    await page.goto("/account");

    await page.getByLabel("Current password").fill("Wrongpass123");
    await page.getByLabel("New password").fill("Newpass4567");
    await page.getByRole("button", { name: "Change password" }).click();
    await expect(page.getByText(/isn.t your current password/)).toBeVisible();

    await page.getByLabel("Current password").fill("Testpass123");
    await page.getByRole("button", { name: "Change password" }).click();
    await expect(page.getByRole("heading", { name: "Password changed" })).toBeVisible();
  });

  test("a status line is set on your account", async ({ page }) => {
    await signUp(page, uniqueEmail("db"));
    await page.goto("/account");
    await page.getByLabel("Status").fill("Heads-down on the refit");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();

    await page.reload();
    await expect(page.getByLabel("Status")).toHaveValue("Heads-down on the refit");
  });
});

/**
 * Where each organisation's notifications are emailed.
 *
 * The HTTP suite proves the routing by reading Mailpit and checking the
 * address a real notification was delivered to. What only a browser shows is
 * the part that makes the rule legible: an empty box whose placeholder is
 * your account address, so "unset" reads as "goes to me" without a second
 * column explaining it.
 */
test.describe("email per organisation", () => {
  test("an empty box shows the account address it falls back to", async ({ page }) => {
    const email = uniqueEmail("orgmail");
    await signUp(page, email);
    await createOrg(page, `Alpha ${Date.now()}`);

    await page.goto("/account");
    const card = page.getByRole("region", { name: "Email per organisation" });
    const field = card.getByRole("textbox", { name: /^Email for Alpha/ });
    await expect(field).toHaveValue("");
    await expect(field).toHaveAttribute("placeholder", email);

    await field.fill("elsewhere@example.com");
    await field.blur();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();

    await page.reload();
    const again = page
      .getByRole("region", { name: "Email per organisation" })
      .getByRole("textbox", { name: /^Email for Alpha/ });
    await expect(again).toHaveValue("elsewhere@example.com");

    // Clearing it is how you go back — the same act, not a separate control.
    await again.fill("");
    await again.blur();
    await expect(page.getByRole("heading", { name: "Back to your account address" })).toBeVisible();
    await page.reload();
    await expect(
      page
        .getByRole("region", { name: "Email per organisation" })
        .getByRole("textbox", { name: /^Email for Alpha/ }),
    ).toHaveAttribute("placeholder", email);
  });
});
