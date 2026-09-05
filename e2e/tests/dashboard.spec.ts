import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, inviteMember, shellIsUp, signUp, uniqueEmail } from "./helpers";

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
  /**
   * Where each organisation's notifications are emailed.
   *
   * The HTTP suite proves the routing by reading Mailpit and checking the
   * address a real notification was delivered to. What only a browser shows
   * is the part that makes the rule legible: an empty box whose placeholder
   * is your account address, so "unset" reads as "goes to me" without a
   * second column explaining it — and, once the confirmation step exists, a
   * pending address that is visibly *not* the one in use.
   */
  test("an empty box shows the account address it falls back to", async ({ page }) => {
    const email = uniqueEmail("orgmail");
    await signUp(page, email);
    await createOrg(page, `Alpha ${Date.now()}`);

    await page.goto("/account");
    await shellIsUp(page);
    const card = page.getByRole("region", { name: "Email per organisation" });
    await expect(card).toBeVisible({ timeout: 15_000 });
    const field = card.getByRole("textbox", { name: /^Email for Alpha/ });
    await expect(field).toHaveValue("");
    await expect(field).toHaveAttribute("placeholder", email);

    // Waits for the request, not the toast: a toast is transient by design,
    // and racing one is how this was flaky in the full suite while passing
    // alone. What is worth asserting is that the PUT happened.
    await field.fill("elsewhere@example.com");
    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes("/me/notification-emails/") && r.request().method() === "PUT",
      ),
      field.blur(),
    ]);

    // **Asked for, not in use.** The box still holds the confirmed value —
    // nothing — and the waiting line says why. Getting this wrong would tell
    // somebody their mail had moved when it hadn't.
    await expect(card.getByText(/Waiting on elsewhere@example.com/)).toBeVisible();
    await expect(field).toHaveValue("");
    await expect(field).toHaveAttribute("placeholder", email);

    // Clearing it drops the pending request too — one act, not two.
    await field.fill("");
    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes("/me/notification-emails/") && r.request().method() === "PUT",
      ),
      field.blur(),
    ]);
    await expect(card.getByText(/Waiting on/)).toHaveCount(0);
  });

  /**
   * The confirmation handshake, end to end, including the link.
   *
   * The HTTP suite proves the token rules. This proves the two screens
   * either side of the email actually join up.
   */
  test("the link in the email switches it over", async ({ page, request }) => {
    const account = uniqueEmail("conf");
    await signUp(page, account);
    await createOrg(page, `Alpha ${Date.now()}`);
    const alias = uniqueEmail("alias");

    await page.goto("/account");
    await shellIsUp(page);
    const card = page.getByRole("region", { name: "Email per organisation" });
    await expect(card).toBeVisible({ timeout: 15_000 });
    const field = card.getByRole("textbox", { name: /^Email for Alpha/ });
    await field.fill(alias);
    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes("/me/notification-emails/") && r.request().method() === "PUT",
      ),
      field.blur(),
    ]);
    await expect(card.getByText(new RegExp(`Waiting on ${alias}`))).toBeVisible();

    // The link, out of Mailpit, opened in this browser. A real one would be
    // opened in whichever browser reads that inbox — which is exactly why
    // the page behind it needs no session.
    let token = "";
    for (let i = 0; i < 25 && !token; i++) {
      const res = await request.get("http://localhost:8025/api/v1/messages?limit=30");
      const data = (await res.json()) as {
        messages: { ID: string; Subject: string; To: { Address: string }[] }[];
      };
      for (const m of data.messages) {
        if (m.To[0]?.Address !== alias || !m.Subject.includes("Confirm this address")) continue;
        const full = (await (
          await request.get(`http://localhost:8025/api/v1/message/${m.ID}`)
        ).json()) as { Text: string };
        const word = full.Text.split(/\s+/).find((w) => w.includes("/notification-email/"));
        if (word) token = word.split("/").pop()!;
        break;
      }
      if (!token) await page.waitForTimeout(1000);
    }
    expect(token).not.toEqual("");

    await page.goto(`/notification-email/${token}`);
    await expect(page.getByText("Address confirmed")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(alias)).toBeVisible();

    await page.goto("/account");
    // The shell first: this is a full page load after navigating away from
    // the app, and the account screen is one of the heaviest. Asserting on
    // the card before the shell exists is racing the whole bundle.
    await shellIsUp(page);
    const after = page.getByRole("region", { name: "Email per organisation" });
    await expect(after).toBeVisible({ timeout: 15_000 });
    await expect(after.getByRole("textbox", { name: /^Email for Alpha/ })).toHaveValue(alias, {
      timeout: 15_000,
    });
    await expect(after.getByText(/Waiting on/)).toHaveCount(0);
  });
});
