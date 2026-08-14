import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

test.describe("time tracking", () => {
  test("the timer runs in the header and ticks on its own", async ({ page }) => {
    await signUp(page, uniqueEmail("tm"));
    const orgId = await createOrg(page, `Clock ${Date.now()}`);
    await createTask(page, orgId, "Sand the hull");
    await openTask(page, orgId, "Sand the hull");

    await page.getByRole("button", { name: "Start timer" }).click();
    const clock = page.getByRole("status", { name: "Running timer" }).getByLabel("Elapsed");
    await expect(clock).toBeVisible();

    // The point of ticking client-side: the number moves without another
    // request. Two seconds of wall time has to show up.
    const first = await clock.textContent();
    await page.waitForTimeout(2100);
    expect(await clock.textContent()).not.toBe(first);

    await page.getByRole("button", { name: "Stop the running timer" }).click();
    await expect(page.getByRole("button", { name: "Start timer" })).toBeVisible();
  });

  test("the timer follows you across screens", async ({ page }) => {
    // It lives in the shell, not on the task — a timer you can only see by
    // navigating back to what you started is a timer you leave running.
    await signUp(page, uniqueEmail("tm"));
    const orgId = await createOrg(page, `Clock ${Date.now()}`);
    await createTask(page, orgId, "Keep timing me");
    await openTask(page, orgId, "Keep timing me");
    await page.getByRole("button", { name: "Start timer" }).click();
    await expect(page.getByRole("status", { name: "Running timer" })).toBeVisible();

    await page.goto(`/orgs/${orgId}/projects`);
    const timer = page.getByRole("status", { name: "Running timer" });
    await expect(timer).toBeVisible();
    await expect(timer.getByText("Keep timing me")).toBeVisible();
  });

  test("starting a second timer stops the first, and says so", async ({ page }) => {
    await signUp(page, uniqueEmail("tm"));
    const orgId = await createOrg(page, `Switch ${Date.now()}`);
    await createTask(page, orgId, "First job");
    await createTask(page, orgId, "Second job");

    await openTask(page, orgId, "First job");
    await page.getByRole("button", { name: "Start timer" }).click();
    await expect(page.getByRole("status", { name: "Running timer" })).toBeVisible();

    await openTask(page, orgId, "Second job");
    await page.getByRole("button", { name: "Start timer" }).click();
    // Not silent: the switch is announced, because otherwise the first task's
    // clock stops with no sign it ever did.
    await expect(page.getByText("Timer switched")).toBeVisible();
    await expect(page.getByText(/Stopped your timer on/)).toBeVisible();
  });

  test("durations can be typed the way people say them", async ({ page }) => {
    await signUp(page, uniqueEmail("tm"));
    const orgId = await createOrg(page, `Manual ${Date.now()}`);
    await createTask(page, orgId, "Log against me");
    await openTask(page, orgId, "Log against me");

    for (const [typed, shown] of [
      ["45", "45m"],
      ["1h30", "1h 30m"],
      ["2h", "2h"],
    ] as const) {
      await page.getByLabel("Log time already spent").fill(typed);
      await page.getByRole("button", { name: "Log", exact: true }).click();
      await expect(page.getByRole("heading", { name: `Logged ${shown}` })).toBeVisible();
    }

    // 45m + 1h30 + 2h = 4h 15m, shown as the task total.
    await expect(page.getByText("4h 15m").first()).toBeVisible();
  });

  test("nonsense in the duration box is refused, not guessed at", async ({ page }) => {
    await signUp(page, uniqueEmail("tm"));
    const orgId = await createOrg(page, `Manual ${Date.now()}`);
    await createTask(page, orgId, "Reject me");
    await openTask(page, orgId, "Reject me");

    await page.getByLabel("Log time already spent").fill("about an hour");
    await page.getByRole("button", { name: "Log", exact: true }).click();
    await expect(page.getByText("Couldn't read that")).toBeVisible();
  });

  test("a correction is recorded, not silent", async ({ page }) => {
    // PLAN.md §9: entries stay editable because people forget to stop timers.
    // The trade is that corrections have to be visible.
    await signUp(page, uniqueEmail("tm"));
    const orgId = await createOrg(page, `Edit ${Date.now()}`);
    await createTask(page, orgId, "Correct me");
    await openTask(page, orgId, "Correct me");

    await page.getByLabel("Log time already spent").fill("90m");
    await page.getByRole("button", { name: "Log", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Logged 1h 30m" })).toBeVisible();

    await page.getByRole("button", { name: "Edit duration" }).click();
    await page.getByLabel("Duration", { exact: true }).fill("45");
    await page.getByRole("button", { name: "Save duration" }).click();

    await expect(page.getByText("edited")).toBeVisible();
    await expect(page.getByText(/corrected 90m to 45m/)).toBeVisible();
  });

  test("the time page rolls up what you can see", async ({ page }) => {
    await signUp(page, uniqueEmail("tm"));
    const orgId = await createOrg(page, `Rollup ${Date.now()}`);
    await createTask(page, orgId, "Rolled up");
    await openTask(page, orgId, "Rolled up");
    await page.getByLabel("Log time already spent").fill("2h");
    await page.getByRole("button", { name: "Log", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Logged 2h" })).toBeVisible();

    await page.goto(`/orgs/${orgId}/time`);
    await expect(page.getByText("2h", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("By person")).toBeVisible();
    await expect(page.getByText("By project")).toBeVisible();
    await expect(page.getByRole("link", { name: "Rolled up" })).toBeVisible();
  });
});
