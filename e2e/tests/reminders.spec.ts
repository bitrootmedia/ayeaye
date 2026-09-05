import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

/**
 * Reminders, from the screen's side.
 *
 * The API suite drives the sweep and proves it fires once. What only a
 * browser shows is the part that makes the feature work at all: the red badge
 * in the rail that tells you something has come due while you were looking at
 * something else.
 */

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

const today = () => new Date().toISOString().slice(0, 10);
const inDays = (n: number) =>
  new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

test.describe("reminders", () => {
  test("one set for today turns the rail badge red", async ({ page }) => {
    await signUp(page, uniqueEmail("rm"));
    const orgId = await createOrg(page, `Remind ${Date.now()}`);
    await createTask(page, orgId, "Chase the yard");
    await openTask(page, orgId, "Chase the yard");

    const panel = page.getByRole("region", { name: "Reminders" });
    await expect(page.getByRole("link", { name: "Reminders" })).toBeVisible();

    await panel.getByLabel("Remind me on").fill(today());
    await panel.getByLabel("What about").fill("ring them");
    await panel.getByRole("button", { name: "Add reminder" }).click();

    await expect(panel.getByText("ring them")).toBeVisible();

    // The badge. It's the whole point — a reminder you only see by opening
    // the task you set it on is a reminder that reminds you of nothing.
    await page.goto("/reminders");
    await expect(page.getByText("Due now")).toBeVisible();
    await expect(page.getByRole("link", { name: "Chase the yard" })).toBeVisible();
  });

  test("one set for next week waits its turn", async ({ page }) => {
    await signUp(page, uniqueEmail("rm"));
    const orgId = await createOrg(page, `Remind ${Date.now()}`);
    await createTask(page, orgId, "Later job");
    await openTask(page, orgId, "Later job");

    await page.getByRole("region", { name: "Reminders" }).getByLabel("Remind me on").fill(inDays(7));
    await page.getByRole("region", { name: "Reminders" }).getByRole("button", { name: "Add reminder" }).click();
    await expect(page.getByRole("region", { name: "Reminders" }).getByText(inDays(7))).toBeVisible();

    await page.goto("/reminders");
    await expect(page.getByText("Coming up")).toBeVisible();
    await expect(page.getByText("Due now")).toHaveCount(0);
  });

  test("dismissing one clears it from the list", async ({ page }) => {
    await signUp(page, uniqueEmail("rm"));
    const orgId = await createOrg(page, `Remind ${Date.now()}`);
    await createTask(page, orgId, "Done with this");
    await openTask(page, orgId, "Done with this");

    const panel = page.getByRole("region", { name: "Reminders" });
    await panel.getByLabel("Remind me on").fill(today());
    await panel.getByRole("button", { name: "Add reminder" }).click();
    await expect(panel.getByText(today())).toBeVisible();

    await page.goto("/reminders");
    await page.getByRole("button", { name: /^Done with/ }).click();
    await expect(page.getByText("Nothing to remember")).toBeVisible();
  });

  test("the browser's timezone is sent up without anyone asking", async ({ page }) => {
    // Reminders are dates, so "the day before" is meaningless without it. It
    // has to be detected, because a setting nobody finds stays wrong.
    await signUp(page, uniqueEmail("rm"));
    const me = await page.evaluate(async () => {
      const res = await fetch("/api/me", { credentials: "include" });
      return res.json();
    });
    expect(me.timezone).toBeTruthy();
  });

  /**
   * Reported: reminders couldn't be edited.
   *
   * The endpoint always accepted the change — `PATCH /reminders/{id}` takes
   * the date, the note and a standalone one's title — so this was a missing
   * control, not a missing feature. Both surfaces get it, because a reminder
   * on a task is most likely edited on that task.
   */
  test("one on a task can be moved and re-worded in place", async ({ page }) => {
    await signUp(page, uniqueEmail("rmedit"));
    const orgId = await createOrg(page, `Remind ${Date.now()}`);
    await createTask(page, orgId, "Windlass service");
    await openTask(page, orgId, "Windlass service");

    await page.getByLabel("Remind me on").fill(inDays(30));
    await page.getByLabel("What about").fill("Order the spare");
    await page.getByRole("button", { name: "Add reminder" }).click();
    await expect(page.getByText("Order the spare")).toBeVisible();

    const panel = page.getByRole("region", { name: "Reminders" });
    await page.getByRole("button", { name: /^Edit the reminder for/ }).click();
    await page.getByLabel(/^Date for the reminder/).fill(inDays(60));
    await page.getByLabel(/^Note for the reminder/).fill("Order two spares");
    // Scoped: the Details card on this same screen has its own Save button.
    await panel.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Reminder updated" })).toBeVisible();

    await page.reload();
    await expect(page.getByText("Order two spares")).toBeVisible();
    await expect(panel.getByText(inDays(60))).toBeVisible();
  });

  test("a standalone one can have its title changed too", async ({ page }) => {
    await signUp(page, uniqueEmail("rmedit"));
    await createOrg(page, `Remind ${Date.now()}`);

    await page.goto("/reminders");
    await page.getByRole("button", { name: "New reminder" }).first().click();
    const dialog = page.locator('[data-slot="dialog-content"]');
    await dialog.getByLabel("What about", { exact: true }).fill("Renew the mooring");
    await dialog.getByLabel("Remind me on").fill(inDays(20));
    await dialog.getByRole("button", { name: "Set reminder" }).click();
    await expect(page.getByText("Renew the mooring")).toBeVisible();

    await page.getByRole("button", { name: /^Edit Renew the mooring/ }).click();
    // The title is only editable on a standalone reminder: a task-anchored
    // one takes its name from the task (ck_reminders_one_anchor).
    await page.getByLabel(/^Title for/).fill("Renew the mooring fee");
    await page.getByLabel(/^Note for/).fill("Harbour office, before April");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Reminder updated" })).toBeVisible();

    await page.reload();
    await expect(page.getByText("Renew the mooring fee")).toBeVisible();
    await expect(page.getByText("Harbour office, before April")).toBeVisible();
  });
});
