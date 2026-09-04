import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  createOrg,
  createTask,
  inviteMember,
  openFilesPanel,
  signUp,
  uniqueEmail,
} from "./helpers";

/**
 * A task changing under someone else's eyes.
 *
 * Two real browser contexts with the same task open. Nothing here polls: the
 * assertions have short timeouts on purpose, so a change that only arrives on
 * the next refresh fails rather than passing slowly.
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

/** Both people, in the same organisation, looking at the same task. */
async function pair(page: Page, browser: Browser, title: string) {
  const owner = uniqueEmail("rtown");
  const mate = uniqueEmail("rtmate");
  await signUp(page, owner);
  const orgId = await createOrg(page, `Live ${Date.now()}`);
  const link = await inviteMember(page, orgId, mate, "admin");
  const them = await otherPerson(browser, mate);
  await acceptInvite(them, link);
  await createTask(page, orgId, title);
  await openTask(page, orgId, title);
  await openTask(them, orgId, title);
  return { orgId, them, mate };
}

// Short: if it needs longer than this, something is polling.
const LIVE = { timeout: 8_000 };

test.describe("a task changing live", () => {
  test("a status change reaches the other tab", async ({ page, browser }) => {
    const { them } = await pair(page, browser, "Watched work");

    await expect(them.getByText("To do").first()).toBeVisible();
    await page.getByRole("button", { name: "Status", exact: true }).click();
    await page.getByRole("option", { name: "Blocked" }).click();
    await expect(page.getByRole("heading", { name: "Status updated" })).toBeVisible();

    // No reload, no poll.
    await expect(them.getByText("Blocked").first()).toBeVisible(LIVE);
    // And the history moved with it.
    await expect(them.getByText("moved it to Blocked")).toBeVisible(LIVE);

    await them.context().close();
  });

  test("a due date and a priority reach the other tab", async ({ page, browser }) => {
    const { them } = await pair(page, browser, "Dated work");

    await page.getByLabel("Due").fill("2027-03-01");
    await expect(page.getByRole("heading", { name: "Due date updated" })).toBeVisible();
    await expect(them.getByLabel("Due")).toHaveValue("2027-03-01", LIVE);

    await page.getByRole("button", { name: "Priority", exact: true }).click();
    await page.getByRole("option", { name: "Critical" }).click();
    await expect(
      them.getByRole("button", { name: "Priority", exact: true }),
    ).toContainText("Critical", LIVE);

    await them.context().close();
  });

  test("a file uploaded on one tab appears on the other", async ({ page, browser }) => {
    const { them } = await pair(page, browser, "Shared files");
    // Both tabs start with an empty, collapsed Files panel; the uploading
    // side needs it open, and the watching side reveals itself when the
    // file lands, which is half of what this test is checking.
    await openFilesPanel(page);

    await page.getByLabel("File to add to this task").setInputFiles({
      name: "plan.png",
      mimeType: "image/png",
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        "base64",
      ),
    });
    await expect(
      page.getByRole("region", { name: "Files" }).getByRole("button", { name: "Open plan.png" }),
    ).toBeVisible({ timeout: 15_000 });

    await expect(
      them.getByRole("region", { name: "Files" }).getByRole("button", { name: "Open plan.png" }),
    ).toBeVisible(LIVE);

    await them.context().close();
  });

  test("a tag appears, and time logged shows in the other tab's history", async ({
    page,
    browser,
  }) => {
    const { them } = await pair(page, browser, "Tagged live");

    await page.getByRole("button", { name: "Add a tag" }).click();
    await page.getByRole("textbox", { name: "Find or create a tag" }).fill("Urgent job");
    await page.getByRole("button", { name: /Create .Urgent job./ }).click();
    await expect(page.getByRole("button", { name: "Remove tag Urgent job" })).toBeVisible();
    await expect(them.getByText("Urgent job")).toBeVisible(LIVE);

    await page.getByLabel("Log time already spent").fill("45");
    await page.getByRole("button", { name: "Log", exact: true }).click();
    await expect(them.getByText(/logged 45m/)).toBeVisible(LIVE);

    await them.context().close();
  });

  test("hiding it tells the watcher, who loses the screen rather than the data", async ({
    page,
    browser,
  }) => {
    // The event carries no content — only the id. So the watcher's refetch is
    // what discovers the access is gone, and 404 is the right answer.
    const { them } = await pair(page, browser, "About to vanish");

    await page.getByRole("button", { name: "Hide from everyone else" }).click();
    await expect(page.getByText("Only you.")).toBeVisible();

    await expect(them.getByText(/don.t have access to this task/)).toBeVisible(LIVE);

    await them.context().close();
  });

  test("a status change moves the card on someone else's board", async ({ page, browser }) => {
    // The board coalesces rather than refetching per event, so it is allowed
    // more time than the task screen — still far less than a poll.
    //
    // Asserting on the *card's column*, not on the word "Blocked": that word
    // is a column heading and is on screen either way, which is exactly how a
    // first attempt at this test passed while the board received nothing.
    const owner = uniqueEmail("rtown");
    const mate = uniqueEmail("rtmate");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Live ${Date.now()}`);
    const link = await inviteMember(page, orgId, mate, "admin");
    const them = await otherPerson(browser, mate);
    await acceptInvite(them, link);
    await createTask(page, orgId, "Moves on its own");

    await them.goto(`/orgs/${orgId}/tasks`);
    const column = (name: string) =>
      them.locator("div.rounded-xl").filter({ has: them.getByText(name, { exact: true }) });
    await expect(column("To do").getByText("Moves on its own")).toBeVisible();
    await expect(column("Blocked").getByText("Moves on its own")).toHaveCount(0);

    await openTask(page, orgId, "Moves on its own");
    await page.getByRole("button", { name: "Status", exact: true }).click();
    await page.getByRole("option", { name: "Blocked" }).click();
    await expect(page.getByRole("heading", { name: "Status updated" })).toBeVisible();

    // No reload on their side.
    await expect(column("Blocked").getByText("Moves on its own")).toBeVisible({ timeout: 15_000 });
    await expect(column("To do").getByText("Moves on its own")).toHaveCount(0);

    await them.context().close();
  });

  test("one socket per tab, not one per panel", async ({ page, browser }) => {
    // The task screen has two subscribers — the thread and the task itself.
    // A connection each would mean two upgrades and two reconnect loops.
    const owner = uniqueEmail("rtown");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Live ${Date.now()}`);
    await createTask(page, orgId, "One socket");

    const sockets: string[] = [];
    page.on("websocket", (ws) => sockets.push(ws.url()));
    await openTask(page, orgId, "One socket");
    await page.waitForTimeout(1500);

    expect(sockets.filter((u) => u.includes("/api/ws"))).toHaveLength(1);
    expect(browser).toBeTruthy();
  });
});
