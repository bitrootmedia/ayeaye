import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * Chats in a real browser: a DM reaching the other person live, a reply
 * quoting what it answers, the privacy rule an org admin runs into, and a
 * task's comments showing up as a chat.
 *
 * The admin is the organisation's owner on purpose — the one person who can
 * open every task in it, and so the one a DM most needs to stay shut to.
 */

async function person(browser: Browser, email: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signUp(page, email);
  return page;
}

async function join(page: Page, link: string) {
  await page.goto(link);
  await page.getByRole("button", { name: /^Join / }).click();
  await page.waitForURL(/\/orgs\/[0-9a-f-]+/);
}

const LIVE = { timeout: 8_000 };

test.describe("chats", () => {
  test("a DM arrives live, replies quote, and an admin can't read it", async ({
    page,
    browser,
  }) => {
    const bob = uniqueEmail("chatbob");
    const carol = uniqueEmail("chatcarol");
    await signUp(page, uniqueEmail("chatadmin"));
    const orgId = await createOrg(page, `Chat ${Date.now()}`);
    const bobLink = await inviteMember(page, orgId, bob);
    const carolLink = await inviteMember(page, orgId, carol);
    const b = await person(browser, bob);
    await join(b, bobLink);
    const c = await person(browser, carol);
    await join(c, carolLink);

    // Carol is sitting on her chat list before anything exists.
    await c.goto(`/orgs/${orgId}/chats`);
    await expect(c.getByText("No conversations yet", { exact: false })).toBeVisible();

    // Bob starts a DM through the New message dialog.
    await b.goto(`/orgs/${orgId}/chats`);
    await b.getByRole("button", { name: "New message" }).click();
    await b.getByRole("button", { name: "Who to message" }).click();
    await b.getByRole("option", { name: new RegExp(carol) }).click();
    await b.waitForURL(/\/chats\/[0-9a-f-]+$/);
    const dm = b.url();
    await b.getByRole("textbox", { name: "Write a message" }).fill("Lunch?");
    await b.keyboard.press("Enter");
    await expect(b.getByText("Lunch?", { exact: true })).toBeVisible();

    // It reaches Carol's list without a reload, unread.
    const row = c.getByRole("link", { name: new RegExp(bob) });
    await expect(row).toBeVisible(LIVE);
    await expect(row).toContainText("Lunch?");
    await row.click();
    await expect(c.getByText("Lunch?", { exact: true })).toBeVisible();

    // She replies to that message specifically.
    await c.getByText("Lunch?", { exact: true }).hover();
    await c.getByRole("button", { name: "Reply" }).first().click();
    await c.getByRole("textbox", { name: "Write a message" }).fill("Sure, 1pm");
    await c.keyboard.press("Enter");

    // Bob, still in the conversation, sees the reply and what it quotes.
    const reply = b.locator("[data-message]").filter({ hasText: "Sure, 1pm" });
    await expect(reply).toBeVisible(LIVE);
    await expect(reply).toContainText("Lunch?");

    // The owner of the organisation follows the link and gets nothing.
    await page.goto(dm.replace(/^https?:\/\/[^/]+/, ""));
    await expect(page.getByText("This chat doesn't exist, or you're not in it.")).toBeVisible();
    await page.goto(`/orgs/${orgId}/chats`);
    await expect(page.getByRole("link", { name: new RegExp(bob) })).toHaveCount(0);
  });

  test("a task's comments are a chat", async ({ page }) => {
    await signUp(page, uniqueEmail("chattask"));
    const orgId = await createOrg(page, `Chat task ${Date.now()}`);
    await createTask(page, orgId, "Survey the keel");
    await page.goto(`/orgs/${orgId}/tasks`);
    await page.getByRole("link", { name: /Survey the keel/ }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);

    await page.getByRole("button", { name: "Open in Chats" }).click();
    await page.waitForURL(/\/chats\/[0-9a-f-]+$/);
    await page.getByRole("textbox", { name: "Write a message" }).fill("Osmosis, port side");
    await page.keyboard.press("Enter");
    await expect(page.getByText("Osmosis, port side", { exact: true })).toBeVisible();

    // The same words, as a comment on the task.
    await page.getByRole("button", { name: "Open task" }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
    await expect(
      page.getByRole("region", { name: "Comments" }).getByText("Osmosis, port side"),
    ).toBeVisible();
  });
});
