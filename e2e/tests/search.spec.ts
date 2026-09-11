import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createProject, createTask, inviteMember, signUp, uniqueEmail } from "./helpers";

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

const searchBox = (page: Page) => page.getByRole("textbox", { name: "Search" });

async function openSearch(page: Page) {
  await page.getByRole("button", { name: "Search" }).click();
  await expect(searchBox(page)).toBeFocused();
}

test.describe("search", () => {
  test("finds a task as you type, and opens it", async ({ page }) => {
    await signUp(page, uniqueEmail("srch"));
    const orgId = await createOrg(page, `Find ${Date.now()}`);
    await createProject(page, orgId, "Antifouling programme");
    await createTask(page, orgId, "Strip the old antifoul", "Antifouling programme");

    await openSearch(page);
    // Partial word — the as-you-type case.
    await searchBox(page).pressSequentially("antif");
    await expect(page.getByRole("button", { name: /Strip the old antifoul/ })).toBeVisible();

    await page.getByRole("button", { name: /Strip the old antifoul/ }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: "Strip the old antifoul" })).toBeVisible();
  });

  test("the keyboard shortcut opens it and Escape closes it", async ({ page }) => {
    await signUp(page, uniqueEmail("srch"));
    const orgId = await createOrg(page, `Keys ${Date.now()}`);
    await createTask(page, orgId, "Reachable by keyboard");

    await page.goto(`/orgs/${orgId}/tasks`);
    // Wait for the trigger: search is organisation-scoped, so the shortcut is
    // a no-op until the shell knows which organisation you're in.
    await expect(page.getByRole("button", { name: "Search" })).toBeVisible();
    await page.keyboard.press("ControlOrMeta+k");
    await expect(searchBox(page)).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(searchBox(page)).toHaveCount(0);
  });

  test("arrow keys and Enter navigate without touching the mouse", async ({ page }) => {
    await signUp(page, uniqueEmail("srch"));
    const orgId = await createOrg(page, `Keys ${Date.now()}`);
    await createTask(page, orgId, "Keyboard alpha");
    await createTask(page, orgId, "Keyboard beta");

    await openSearch(page);
    await searchBox(page).pressSequentially("Keyboard");
    await expect(page.getByRole("button", { name: /Keyboard alpha/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Keyboard beta/ })).toBeVisible();

    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
  });

  test("typing fast leaves the results matching the final query", async ({ page }) => {
    // The race this whole component is built around: one request per
    // keystroke, answers arriving out of order. Without the sequence guard, a
    // slow answer for "ant" lands after the fast one for "antifoul" and the
    // list ends up showing results for something the person already finished
    // typing. Invisible locally, constant on a real connection.
    await signUp(page, uniqueEmail("srch"));
    const orgId = await createOrg(page, `Race ${Date.now()}`);
    await createTask(page, orgId, "Antifoul stripping");
    await createTask(page, orgId, "Anchor windlass service");

    // Slow the early requests down so they'd overtake if unguarded.
    await page.route("**/search?q=**", async (route) => {
      const q = new URL(route.request().url()).searchParams.get("q") ?? "";
      if (q.length <= 3) await new Promise((r) => setTimeout(r, 800));
      await route.continue();
    });

    await openSearch(page);
    await searchBox(page).pressSequentially("Antifoul", { delay: 30 });
    await expect(page.getByRole("button", { name: /Antifoul stripping/ })).toBeVisible();

    // The short-query result must never win. Waiting past the injected delay
    // is the point: this is what a missing guard would look like.
    await page.waitForTimeout(1200);
    await expect(page.getByRole("button", { name: /Anchor windlass/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Antifoul stripping/ })).toBeVisible();
  });

  test("it only finds what you're allowed to see", async ({ page, browser }) => {
    // The same guarantee the HTTP suite checks, but through the box a person
    // actually types into — where a leak would be most visible and most
    // damaging.
    const owner = uniqueEmail("own");
    const other = uniqueEmail("oth");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Private ${Date.now()}`);
    const link = await inviteMember(page, orgId, other);
    const them = await otherPerson(browser, other);
    await acceptInvite(them, link);

    await createProject(page, orgId, "Confidential refit");
    await createTask(page, orgId, "Confidential hull survey", "Confidential refit");

    await openSearch(them);
    await searchBox(them).pressSequentially("Confidential");
    await expect(them.getByText(/Nothing matches/)).toBeVisible();
    await expect(them.getByText(/only covers what you have access to/)).toBeVisible();

    // The owner finds both.
    await openSearch(page);
    await searchBox(page).pressSequentially("Confidential");
    await expect(page.getByRole("button", { name: /Confidential hull survey/ })).toBeVisible();
    // Exact: the task's accessible name includes its project as context, so a
    // loose regex matches both rows.
    await expect(
      page.getByRole("button", { name: "Confidential refit", exact: true }),
    ).toBeVisible();

    await them.context().close();
  });

  test("an article hit opens the article, not a task URL", async ({ page }) => {
    await signUp(page, uniqueEmail("srch-kb"));
    const orgId = await createOrg(page, `Manual ${Date.now()}`);

    // Set up through the API rather than by clicking through the knowledge
    // base: this test is about where a *search hit* goes, and the KB's own
    // creation flow is somebody else's test. `page.request` shares this
    // context's cookie jar, so it is the same signed-in person either way.
    const api = async (url: string, method: "post" | "patch", data: object) => {
      const res = await page.request.fetch(`/api${url}`, { method, data });
      expect(res.ok()).toBe(true);
      return res.json();
    };
    const book = await api(`/organisations/${orgId}/kb/books`, "post", { name: "Runbooks" });
    const article = await api(`/organisations/${orgId}/kb/books/${book.id}/articles`, "post", {
      title: "Winterising the engine",
    });
    // Born private; published so it is an ordinary hit rather than one only
    // its owner can see.
    await api(`/organisations/${orgId}/kb/articles/${article.id}/private`, "patch", {
      is_private: false,
    });

    await page.goto(`/orgs/${orgId}/tasks`);
    await openSearch(page);
    await searchBox(page).pressSequentially("Winteris");
    const hit = page.getByRole("button", { name: /Winterising the engine/ });
    await expect(hit).toBeVisible();
    await hit.click();

    // The regression this pins: `articles_stmt` was added to `search()` when
    // the knowledge base shipped and the palette's own routing never heard
    // about it, so every article hit went to `/tasks/<an article id>` and
    // landed on "task not found".
    await page.waitForURL(new RegExp(`/kb/articles/${article.id}$`));
    await expect(page.getByRole("heading", { name: "Winterising the engine" })).toBeVisible();
  });

  test("a typo still finds it", async ({ page }) => {
    await signUp(page, uniqueEmail("srch"));
    const orgId = await createOrg(page, `Fuzzy ${Date.now()}`);
    await createTask(page, orgId, "Order two-part epoxy");

    await openSearch(page);
    await searchBox(page).pressSequentially("epoxi");
    await expect(page.getByRole("button", { name: /Order two-part epoxy/ })).toBeVisible();
  });

  test("closed work is findable, and shown as closed", async ({ page }) => {
    await signUp(page, uniqueEmail("srch"));
    const orgId = await createOrg(page, `Closed ${Date.now()}`);
    await createTask(page, orgId, "Winterise the engine");
    await page.getByRole("link", { name: /Winterise the engine/ }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
    await page.getByRole("button", { name: "Close task" }).click();
    await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();

    await openSearch(page);
    await searchBox(page).pressSequentially("Winterise");
    const hit = page.getByRole("button", { name: /Winterise the engine/ });
    await expect(hit).toBeVisible();
    // Struck through rather than hidden: people search for finished work
    // precisely because they can't remember where it went.
    await expect(hit.locator(".line-through")).toBeVisible();
  });
});
