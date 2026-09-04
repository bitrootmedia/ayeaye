import { expect, test, type Page } from "@playwright/test";

import {
  createOrg,
  createProject,
  createTask,
  openPrivateNote,
  signUp,
  uniqueEmail,
} from "./helpers";

/**
 * The list view: a real table, sorted and filtered by the server.
 *
 * Sorting in the browser would only order the rows it happens to be holding —
 * the list is a page — so these assert the *first row* changes, which is only
 * true if the ordering came back from the server.
 */

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

const firstRow = (page: Page) => page.locator("tbody tr").first();

test.describe("the task list", () => {
  test("shows every column it promises", async ({ page }) => {
    await signUp(page, uniqueEmail("tl"));
    const orgId = await createOrg(page, `List ${Date.now()}`);
    await createProject(page, orgId, "Refit");
    await createTask(page, orgId, "Ordinary work", "Refit");

    await page.goto(`/orgs/${orgId}/tasks?view=list`);
    for (const heading of [
      "Task",
      "Project",
      "Status",
      "Priority",
      "Owner",
      "Action required",
      "Created",
      "Updated",
    ]) {
      await expect(page.getByRole("button", { name: `Sort by ${heading}` })).toBeVisible();
    }
    const row = firstRow(page);
    await expect(row).toContainText("Ordinary work");
    await expect(row).toContainText("Refit");
    await expect(row).toContainText("To do");
    await expect(row).toContainText("Normal");
  });

  test("sorting by a column reorders the whole list, not the page", async ({ page }) => {
    await signUp(page, uniqueEmail("tl"));
    const orgId = await createOrg(page, `List ${Date.now()}`);
    for (const title of ["Alpha job", "Zulu job", "Mike job"]) {
      await createTask(page, orgId, title);
    }

    await page.goto(`/orgs/${orgId}/tasks?view=list`);
    await page.getByRole("button", { name: "Sort by Task" }).click();
    await expect(firstRow(page)).toContainText("Alpha job");

    // The same header again flips the direction.
    await page.getByRole("button", { name: "Sort by Task" }).click();
    await expect(firstRow(page)).toContainText("Zulu job");

    // …and it's in the URL, so the view can be sent to somebody.
    await expect(page).toHaveURL(/sort=title/);
    await expect(page).toHaveURL(/dir=desc/);
  });

  test("filters narrow the list and combine", async ({ page }) => {
    await signUp(page, uniqueEmail("tl"));
    const orgId = await createOrg(page, `List ${Date.now()}`);
    await createTask(page, orgId, "Still to do");
    await createTask(page, orgId, "Being done");
    await openTask(page, orgId, "Being done");
    await page.getByRole("button", { name: "Status", exact: true }).click();
    await page.getByRole("option", { name: "In progress" }).click();
    await expect(page.getByRole("heading", { name: "Status updated" })).toBeVisible();

    await page.goto(`/orgs/${orgId}/tasks?view=list`);
    await expect(page.locator("tbody tr")).toHaveCount(2);

    await page.getByLabel("Filter by status").click();
    await page.getByRole("option", { name: "In progress" }).click();
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await expect(firstRow(page)).toContainText("Being done");

    // Combining with one that matches nothing empties it rather than ignoring
    // the second filter.
    await page.getByLabel("Filter by priority").click();
    await page.getByRole("option", { name: "Critical" }).click();
    await expect(page.getByText("No tasks here")).toBeVisible();
  });

  test("the board has no status filter — its columns are the statuses", async ({ page }) => {
    await signUp(page, uniqueEmail("tl"));
    const orgId = await createOrg(page, `List ${Date.now()}`);
    await createTask(page, orgId, "Anything");

    await page.goto(`/orgs/${orgId}/tasks`);
    await expect(page.getByLabel("Filter by status")).toHaveCount(0);
    await page.goto(`/orgs/${orgId}/tasks?view=list`);
    await expect(page.getByLabel("Filter by status")).toBeVisible();
  });
});

test.describe("updated_at is last activity", () => {
  test("a comment moves a task to the top of the recently-updated list", async ({ page }) => {
    await signUp(page, uniqueEmail("tl"));
    const orgId = await createOrg(page, `List ${Date.now()}`);
    await createTask(page, orgId, "Older work");
    await createTask(page, orgId, "Newer work");

    // Newest first to begin with.
    await page.goto(`/orgs/${orgId}/tasks?view=list&sort=updated_at&dir=desc`);
    await expect(firstRow(page)).toContainText("Newer work");

    // A comment doesn't touch the tasks row, so this only works because
    // posting one announces the task as changed.
    await openTask(page, orgId, "Older work");
    await page.getByLabel("Write a comment").fill("Picking this back up");
    await page.getByRole("button", { name: "Comment" }).click();
    await expect(page.getByText("Picking this back up")).toBeVisible();

    await page.goto(`/orgs/${orgId}/tasks?view=list&sort=updated_at&dir=desc`);
    await expect(firstRow(page)).toContainText("Older work");
  });

  test("a private note does not — that would leak it", async ({ page }) => {
    await signUp(page, uniqueEmail("tl"));
    const orgId = await createOrg(page, `List ${Date.now()}`);
    await createTask(page, orgId, "Quiet one");
    await createTask(page, orgId, "Loud one");

    await page.goto(`/orgs/${orgId}/tasks?view=list&sort=updated_at&dir=desc`);
    await expect(firstRow(page)).toContainText("Loud one");

    await openTask(page, orgId, "Quiet one");
    await openPrivateNote(page);
    await page.getByRole("textbox", { name: "Your private note" }).fill("nobody sees this");
    await page.getByRole("textbox", { name: "Your private note" }).blur();
    await expect(page.getByText(/Saved/)).toBeVisible();

    // Unmoved. A note nobody else can read must not announce itself through a
    // timestamp everybody can see.
    await page.goto(`/orgs/${orgId}/tasks?view=list&sort=updated_at&dir=desc`);
    await expect(firstRow(page)).toContainText("Loud one");
  });
});
