import { expect, type Page } from "@playwright/test";

/**
 * Shared plumbing for the browser tests.
 *
 * Every test makes its own accounts, because they all drive one shared dev
 * stack that accumulates data across runs. A test that assumes an empty
 * database passes once and then fails forever.
 */

/** Unique per call, so two runs a second apart don't collide on an email. */
let counter = 0;
export const uniqueEmail = (prefix: string) =>
  `${prefix}${Date.now()}x${counter++}@example.com`;

export const PASSWORD = "Testpass123";

/**
 * Register through the real sign-up form and wait until the app shell has
 * rendered.
 *
 * Going through the UI rather than posting to the API is the point: it covers
 * SuperTokens' pre-built form, the redirect afterwards, and the `GET /me` that
 * creates the local user row — the chain that has to work for a new person.
 */
export async function signUp(page: Page, email: string): Promise<string> {
  await page.goto("/auth?show=signup");
  await page.getByText("Sign Up", { exact: true }).first().waitFor();
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: /sign up/i }).click();
  await shellIsUp(page);
  return email;
}

export async function signIn(page: Page, email: string) {
  await page.goto("/auth");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await shellIsUp(page);
}

/**
 * Wait for the app shell.
 *
 * "Log out" in the rail rather than a nav link: nav labels also appear in
 * breadcrumbs, so `getByRole("link", { name: "Organisations" })` matches twice
 * the moment you're inside an organisation and Playwright's strict mode
 * (rightly) refuses to guess.
 */
export async function shellIsUp(page: Page) {
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible({
    timeout: 15_000,
  });
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await page.waitForURL(/\/auth/);
}

/** Create an organisation through the dialog and return its id from the URL. */
export async function createOrg(page: Page, name: string): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: "New organisation" }).first().click();
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForURL(/\/orgs\/[0-9a-f-]+$/);
  return page.url().split("/orgs/")[1];
}

/** Invite someone and hand back the copyable link the screen shows. */
export async function inviteMember(
  page: Page,
  orgId: string,
  email: string,
  role: "member" | "admin" | "owner" = "member",
): Promise<string> {
  // The roster moved to /people when the org's home became the dashboard.
  await page.goto(`/orgs/${orgId}/people`);
  await page.getByRole("button", { name: "Invite" }).click();
  await page.getByLabel("Email").fill(email);
  if (role !== "member") {
    // Scoped to the dialog: every row in the roster behind it also has a
    // "Role" select.
    await page.getByRole("dialog").getByLabel("Role").click();
    await page.getByRole("option", { name: role === "admin" ? "Admin" : "Owner" }).click();
  }
  await page.getByRole("button", { name: "Send invitation" }).click();
  // By role, not by label: the roster row also has a "Copy invitation link"
  // button, and getByLabel matches on substring.
  const field = page.getByRole("textbox", { name: "Invitation link" });
  await expect(field).toBeVisible();
  return (await field.inputValue()).trim();
}

export async function createProject(page: Page, orgId: string, name: string): Promise<string> {
  await page.goto(`/orgs/${orgId}/projects`);
  await page.getByRole("button", { name: "New project" }).first().click();
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("link", { name: new RegExp(name) })).toBeVisible();
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await page.waitForURL(/\/projects\/[0-9a-f-]+$/);
  return page.url().split("/projects/")[1];
}

export async function createTask(page: Page, orgId: string, title: string, project?: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("button", { name: "New task" }).first().click();
  await page.getByLabel("Title").fill(title);
  if (project) {
    // Scoped to the dialog: the board behind it has a "Filter by project"
    // select, and getByLabel matches on substring.
    await page.getByRole("dialog").getByLabel("Project").click();
    await page.getByRole("option", { name: project }).click();
  }
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByRole("link", { name: new RegExp(title) })).toBeVisible();
}
