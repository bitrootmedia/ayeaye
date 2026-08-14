import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * Private notes, from both sides of the same task.
 *
 * The API suite proves the endpoint. What only two browser contexts can show
 * is that the same screen, on the same task, shows two people two different
 * notes — and never each other's.
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

test.describe("private notes", () => {
  test("two people, one task, two notes neither can see", async ({ page, browser }) => {
    const alice = uniqueEmail("noteown");
    const bob = uniqueEmail("notemem");
    await signUp(page, alice);
    const orgId = await createOrg(page, `Notes ${Date.now()}`);
    const link = await inviteMember(page, orgId, bob);
    const them = await otherPerson(browser, bob);
    await acceptInvite(them, link);

    // Alice owns it and asks Bob to act, which is how he can open it at all.
    await createTask(page, orgId, "Shared work");
    await openTask(page, orgId, "Shared work");
    await page.getByRole("button", { name: "Action required", exact: true }).click();
    await page.getByRole("option", { name: bob }).click();
    await expect(page.getByRole("heading", { name: /notified/ })).toBeVisible();

    const note = (p: Page) => p.getByRole("textbox", { name: "Your private note" });

    await note(page).fill("Alice thinks the quote is high");
    await note(page).blur();
    await expect(page.getByText(/Saved/)).toBeVisible();

    await openTask(them, orgId, "Shared work");
    // Bob's box is empty on the very same task…
    await expect(note(them)).toHaveValue("");
    await note(them).fill("Bob has done this before");
    await note(them).blur();
    await expect(them.getByText(/Saved/)).toBeVisible();

    // …and neither note appears on the other person's screen.
    await expect(them.getByText("Alice thinks the quote is high")).toHaveCount(0);
    await page.reload();
    await expect(note(page)).toHaveValue("Alice thinks the quote is high");
    await expect(page.getByText("Bob has done this before")).toHaveCount(0);

    await them.context().close();
  });

  test("a note survives a reload and is found by search", async ({ page }) => {
    await signUp(page, uniqueEmail("note"));
    const orgId = await createOrg(page, `Notes ${Date.now()}`);
    await createTask(page, orgId, "Remember this");
    await openTask(page, orgId, "Remember this");

    await page.getByRole("textbox", { name: "Your private note" }).fill("mizzenmast bracket");
    await page.getByRole("textbox", { name: "Your private note" }).blur();
    await expect(page.getByText(/Saved/)).toBeVisible();

    await page.reload();
    await expect(page.getByRole("textbox", { name: "Your private note" })).toHaveValue(
      "mizzenmast bracket",
    );

    // Searchable — the point of writing it down somewhere retrievable.
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByRole("textbox", { name: "Search" }).pressSequentially("mizzenmast");
    const hit = page.getByRole("dialog").getByText("Your private note");
    await expect(hit).toBeVisible({ timeout: 10_000 });
    // …and it takes you to the task, not to a note screen.
    await page.getByRole("dialog").getByText("Remember this").click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
  });

  test("clearing the box removes the note", async ({ page }) => {
    await signUp(page, uniqueEmail("note"));
    const orgId = await createOrg(page, `Notes ${Date.now()}`);
    await createTask(page, orgId, "Never mind");
    await openTask(page, orgId, "Never mind");

    const box = page.getByRole("textbox", { name: "Your private note" });
    await box.fill("temporary thought");
    await box.blur();
    await expect(page.getByText(/Saved/)).toBeVisible();

    await box.fill("");
    await box.blur();
    await page.reload();
    await expect(page.getByRole("textbox", { name: "Your private note" })).toHaveValue("");
    // Scoped and exact: the reminder panel on the same screen says "Only you
    // see this…", which a substring match happily finds instead.
    await expect(
      page.getByRole("region", { name: "Private note" }).getByText("Only you", { exact: true }),
    ).toBeVisible();
  });
});
