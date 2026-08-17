import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, createProject, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * The privacy behaviour, through two real browser sessions.
 *
 * The bash suites already prove the API. What only a browser can show is what
 * a *second person* actually sees on screen — that a project they weren't
 * given is absent from their list rather than merely 403-ing an XHR, and that
 * the controls they can't use aren't rendered at all.
 */

/** A second signed-in person, in their own browser context and cookie jar. */
async function otherPerson(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signUp(page, email);
  return page;
}

/** Accept an invitation by opening its link, the way a real invitee would. */
async function acceptInvite(page: Page, link: string) {
  await page.goto(link);
  await page.getByRole("button", { name: /^Join / }).click();
  await page.waitForURL(/\/orgs\/[0-9a-f-]+/);
}

test.describe("projects are private until shared", () => {
  test("a colleague cannot see a project they weren't given", async ({ page, browser }) => {
    const owner = uniqueEmail("own");
    const other = uniqueEmail("oth");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Acme ${Date.now()}`);
    const link = await inviteMember(page, orgId, other);

    const them = await otherPerson(browser, other);
    await acceptInvite(them, link);

    const projectId = await createProject(page, orgId, "Secret plans");

    // The whole product decision, on screen: they're in the organisation and
    // the project is simply not there.
    await them.goto(`/orgs/${orgId}/projects`);
    await expect(them.getByText("Secret plans")).toHaveCount(0);
    await expect(them.getByText("Nothing here yet")).toBeVisible();

    // And a direct link reads as "doesn't exist", not "forbidden".
    await them.goto(`/orgs/${orgId}/projects/${projectId}`);
    // Matched around the apostrophe: the copy uses a typographic one
    // (&rsquo;), and an ASCII ' never matches it.
    await expect(them.getByText(/have access to this project/)).toBeVisible();

    await them.context().close();
  });

  test("sharing makes it appear, at the level given", async ({ page, browser }) => {
    const owner = uniqueEmail("own");
    const other = uniqueEmail("oth");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Acme ${Date.now()}`);
    const link = await inviteMember(page, orgId, other);
    const them = await otherPerson(browser, other);
    await acceptInvite(them, link);

    const projectId = await createProject(page, orgId, "Shared plans");

    await page.getByLabel("Share with").click();
    await page.getByRole("option", { name: other }).click();
    await page.getByRole("button", { name: "Share" }).click();
    await expect(page.getByText("Shared with")).toBeVisible();

    await them.goto(`/orgs/${orgId}/projects/${projectId}`);
    await expect(them.getByText("Shared plans").first()).toBeVisible();
    // Read-only: the edit form isn't rendered, and it says why.
    await expect(them.getByText("You have view-only access")).toBeVisible();
    await expect(them.getByRole("button", { name: "Save" })).toHaveCount(0);
    // Nor can they change who else can see it.
    await expect(them.getByLabel("Share with")).toHaveCount(0);

    await them.context().close();
  });

  test("the access panel names the organisation's admins", async ({ page, browser }) => {
    // The requirement that access is stated, never inferred. Admins can see
    // every project whether or not anyone shared it, so leaving them implicit
    // would make this panel a comforting lie.
    //
    // Needs a *second* admin: the project's own owner is listed separately, so
    // in a one-person organisation the block is legitimately absent.
    const owner = uniqueEmail("own");
    const admin = uniqueEmail("adm");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Acme ${Date.now()}`);
    const link = await inviteMember(page, orgId, admin, "admin");
    const them = await otherPerson(browser, admin);
    await acceptInvite(them, link);
    await them.context().close();

    await createProject(page, orgId, "Audit me");

    await expect(page.getByText("Who can see this", { exact: true })).toBeVisible();
    await expect(
      page.getByText(/administer the organisation, so they can see every project/),
    ).toBeVisible();
    await expect(page.getByText("Organisation admin")).toBeVisible();
  });

  test("a one-person organisation is not told everyone already has access", async ({ page }) => {
    // Regression: this used to read "Everyone in this organisation already has
    // access", which flatly contradicts the promise that a project is private
    // to its owner — and it said it to someone who was on their own.
    const owner = uniqueEmail("own");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Solo ${Date.now()}`);
    await createProject(page, orgId, "Just me");

    await expect(page.getByText(/nobody else here yet/)).toBeVisible();
    await expect(page.getByText(/Everyone in this organisation already has access/)).toHaveCount(
      0,
    );
  });
});

test.describe("loose tasks", () => {
  test("a task with no project is invisible to other members", async ({ page, browser }) => {
    const owner = uniqueEmail("own");
    const other = uniqueEmail("oth");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Acme ${Date.now()}`);
    const link = await inviteMember(page, orgId, other);
    const them = await otherPerson(browser, other);
    await acceptInvite(them, link);

    await page.goto(`/orgs/${orgId}/tasks`);
    await page.getByRole("button", { name: "New task" }).first().click();
    await page.getByLabel("Title").fill("Private note");
    // The rule, said at the moment the choice is made rather than in a help
    // page nobody opens.
    await expect(page.getByText(/visible only to you/)).toBeVisible();
    await page.getByRole("button", { name: "Create", exact: true }).click();
    // By role, not by text: creating a task now also raises a toast titled
    // 'Task "Private note" was created', which matches the same text.
    await expect(page.getByRole("link", { name: "Private note" })).toBeVisible();

    await them.goto(`/orgs/${orgId}/tasks`);
    await expect(them.getByText("Private note")).toHaveCount(0);

    await them.context().close();
  });
});
