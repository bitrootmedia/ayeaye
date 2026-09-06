import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * Triage: open tasks nobody has been asked to act on.
 *
 * `scripts/e2e-triage.sh` proves the filter and its access scoping over HTTP.
 * What only a browser can show is the thing the filter exists for — that a
 * person can work the queue without leaving the screen, and that a row really
 * does leave it once they have.
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

test.describe("Triage", () => {
  test("lists unassigned work, and assigning takes it out of the queue", async ({
    page,
    browser,
  }) => {
    await signUp(page, uniqueEmail("triage-owner"));
    // Named after nothing in particular: an organisation called "Triage …"
    // would give the org switcher that accessible name, and every
    // getByRole("button", { name: "Triage" }) below would open the switcher.
    const orgId = await createOrg(page, `Harbour ${Date.now()}`);

    const mateEmail = uniqueEmail("triage-mate");
    const link = await inviteMember(page, orgId, mateEmail);
    await acceptInvite(await otherPerson(browser, mateEmail), link);

    await createTask(page, orgId, "Order new warps");
    await createTask(page, orgId, "Book the lift-out");

    await page.goto(`/orgs/${orgId}/triage`);
    await expect(page.getByRole("link", { name: "Order new warps" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Book the lift-out" })).toBeVisible();

    // Assign one, inline, without leaving the screen.
    await page.getByRole("button", { name: "Action required for Order new warps" }).click();
    await page.getByRole("option", { name: new RegExp(mateEmail) }).click();

    // It leaves the queue — that's what the list *is*, not a cosmetic tidy-up.
    await expect(page.getByRole("link", { name: "Order new warps" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Book the lift-out" })).toBeVisible();

    // And the assignment actually landed, rather than the row merely
    // vanishing from a stale local list: it's still gone after a reload.
    await page.reload();
    await expect(page.getByRole("link", { name: "Book the lift-out" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Order new warps" })).toHaveCount(0);
  });

  test("an empty queue says so rather than looking broken", async ({ page }) => {
    await signUp(page, uniqueEmail("triage-empty"));
    const orgId = await createOrg(page, `Slipway ${Date.now()}`);
    await page.goto(`/orgs/${orgId}/triage`);
    await expect(page.getByText("Nothing to triage")).toBeVisible();
  });
});
