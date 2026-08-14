import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  createOrg,
  createProject,
  createTask,
  inviteMember,
  signUp,
  uniqueEmail,
} from "./helpers";

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

test.describe("the board", () => {
  test("a new task lands in To do, and the board has no Closed column", async ({ page }) => {
    await signUp(page, uniqueEmail("tk"));
    const orgId = await createOrg(page, `Board ${Date.now()}`);
    await createTask(page, orgId, "Chart a course");

    // Five columns, and closed is not one of them: a closed task keeps its
    // real status, so a Closed column would throw that away.
    for (const column of ["To do", "In progress", "In review", "On hold", "Blocked"]) {
      await expect(page.getByText(column, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText("Closed", { exact: true })).toHaveCount(0);
  });

  test("closing keeps the status it had", async ({ page }) => {
    // The distinction the whole model rests on: "closed while still blocked"
    // has to be expressible, because that is what abandoned work looks like.
    await signUp(page, uniqueEmail("tk"));
    const orgId = await createOrg(page, `Board ${Date.now()}`);
    await createTask(page, orgId, "Abandoned work");
    await openTask(page, orgId, "Abandoned work");

    await page.getByLabel("Status").click();
    await page.getByRole("option", { name: "Blocked" }).click();
    await expect(page.getByText("Blocked").first()).toBeVisible();

    await page.getByRole("button", { name: "Close task" }).click();
    await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();
    // Still Blocked, plus a Closed badge — two independent facts.
    await expect(page.getByText("Blocked").first()).toBeVisible();
    await expect(page.getByText("Closed").first()).toBeVisible();
  });

  test("closed tasks are hidden until you ask for them", async ({ page }) => {
    await signUp(page, uniqueEmail("tk"));
    const orgId = await createOrg(page, `Board ${Date.now()}`);
    await createTask(page, orgId, "Finish me");
    await openTask(page, orgId, "Finish me");
    await page.getByRole("button", { name: "Close task" }).click();
    await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();

    await page.goto(`/orgs/${orgId}/tasks`);
    await expect(page.getByText("Finish me")).toHaveCount(0);
    await page.getByRole("button", { name: "Show closed" }).click();
    await expect(page.getByText("Finish me")).toBeVisible();
  });
});

test.describe("only the owner closes", () => {
  test("an editor can edit but has no close button", async ({ page, browser }) => {
    const owner = uniqueEmail("own");
    const editor = uniqueEmail("edt");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Crew ${Date.now()}`);
    const link = await inviteMember(page, orgId, editor);
    const them = await otherPerson(browser, editor);
    await acceptInvite(them, link);

    const projectId = await createProject(page, orgId, "Voyage");
    await page.getByLabel("Share with").click();
    await page.getByRole("option", { name: editor }).click();
    await page.getByLabel("Access level").click();
    await page.getByRole("option", { name: "Can edit" }).click();
    await page.getByRole("button", { name: "Share" }).click();
    await expect(page.getByText(`Shared with ${editor}`)).toBeVisible();

    await createTask(page, orgId, "Swab the deck", "Voyage");

    await openTask(them, orgId, "Swab the deck");
    // They can edit…
    await expect(them.getByLabel("Status")).toBeEnabled();
    // …but the close button isn't rendered at all, rather than being rendered
    // and 403-ing. `can_close` is resolved server-side.
    await expect(them.getByRole("button", { name: "Close task" })).toHaveCount(0);

    expect(projectId).toBeTruthy();
    await them.context().close();
  });
});

test.describe("action required", () => {
  test("naming someone notifies them and lets them in", async ({ page, browser }) => {
    const owner = uniqueEmail("own");
    const helper = uniqueEmail("hlp");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Crew ${Date.now()}`);
    const link = await inviteMember(page, orgId, helper);
    const them = await otherPerson(browser, helper);
    await acceptInvite(them, link);

    // A loose task: nothing but the action-required flag can let them in.
    await createTask(page, orgId, "Check the rigging");
    await openTask(page, orgId, "Check the rigging");

    await them.goto(`/orgs/${orgId}/tasks`);
    await expect(them.getByText("Check the rigging")).toHaveCount(0);

    await page.getByLabel("Action required").click();
    await page.getByRole("option", { name: helper }).click();
    await expect(page.getByText("They've been notified")).toBeVisible();

    // Being asked to act carries its own access — you cannot ask someone to
    // act on something they can't open.
    await them.goto(`/orgs/${orgId}/tasks`);
    await expect(them.getByText("Check the rigging")).toBeVisible();

    // And it reached their inbox.
    await them.goto("/notifications");
    await expect(them.getByText(/needs you on/)).toBeVisible();

    await them.context().close();
  });

  test("the unread badge appears and clears", async ({ page, browser }) => {
    const owner = uniqueEmail("own");
    const helper = uniqueEmail("hlp");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Crew ${Date.now()}`);
    const link = await inviteMember(page, orgId, helper);
    const them = await otherPerson(browser, helper);
    await acceptInvite(them, link);

    await createTask(page, orgId, "Hoist the sails");
    await openTask(page, orgId, "Hoist the sails");
    await page.getByLabel("Action required").click();
    await page.getByRole("option", { name: helper }).click();
    await expect(page.getByText("They've been notified")).toBeVisible();

    await them.goto("/notifications");
    await expect(them.getByRole("button", { name: "Mark all read" })).toBeVisible();
    await them.getByRole("button", { name: "Mark all read" }).click();
    await expect(them.getByRole("button", { name: "Mark all read" })).toHaveCount(0);

    await them.context().close();
  });
});

test.describe("history", () => {
  test("every change is recorded", async ({ page }) => {
    await signUp(page, uniqueEmail("tk"));
    const orgId = await createOrg(page, `Log ${Date.now()}`);
    await createTask(page, orgId, "Trace me");
    await openTask(page, orgId, "Trace me");

    await expect(page.getByText("created this task")).toBeVisible();

    await page.getByLabel("Status").click();
    await page.getByRole("option", { name: "In progress" }).click();
    await expect(page.getByText("moved it to In progress")).toBeVisible();

    await page.getByRole("button", { name: "Close task" }).click();
    await expect(page.getByText("closed it")).toBeVisible();

    await page.getByRole("button", { name: "Reopen" }).click();
    await expect(page.getByText("reopened it")).toBeVisible();
  });
});
