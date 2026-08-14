import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * Hiding a task, from the other person's side.
 *
 * `scripts/e2e-hidden.sh` proves the API returns 404. That and a screen that
 * renders an absent task are different claims, and only the second is what
 * someone actually experiences — which is the whole reason this suite exists.
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

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

test.describe("a hidden task", () => {
  test("disappears for an organisation admin, and comes back", async ({ page, browser }) => {
    // Bob owns the task; Alice is the organisation's owner. She is the one who
    // must stop seeing it — that's the deliberate hole in "an admin can do
    // anything", and it is only observable between two accounts.
    const alice = uniqueEmail("hidown");
    const bob = uniqueEmail("hidmem");
    await signUp(page, alice);
    const orgId = await createOrg(page, `Hidden ${Date.now()}`);
    const link = await inviteMember(page, orgId, bob);
    const them = await otherPerson(browser, bob);
    await acceptInvite(them, link);

    await createTask(them, orgId, "Quiet work");

    // Alice can see it to begin with — she administers the organisation.
    await page.goto(`/orgs/${orgId}/tasks`);
    await expect(page.getByText("Quiet work")).toBeVisible();
    const taskUrl = await them.url();

    await openTask(them, orgId, "Quiet work");
    await them.getByRole("button", { name: "Hide from everyone else" }).click();
    await expect(them.getByRole("heading", { name: "Hidden", exact: true })).toBeVisible();
    await expect(them.getByText("Only you.")).toBeVisible();

    // Gone from her board…
    await page.goto(`/orgs/${orgId}/tasks`);
    await expect(page.getByText("Quiet work")).toHaveCount(0);
    // …and gone from search, which is a different query.
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByRole("textbox", { name: "Search" }).pressSequentially("Quiet");
    await page.waitForTimeout(700);
    await expect(page.getByRole("dialog").getByText("Quiet work")).toHaveCount(0);
    await page.keyboard.press("Escape");

    // Bob still has it, marked.
    await them.goto(`/orgs/${orgId}/tasks`);
    await expect(them.getByText("Quiet work")).toBeVisible();
    await expect(them.getByLabel("Hidden from everyone else").first()).toBeVisible();

    // And un-hiding gives it back without anything being re-shared.
    await openTask(them, orgId, "Quiet work");
    await them.getByRole("button", { name: "Make it visible again" }).click();
    await expect(them.getByRole("heading", { name: "Visible again" })).toBeVisible();
    await page.goto(`/orgs/${orgId}/tasks`);
    await expect(page.getByText("Quiet work")).toBeVisible();

    expect(taskUrl).toBeTruthy();
    await them.context().close();
  });

  test("following a direct link to one reads as no access", async ({ page, browser }) => {
    const alice = uniqueEmail("hidown");
    const bob = uniqueEmail("hidmem");
    await signUp(page, alice);
    const orgId = await createOrg(page, `Hidden ${Date.now()}`);
    const link = await inviteMember(page, orgId, bob);
    const them = await otherPerson(browser, bob);
    await acceptInvite(them, link);

    await createTask(them, orgId, "Secret survey");
    await openTask(them, orgId, "Secret survey");
    const url = them.url();
    await them.getByRole("button", { name: "Hide from everyone else" }).click();
    await expect(them.getByText("Only you.")).toBeVisible();

    // The URL is guessable and someone may have had it open. It must read as
    // "not for you", never as an error, and never leak the title.
    await page.goto(url);
    await expect(page.getByText(/don.t have access to this task/)).toBeVisible();
    await expect(page.getByText("Secret survey")).toHaveCount(0);

    await them.context().close();
  });

  test("the owner cannot hide it while someone else must act", async ({ page, browser }) => {
    const alice = uniqueEmail("hidown");
    const bob = uniqueEmail("hidmem");
    await signUp(page, alice);
    const orgId = await createOrg(page, `Hidden ${Date.now()}`);
    const link = await inviteMember(page, orgId, bob);
    const them = await otherPerson(browser, bob);
    await acceptInvite(them, link);

    await createTask(page, orgId, "Needs Bob");
    await openTask(page, orgId, "Needs Bob");
    await page.getByRole("button", { name: "Action required", exact: true }).click();
    await page.getByRole("option", { name: bob }).click();
    await expect(page.getByRole("heading", { name: /notified/ })).toBeVisible();

    // Refused with a reason rather than silently un-asking Bob, which would
    // leave him holding a notification that 404s.
    await page.getByRole("button", { name: "Hide from everyone else" }).click();
    await expect(page.getByText(/clear the action required first/)).toBeVisible();

    await them.context().close();
  });

  test("an admin has no hide button on someone else's task", async ({ page, browser }) => {
    const alice = uniqueEmail("hidown");
    const bob = uniqueEmail("hidmem");
    await signUp(page, alice);
    const orgId = await createOrg(page, `Hidden ${Date.now()}`);
    const link = await inviteMember(page, orgId, bob);
    const them = await otherPerson(browser, bob);
    await acceptInvite(them, link);

    await createTask(them, orgId, "Bob's own");

    // `can_hide` is resolved server-side, so the control isn't rendered rather
    // than being rendered and 403-ing.
    await openTask(page, orgId, "Bob's own");
    await expect(page.getByRole("button", { name: "Hide from everyone else" })).toHaveCount(0);
    // …but she can still close it. The two rules are deliberately different.
    await expect(page.getByRole("button", { name: "Close task" })).toBeVisible();

    await them.context().close();
  });
});
