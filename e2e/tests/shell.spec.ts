import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

/**
 * The shell itself — the rail, the switcher, and what happens when a render
 * throws.
 *
 * Every one of these is a bug that reached a person before it reached a test:
 * 100 browser tests and not one of them had ever *opened* the organisation
 * switcher, so a menu label in the wrong place blanked the entire app the
 * first time anybody clicked it.
 */

/** Nothing rendered at all — the symptom of an uncaught render error. */
async function appIsAlive(page: Page) {
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await expect(page.getByText("This screen stopped working")).toHaveCount(0);
}

test.describe("the shell", () => {
  test("the organisation switcher opens", async ({ page }) => {
    await signUp(page, uniqueEmail("sh"));
    const orgId = await createOrg(page, `Shell ${Date.now()}`);
    await page.goto(`/orgs/${orgId}/tasks`);

    await page.locator("[data-slot='dropdown-menu-trigger']").first().click();
    await expect(page.getByRole("menu")).toBeVisible();
    await expect(page.getByRole("menuitem", { name: /New organisation/ })).toBeVisible();
    // The app is still there. It used to not be.
    await appIsAlive(page);
  });

  test("switching organisation from the menu goes there", async ({ page }) => {
    await signUp(page, uniqueEmail("sh"));
    const first = await createOrg(page, `Alpha ${Date.now()}`);
    const second = await createOrg(page, `Beta ${Date.now()}`);
    await page.goto(`/orgs/${first}`);

    await page.locator("[data-slot='dropdown-menu-trigger']").first().click();
    await page.getByRole("menuitem", { name: /^Beta / }).click();
    await page.waitForURL(new RegExp(`/orgs/${second}`));
    await appIsAlive(page);
  });

  test("the rail keeps its organisation on the personal screens", async ({ page }) => {
    // Losing the whole section the moment you glance at a list leaves no way
    // back except clicking through it — and the switcher went on claiming an
    // organisation the nav no longer showed.
    await signUp(page, uniqueEmail("sh"));
    const orgId = await createOrg(page, `Shell ${Date.now()}`);
    await createTask(page, orgId, "Something");

    for (const path of ["/", "/notifications", "/reminders", "/account"]) {
      await page.goto(path);
      await expect(page.getByRole("link", { name: "Tasks" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Projects" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();
      // …and it still goes where it says.
      await page.getByRole("link", { name: "Tasks" }).click();
      await page.waitForURL(new RegExp(`/orgs/${orgId}/tasks`));
    }
  });

  test("search works from the organisations list", async ({ page }) => {
    // If the rail says you're working in an organisation, the shortcut that
    // searches it has to work — otherwise ⌘K silently does nothing.
    await signUp(page, uniqueEmail("sh"));
    const orgId = await createOrg(page, `Shell ${Date.now()}`);
    await createTask(page, orgId, "Findable thing");

    await page.goto("/");
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByRole("textbox", { name: "Search" }).pressSequentially("Findable");
    await expect(page.getByRole("dialog").getByText("Findable thing")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("a render error shows a way out, not a white page", async ({ page }) => {
    // Through a route that genuinely throws (dev-only, see main.tsx), because
    // a boundary asserted to be *absent* is a test that cannot fail — which
    // is how the switcher crash survived a hundred green tests.
    await signUp(page, uniqueEmail("sh"));
    await page.goto("/__crash");

    await expect(page.getByText("This screen stopped working")).toBeVisible();
    await expect(page.getByText(/deliberate crash/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Reload" })).toBeVisible();

    // And the way out works.
    await page.getByRole("button", { name: "Start again" }).click();
    await expect(page.getByRole("button", { name: "Log out" })).toBeVisible({ timeout: 15_000 });
  });

  test("an unknown URL shows a way home, not a blank page", async ({ page }) => {
    // Without a wildcard route, a URL matching nothing in the tree matches
    // nothing at all — not even Root — and the whole page renders blank: no
    // rail, no message, nothing to click. That's the bug this pins.
    await signUp(page, uniqueEmail("sh"));
    await page.goto("/this-page-does-not-exist");

    // The shell is still here — this is a 404 inside the app, not instead of it.
    await appIsAlive(page);
    await expect(page.getByText("Nothing here")).toBeVisible();

    await page.getByRole("button", { name: "Take me home" }).click();
    await page.waitForURL("/");
    await appIsAlive(page);
  });
});
