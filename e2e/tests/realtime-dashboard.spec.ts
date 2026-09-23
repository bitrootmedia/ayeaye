import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * The dashboard moving under somebody who is not touching it.
 *
 * It is built from four kinds of record — tasks, announcements, absences and
 * your own pins — and until this it was the one screen in the product whose
 * answer to "has anything changed" was to press reload. Every assertion here
 * is on a page nobody navigates or refreshes: a change that only arrives on
 * the next load fails rather than passing slowly.
 *
 * Longer than the task screen's own 8s allowance, because this page coalesces
 * events for 1.5s before refetching — the same bargain the Tasks board makes,
 * and the same reason its live test is given more room.
 */

const LIVE = { timeout: 15_000 };

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

/** An admin and a member, both in one organisation. */
async function pair(page: Page, browser: Browser) {
  const boss = uniqueEmail("rdown");
  const crew = uniqueEmail("rdmem");
  await signUp(page, boss);
  const orgId = await createOrg(page, `Live dash ${Date.now()}`);
  const link = await inviteMember(page, orgId, crew, "admin");
  const them = await otherPerson(browser, crew);
  await acceptInvite(them, link);
  return { orgId, them, crew };
}

test.describe("a dashboard changing live", () => {
  test("an announcement appears without a refresh", async ({ page, browser }) => {
    const { orgId, them } = await pair(page, browser);

    // They are looking at the dashboard and will not touch it again.
    await them.goto(`/orgs/${orgId}`);
    await expect(them.getByRole("region", { name: "Announcements" })).toBeVisible();
    await expect(them.getByText("Yard closed Friday")).toHaveCount(0);

    await page.goto(`/orgs/${orgId}`);
    await page.getByRole("button", { name: "Announcement" }).click();
    await page.getByRole("textbox", { name: "Announcement" }).fill("Yard closed Friday");
    await page.getByRole("button", { name: "Post" }).click();
    await expect(page.getByText("Yard closed Friday")).toBeVisible();

    await expect(them.getByText("Yard closed Friday")).toBeVisible(LIVE);

    // And taking it down reaches them too — the event is published either
    // way, which is the half that is easy to forget.
    await page.getByRole("button", { name: "Take this announcement down" }).click();
    await expect(page.getByText("Yard closed Friday")).toHaveCount(0);
    await expect(them.getByText("Yard closed Friday")).toHaveCount(0, LIVE);

    await them.context().close();
  });

  test("an absence set on an account reaches a colleague's open dashboard", async ({
    page,
    browser,
  }) => {
    // The one record here with no organisation of its own: it is set on
    // `/account` and read once per organisation the person belongs to, so the
    // event has to fan out over exactly those.
    const { orgId, them, crew } = await pair(page, browser);
    await page.goto(`/orgs/${orgId}`);
    const away = page.getByRole("region", { name: "Out of office" });
    await expect(away.getByText(crew)).toHaveCount(0);

    await them.goto("/account");
    await them.getByLabel("From").fill(today());
    await them.getByLabel("Until (included)").fill(inDays(3));
    await them.getByLabel("Why").fill("sailing");
    await them.getByRole("button", { name: "Add", exact: true }).click();
    await expect(them.getByText("Away now")).toBeVisible();

    await expect(away.getByText(crew)).toBeVisible(LIVE);
    await expect(away.getByText("sailing")).toBeVisible(LIVE);

    await them.context().close();
  });

  test("a task raised to critical lands on its owner's dashboard", async ({ page, browser }) => {
    // The task path, which the socket already carried — what was missing was
    // anything on this screen listening to it.
    const { orgId, them } = await pair(page, browser);
    await createTask(page, orgId, "Fix the sea cock");

    await page.goto(`/orgs/${orgId}`);
    const critical = page.getByRole("region", { name: "Critical tasks" });
    await expect(critical.getByText("Fix the sea cock")).toHaveCount(0);

    // The colleague, who is an admin, raises it from their own screen.
    await them.goto(`/orgs/${orgId}/tasks`);
    await them.getByRole("link", { name: /Fix the sea cock/ }).click();
    await them.waitForURL(/\/tasks\/[0-9a-f-]+$/);
    await them.getByRole("button", { name: "Priority", exact: true }).click();
    await them.getByRole("option", { name: "Critical" }).click();

    await expect(critical.getByText("Fix the sea cock")).toBeVisible(LIVE);

    await them.context().close();
  });

  test("a pin reaches your own other tab, and nobody else's", async ({ page, browser }) => {
    // A pin is private, so it is delivered by user id with no watch key —
    // your other tabs, not the organisation. Both halves are the test.
    const { orgId, them } = await pair(page, browser);
    await createTask(page, orgId, "Order the shackle");

    await page.goto(`/orgs/${orgId}`);
    const pinned = page.getByRole("region", { name: "Pinned tasks" });
    await expect(pinned.getByText("Order the shackle")).toHaveCount(0);
    await them.goto(`/orgs/${orgId}`);
    const theirPinned = them.getByRole("region", { name: "Pinned tasks" });

    // A second tab of the same person, which is where the pin happens.
    const other = await page.context().newPage();
    await other.goto(`/orgs/${orgId}/tasks`);
    await other.getByRole("link", { name: /Order the shackle/ }).click();
    await other.waitForURL(/\/tasks\/[0-9a-f-]+$/);
    await other.getByRole("button", { name: "Pin task" }).click();

    await expect(pinned.getByText("Order the shackle")).toBeVisible(LIVE);
    // Their dashboard has no business moving: nobody else's Pinned card
    // changes because you bookmarked something.
    await expect(theirPinned.getByText("Order the shackle")).toHaveCount(0);

    await other.close();
    await them.context().close();
  });
});
