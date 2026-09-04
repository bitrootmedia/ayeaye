import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

/**
 * Tags, and the one that takes work off the board.
 *
 * `scripts/e2e-tags.sh` proves the API. What only a browser can show is that
 * a knowledge-base item leaves the board **and stays reachable** — a person
 * who can't find it again experiences that as data loss, whatever the API
 * returns.
 */

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

test.describe("tags", () => {
  test("a tag is created from the task that needs it", async ({ page }) => {
    await signUp(page, uniqueEmail("tg"));
    const orgId = await createOrg(page, `Tags ${Date.now()}`);
    await createTask(page, orgId, "Splice the mainbrace");
    await openTask(page, orgId, "Splice the mainbrace");

    await page.getByRole("button", { name: "Add a tag" }).click();
    await page.getByRole("textbox", { name: "Find or create a tag" }).fill("Rigging");
    await page.getByRole("button", { name: new RegExp(`Create .Rigging.`) }).click();
    // Wait for the chip rather than the click: the board fetch can otherwise
    // outrun the POST that put the tag there.
    await expect(page.getByRole("button", { name: "Remove tag Rigging" })).toBeVisible();

    // …and it's on the card, not just the detail screen.
    await page.goto(`/orgs/${orgId}/tasks`);
    await expect(page.getByText("Rigging")).toBeVisible();
  });

  test("typing an existing tag finds it rather than making a twin", async ({ page }) => {
    await signUp(page, uniqueEmail("tg"));
    const orgId = await createOrg(page, `Tags ${Date.now()}`);
    await createTask(page, orgId, "First");
    await createTask(page, orgId, "Second");

    await openTask(page, orgId, "First");
    await page.getByRole("button", { name: "Add a tag" }).click();
    await page.getByRole("textbox", { name: "Find or create a tag" }).fill("Survey");
    await page.getByRole("button", { name: new RegExp(`Create .Survey.`) }).click();
    await expect(page.getByText("Survey")).toBeVisible();

    await openTask(page, orgId, "Second");
    await page.getByRole("button", { name: "Add a tag" }).click();
    // Different case. The existing tag is offered; "create" is not.
    await page.getByRole("textbox", { name: "Find or create a tag" }).fill("survey");
    await expect(page.getByRole("button", { name: new RegExp(`Create .survey.`) })).toHaveCount(0);
    await page.getByRole("button", { name: "Survey", exact: true }).click();
    // Wait for the chip, not just the click: navigating straight to the
    // vocabulary screen can outrun the POST, and then the count is 1 and the
    // failure looks like a deduplication bug.
    await expect(page.getByRole("button", { name: "Remove tag Survey" })).toBeVisible();

    // One tag in the vocabulary, used twice.
    await page.goto(`/orgs/${orgId}/structure`);
    const tags = page.getByRole("region", { name: "Tags" });
    await expect(tags.getByText("Survey")).toHaveCount(1);
    await expect(tags.getByText("2", { exact: true })).toBeVisible();
  });

  test("a tag kept off the board takes its task with it, but not out of reach", async ({
    page,
  }) => {
    await signUp(page, uniqueEmail("tg"));
    const orgId = await createOrg(page, `Tags ${Date.now()}`);
    await createTask(page, orgId, "How the winch works");
    await openTask(page, orgId, "How the winch works");
    await page.getByRole("button", { name: "Add a tag" }).click();
    await page.getByRole("textbox", { name: "Find or create a tag" }).fill("Knowledge base");
    await page.getByRole("button", { name: new RegExp(`Create .Knowledge base.`) }).click();
    // The chip's own remove button, not `getByText("Knowledge base")`: the
    // rail has a "Knowledge base" nav item of its own now, and a bare text
    // match hits both. Same trap as a toast title matching a history line —
    // assert on the one element that can only be the thing you mean.
    await expect(page.getByRole("button", { name: "Remove tag Knowledge base" })).toBeVisible();

    // Still a task at this point — the tag has to be marked first.
    await page.goto(`/orgs/${orgId}/tasks`);
    await expect(page.getByText("How the winch works")).toBeVisible();

    await page.goto(`/orgs/${orgId}/structure`);
    await page.getByRole("button", { name: "Keep Knowledge base off the board" }).click();
    await expect(page.getByRole("button", { name: /back on the board/ })).toBeVisible();

    // Off the board…
    await page.goto(`/orgs/${orgId}/tasks`);
    await expect(page.getByText("How the winch works")).toHaveCount(0);

    // …but there when you ask for the tag, and the screen says why.
    await page.getByLabel("Filter by tag").click();
    await page.getByRole("option", { name: "Knowledge base" }).click();
    await expect(page.getByText("How the winch works")).toBeVisible();
    await expect(page.getByText(/kept off the board/)).toBeVisible();

    // …and still findable by typing the tag into search, which is the thing
    // that stops "off the board" meaning "gone".
    await page.goto(`/orgs/${orgId}/tasks`);
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByRole("textbox", { name: "Search" }).pressSequentially("Knowledge");
    await expect(
      page.getByRole("dialog").getByText("How the winch works"),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("a tag comes off a task without leaving the vocabulary", async ({ page }) => {
    await signUp(page, uniqueEmail("tg"));
    const orgId = await createOrg(page, `Tags ${Date.now()}`);
    await createTask(page, orgId, "Tagged once");
    await openTask(page, orgId, "Tagged once");
    await page.getByRole("button", { name: "Add a tag" }).click();
    await page.getByRole("textbox", { name: "Find or create a tag" }).fill("Spare");
    await page.getByRole("button", { name: new RegExp(`Create .Spare.`) }).click();
    await expect(page.getByText("Spare")).toBeVisible();

    await page.getByRole("button", { name: "Remove tag Spare" }).click();
    await expect(page.getByText("Spare")).toHaveCount(0);

    // The tag is shared, so taking it off one task must not delete it.
    await page.goto(`/orgs/${orgId}/structure`);
    await expect(page.getByRole("region", { name: "Tags" }).getByText("Spare")).toBeVisible();
  });
});
