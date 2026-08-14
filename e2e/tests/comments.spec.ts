import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createProject, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

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

const box = (page: Page) => page.getByLabel("Write a comment");

async function comment(page: Page, text: string) {
  await box(page).fill(text);
  await page.getByRole("button", { name: "Comment" }).click();
  await expect(box(page)).toHaveValue("");
}

test.describe("comments", () => {
  test("post one, and it appears attributed", async ({ page }) => {
    const me = uniqueEmail("cm");
    await signUp(page, me);
    const orgId = await createOrg(page, `Talk ${Date.now()}`);
    await createTask(page, orgId, "Survey the keel");
    await openTask(page, orgId, "Survey the keel");

    await expect(page.getByText("No comments yet")).toBeVisible();
    await comment(page, "Keel looks sound");
    await expect(page.getByText("Keel looks sound")).toBeVisible();
    await expect(page.getByText(me).first()).toBeVisible();
  });

  test("Enter sends, Shift+Enter breaks the line", async ({ page }) => {
    await signUp(page, uniqueEmail("cm"));
    const orgId = await createOrg(page, `Keys ${Date.now()}`);
    await createTask(page, orgId, "Typing test");
    await openTask(page, orgId, "Typing test");

    // Shift+Enter must NOT submit — otherwise a two-line comment is two
    // comments, and people learn not to press Enter at all.
    await box(page).fill("first line");
    await box(page).press("Shift+Enter");
    await box(page).pressSequentially("second line");
    await expect(box(page)).toHaveValue(/first line\nsecond line/);

    await box(page).press("Enter");
    await expect(box(page)).toHaveValue("");
    await expect(page.getByText(/first line/)).toBeVisible();
  });

  test("editing marks it edited; deleting leaves a tombstone", async ({ page }) => {
    await signUp(page, uniqueEmail("cm"));
    const orgId = await createOrg(page, `Edit ${Date.now()}`);
    await createTask(page, orgId, "Revise me");
    await openTask(page, orgId, "Revise me");
    await comment(page, "First draft");

    await page.getByRole("button", { name: "Edit comment" }).click();
    await page.getByLabel("Edit comment body").fill("Second draft");
    await page.getByRole("button", { name: "Save comment" }).click();
    await expect(page.getByText("Second draft")).toBeVisible();
    await expect(page.getByText(/edited/)).toBeVisible();

    await page.getByRole("button", { name: "Remove comment" }).click();
    // A hole would leave the surrounding replies making no sense.
    await expect(page.getByText(/removed a comment/)).toBeVisible();
    await expect(page.getByText("Second draft")).toHaveCount(0);
  });

  test("a read-only viewer can still comment", async ({ page, browser }) => {
    // The product decision: a comment is a contribution, not a change to the
    // work. The commonest reason to share read-only is to get someone's input.
    const owner = uniqueEmail("own");
    const viewer = uniqueEmail("vw");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Viewer ${Date.now()}`);
    const link = await inviteMember(page, orgId, viewer);
    const them = await otherPerson(browser, viewer);
    await acceptInvite(them, link);

    await createProject(page, orgId, "Shared refit");
    await page.getByLabel("Share with").click();
    await page.getByRole("option", { name: viewer }).click();
    await page.getByRole("button", { name: "Share" }).click();
    await expect(page.getByText(`Shared with ${viewer}`)).toBeVisible();

    await createTask(page, orgId, "Check the shaft", "Shared refit");

    await openTask(them, orgId, "Check the shaft");
    // They cannot edit the task…
    await expect(them.getByText("You have view-only access")).toBeVisible();
    // …but they can say something about it.
    await comment(them, "Shaft has play in it");
    await expect(them.getByText("Shaft has play in it")).toBeVisible();

    await them.context().close();
  });

  test("a comment arrives live, without a refresh", async ({ page, browser }) => {
    // The socket carries no content — it says "this conversation moved" and
    // the client refetches. What matters here is that the other side updates
    // with nobody touching it.
    const owner = uniqueEmail("own");
    const other = uniqueEmail("oth");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Live ${Date.now()}`);
    const link = await inviteMember(page, orgId, other);
    const them = await otherPerson(browser, other);
    await acceptInvite(them, link);

    await createProject(page, orgId, "Live refit");
    await page.getByLabel("Share with").click();
    await page.getByRole("option", { name: other }).click();
    await page.getByRole("button", { name: "Share" }).click();
    await expect(page.getByText(`Shared with ${other}`)).toBeVisible();
    await createTask(page, orgId, "Watch me update", "Live refit");

    // Both people sit on the task.
    await openTask(page, orgId, "Watch me update");
    await openTask(them, orgId, "Watch me update");
    await expect(them.getByText("No comments yet")).toBeVisible();

    await comment(page, "Can you see this?");

    // No reload on their side — the socket did it.
    await expect(them.getByText("Can you see this?")).toBeVisible({ timeout: 10_000 });

    await them.context().close();
  });

  test("projects have their own thread", async ({ page }) => {
    await signUp(page, uniqueEmail("cm"));
    const orgId = await createOrg(page, `Proj ${Date.now()}`);
    const projectId = await createProject(page, orgId, "Talkable");
    await comment(page, "Kick-off Monday");
    await expect(page.getByText("Kick-off Monday")).toBeVisible();

    // Separate from any task's thread.
    await createTask(page, orgId, "A task", "Talkable");
    await openTask(page, orgId, "A task");
    await expect(page.getByText("No comments yet")).toBeVisible();
    expect(projectId).toBeTruthy();
  });
});
