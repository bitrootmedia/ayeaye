import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

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

/**
 * The day planner: a pool of open tasks, five buckets, drag between them.
 *
 * Keyboard-driven drag rather than synthetic pointer movement — dnd-kit's
 * mouse sensor is pointer-event-based and genuinely flaky to script through
 * Playwright's `mouse.move` steps, and this is the same idiom the picker is
 * already tested with (type/arrow/Enter, not literal pointer paths). It also
 * proves the drag is actually reachable by keyboard, which is a real
 * requirement here and not just a testing convenience.
 */
test.describe("the planner", () => {
  test("an open task starts in the pool", async ({ page }) => {
    await signUp(page, uniqueEmail("pl"));
    const orgId = await createOrg(page, `Planner ${Date.now()}`);
    await createTask(page, orgId, "Order the antifoul");

    await page.goto(`/orgs/${orgId}/planner`);
    await expect(
      page.getByRole("region", { name: "Not planned yet" }).getByText("Order the antifoul"),
    ).toBeVisible();
    await expect(page.getByRole("region", { name: "Today" }).getByText("Order the antifoul")).toHaveCount(
      0,
    );
  });

  test("the title opens the task, without picking it up", async ({ page }) => {
    await signUp(page, uniqueEmail("pl"));
    const orgId = await createOrg(page, `Planner ${Date.now()}`);
    await createTask(page, orgId, "Order the antifoul");
    await page.goto(`/orgs/${orgId}/planner`);

    await page.getByRole("link", { name: "Order the antifoul" }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: "Order the antifoul" })).toBeVisible();
  });

  test("keyboard drag moves a task out of the pool and into a bucket", async ({ page }) => {
    // Which bucket a single ArrowRight lands on is dnd-kit's own spatial
    // collision algorithm, not a product decision this test should pin — the
    // thing that matters here is that keyboard drag genuinely crosses from
    // one container to another and the move is a real placement, not a
    // client-only rearrangement.
    await signUp(page, uniqueEmail("pl"));
    const orgId = await createOrg(page, `Planner ${Date.now()}`);
    await createTask(page, orgId, "Order the antifoul");
    await page.goto(`/orgs/${orgId}/planner`);

    // dnd-kit's keyboard sensor updates its collision state on the next
    // animation frame, not synchronously with the keydown — a bare
    // press/press/press sequence races that update and intermittently drops
    // in place. A short pause after each step is what the interaction
    // actually needs, not a Playwright quirk.
    const handle = page.getByRole("button", { name: "Move Order the antifoul" });
    await handle.focus();
    await page.keyboard.press("Space");
    await page.waitForTimeout(250);
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(250);
    await page.keyboard.press("Space");

    await expect(
      page.getByRole("region", { name: "Not planned yet" }).getByText("Order the antifoul"),
    ).toHaveCount(0);
    const landedIn = page
      .locator('[role="region"]')
      .filter({ hasText: "Order the antifoul" })
      .first();
    const bucketName = await landedIn.getAttribute("aria-label");

    // Survives a reload — it's a real server-side placement, not local state.
    await page.reload();
    await expect(
      page.getByRole("region", { name: bucketName ?? "" }).getByText("Order the antifoul"),
    ).toBeVisible();
  });

  test("the \"planning for\" picker: an admin gets it, a plain member never does", async ({
    page,
    browser,
  }) => {
    const owner = uniqueEmail("plo");
    const mate = uniqueEmail("plm");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Planner roles ${Date.now()}`);
    const link = await inviteMember(page, orgId, mate, "member");

    const them = await otherPerson(browser, mate);
    await acceptInvite(them, link);

    await page.goto(`/orgs/${orgId}/planner`);
    // The owner administers the organisation, and there's now someone else
    // to plan for.
    await expect(page.getByRole("button", { name: "Planning for" })).toBeVisible();

    await them.goto(`/orgs/${orgId}/planner`);
    await expect(them.getByRole("button", { name: "Planning for" })).toHaveCount(0);
  });
});
