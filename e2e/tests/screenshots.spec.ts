import { expect, test, type Page } from "@playwright/test";

import { createOrg, createProject, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * Builds one realistic organisation and photographs every main screen, in both
 * themes, into `artifacts/shots/`.
 *
 * Not an assertion suite — it's how a human (or an agent with no browser)
 * reviews what the product actually looks like. Three of the bugs found while
 * writing these tests were only visible this way: copy that contradicted the
 * access model, a stale "arrives in the next phase" card, and an empty state
 * that told a lone user everyone could already see their work.
 */

/** Wait for the screen to settle before photographing it.
 *
 *  Without this you capture spinners: every screen fetches after mount, so
 *  `goto` resolving is not the same as the screen being ready. */
async function shot(page: Page, name: string) {
  await page.waitForLoadState("networkidle");
  await page.locator('[data-slot="spinner"]').waitFor({ state: "hidden" }).catch(() => {});
  await page.waitForTimeout(250);
  await page.screenshot({ path: `artifacts/shots/${name}.png`, fullPage: true });
}

async function setTheme(page: Page, theme: "light" | "dark") {
  const current = await page.evaluate(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  if (current !== theme) {
    await page.getByRole("button", { name: theme === "dark" ? "Dark" : "Light" }).click();
  }
}

test("photograph the product", async ({ page }) => {
  test.slow();
  const owner = uniqueEmail("shot");
  const mate = uniqueEmail("mate");

  await page.goto("/auth?show=signup");
  await page.getByText("Sign Up", { exact: true }).first().waitFor();
  await shot(page, "01-sign-up");

  // The same screen with the lights off. The auth UI lives in a shadow root
  // and inherits the product's tokens through it, so this is the check that
  // the theme actually reaches it.
  await page.evaluate(() => localStorage.setItem("ui-theme", "dark"));
  await page.reload();
  await page.getByText("Sign Up", { exact: true }).first().waitFor();
  await shot(page, "01-sign-up-dark");
  await page.evaluate(() => localStorage.setItem("ui-theme", "light"));
  await page.reload();

  await signUp(page, owner);
  await shot(page, "02-no-organisations");

  const orgId = await createOrg(page, "Blue Horizon");
  await shot(page, "02b-dashboard-empty");
  await page.goto(`/orgs/${orgId}/people`);
  await shot(page, "03-organisation-people");

  await inviteMember(page, orgId, mate, "admin");
  await shot(page, "04-invitation-link");

  // Some structure to photograph against.
  await page.goto(`/orgs/${orgId}/structure`);
  await page.getByLabel("New team").fill("Deck crew");
  await page.getByRole("button", { name: "New team" }).click();
  await page.getByLabel("New group").fill("Refit");
  await page.getByRole("button", { name: "New group" }).click();
  await shot(page, "05-teams-and-groups");

  await createProject(page, orgId, "Hull refit");
  await shot(page, "06-project-detail");

  await createTask(page, orgId, "Strip the old antifoul", "Hull refit");
  await createTask(page, orgId, "Order two-part epoxy", "Hull refit");
  await createTask(page, orgId, "Book the travel lift");

  // Spread them across the board so the columns aren't all empty.
  for (const [title, status] of [
    ["Order two-part epoxy", "In progress"],
    ["Book the travel lift", "Blocked"],
  ] as const) {
    await page.goto(`/orgs/${orgId}/tasks`);
    await page.getByRole("link", { name: new RegExp(title) }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
    await page.getByLabel("Status").click();
    await page.getByRole("option", { name: status }).click();
    await page.waitForTimeout(300);
  }

  // And across the priority range, so the glyphs aren't all Normal.
  for (const [title, priority] of [
    ["Strip the old antifoul", "High"],
    ["Book the travel lift", "Critical"],
  ] as const) {
    await page.goto(`/orgs/${orgId}/tasks`);
    await page.getByRole("link", { name: new RegExp(title) }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
    await page.getByRole("button", { name: "Priority", exact: true }).click();
    await page.getByRole("option", { name: priority }).click();
    await page.waitForTimeout(300);
  }

  await page.goto(`/orgs/${orgId}/tasks`);
  await shot(page, "07-task-board");

  // The same cards, arranged by the other question a board gets asked.
  await page.goto(`/orgs/${orgId}/tasks?group=priority`);
  await shot(page, "07-task-board-by-priority");

  await page.goto(`/orgs/${orgId}/tasks?view=list`);
  await shot(page, "08-task-list");

  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: /Strip the old antifoul/ }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);

  // A comment with a picture on it, so the thread isn't photographed empty.
  await page.getByLabel("File to upload").setInputFiles({
    name: "hull.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAEAAAAAgCAYAAACinX6EAAAAM0lEQVR42u3MMQEAAAgDoC252H0Mg0dogo1TFQAAAAAAAAAAAAAAAAAAAAAAAAAAAADwzQI1kQGVn6IjqAAAAABJRU5ErkJggg==",
      "base64",
    ),
  });
  await page.getByRole("button", { name: "Remove hull.png" }).waitFor({ timeout: 15_000 });
  await page.getByLabel("Write a comment").fill("Starboard side after the first pass.");
  await page.getByRole("button", { name: "Comment" }).click();
  // Scoped: the same picture lands in the Files panel above the thread too.
  await page
    .getByRole("region", { name: "Comments" })
    .getByRole("img", { name: "hull.png" })
    .waitFor({ timeout: 15_000 });

  await shot(page, "09-task-detail");

  // The picker open, filter and all — this is what replaced every dropdown
  // that could hold more than a handful of things.
  await page.getByRole("button", { name: "Priority", exact: true }).click();
  await shot(page, "09-picker-open");
  await page.keyboard.press("Escape");

  // And a picture full size, opened from the Files panel.
  await page
    .getByRole("region", { name: "Files" })
    .getByRole("button", { name: "Open hull.png" })
    .click();
  await shot(page, "09-lightbox");
  await page.keyboard.press("Escape");

  await page.goto(`/orgs/${orgId}/projects`);
  await shot(page, "10-projects");

  // The search palette, mid-query.
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("textbox", { name: "Search" }).pressSequentially("antif");
  await page.waitForTimeout(600);
  await shot(page, "11-search-palette");
  await page.keyboard.press("Escape");

  // Some logged time, so the rollups aren't all zeroes.
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: /Strip the old antifoul/ }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
  await page.getByLabel("Log time already spent").fill("2h30");
  await page.getByRole("button", { name: "Log", exact: true }).click();
  await page.waitForTimeout(400);
  await page.goto(`/orgs/${orgId}/time`);
  await shot(page, "12-time");

  // The task's own private note and reminder, photographed with the task.
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: /Strip the old antifoul/ }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
  await page.getByRole("textbox", { name: "Your private note" }).fill(
    "The yard quoted 400 for the lift. Worth asking Ada before we book.",
  );
  await page.getByRole("textbox", { name: "Your private note" }).blur();
  await page.getByRole("button", { name: "Add a tag" }).click();
  await page.getByRole("textbox", { name: "Find or create a tag" }).fill("Hull");
  await page.getByRole("button", { name: /Create .Hull./ }).click();
  await expect(page.getByRole("button", { name: "Remove tag Hull" })).toBeVisible();
  await shot(page, "09b-task-notes-and-tags");

  // The dashboard, with something on it.
  await page.goto("/account");
  const today = new Date().toISOString().slice(0, 10);
  const soon = new Date(Date.now() + 4 * 86_400_000).toISOString().slice(0, 10);
  await page.getByLabel("Status").fill("Refitting the Blue Horizon");
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByLabel("From").fill(today);
  await page.getByLabel("Until (included)").fill(soon);
  await page.getByLabel("Why").fill("sea trials");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await shot(page, "13-account");

  await page.goto(`/orgs/${orgId}`);
  await page.getByRole("button", { name: "Announcement" }).click();
  await page
    .getByRole("textbox", { name: "Announcement" })
    .fill("Travel lift is booked for the 3rd. Everything off the deck by Tuesday.");
  await page.getByText("Pin to the top").click();
  await page.getByRole("button", { name: "Post" }).click();
  await expect(page.getByText("Pinned")).toBeVisible();
  await shot(page, "02c-dashboard");

  await page.goto("/reminders");
  await shot(page, "14-reminders");

  await page.goto("/notifications");
  await shot(page, "13-notifications");

  await page.goto("/account");
  await shot(page, "14-account");

  // The same product with the lights off. The tokens are one set with a `.dark`
  // override, so this is the check that nothing hard-codes a colour.
  await setTheme(page, "dark");
  await page.goto(`/orgs/${orgId}/tasks`);
  await shot(page, "15-task-board-dark");
  await page.goto(`/orgs/${orgId}/projects`);
  await shot(page, "16-projects-dark");
});
