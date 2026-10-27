import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * Work reports, as two people see them: an admin gets the screen, a member
 * gets neither the link nor the data. The arithmetic is proved without a
 * browser in `test_work_report_rules.py` and `scripts/e2e-work-reports.sh`.
 */

async function otherPerson(browser: Browser, email: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signUp(page, email);
  return page;
}

async function acceptInvite(page: Page, link: string) {
  await page.goto(link);
  await page.getByRole("button", { name: /^Join / }).click();
  await page.waitForURL(/\/orgs\/[0-9a-f-]+/);
}

test("an admin sees who is on what; a member is not offered it", async ({ page, browser }) => {
  const member = uniqueEmail("wrm");
  await signUp(page, uniqueEmail("wro"));
  const orgId = await createOrg(page, `Yard ${Date.now()}`);
  const link = await inviteMember(page, orgId, member);
  const them = await otherPerson(browser, member);
  await acceptInvite(them, link);

  await createTask(page, orgId, "Caulk the deck");
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: /Caulk the deck/ }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
  await page.getByLabel("Log time already spent").fill("1h15");
  await page.getByRole("button", { name: "Log", exact: true }).click();
  await expect(page.getByText("1h 15m").first()).toBeVisible();
  await page.getByRole("button", { name: "Start work" }).click();
  await expect(page.getByRole("status", { name: "Running timer" })).toBeVisible();

  // The owner: the rail offers it, and "Right now" names the running task.
  await page.getByRole("link", { name: "Work reports" }).click();
  await page.waitForURL(/\/reports$/);
  const now = page.getByRole("table").first();
  await expect(now.getByRole("link", { name: "Caulk the deck" })).toBeVisible();
  await expect(page.getByText("1h 15m").first()).toBeVisible();

  // The member: no link in the rail, and a direct URL says why.
  await them.goto(`/orgs/${orgId}`);
  await expect(them.getByRole("link", { name: "Work reports" })).toHaveCount(0);
  await them.goto(`/orgs/${orgId}/reports`);
  await expect(them.getByText("For organisation admins")).toBeVisible();
  await expect(them.getByText("Caulk the deck")).toHaveCount(0);

  await page.getByRole("button", { name: "Stop the running timer" }).click();
  await them.context().close();
});
