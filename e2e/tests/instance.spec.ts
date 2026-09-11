import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, signUp, uniqueEmail } from "./helpers";

/**
 * The instance operator's panel.
 *
 * `scripts/e2e-instance.sh` proves the HTTP half — 404 for anybody without
 * the row, no route that grants one, an instance admin still 404ing on
 * somebody's organisation. What only a browser can show is the half a person
 * experiences: that the rail item is *absent* rather than present-and-
 * refusing, and — the one that matters most — that a member of a suspended
 * organisation is told what happened instead of being left on a screen whose
 * every panel silently failed to load.
 */

/** Granting is shell-only, deliberately (see models/instance_admin.py), so
 *  the test grants it the only way anybody can. That it has to shell out at
 *  all is the feature working. */
function grantAdmin(email: string) {
  // Resolved from the working directory, not `__dirname`: this package is
  // ESM, where that binding doesn't exist at all — and `scripts/e2e-browser.sh`
  // always runs the suite from `e2e/`, which is also where the config lives.
  execFileSync(path.resolve(process.cwd(), "../scripts/instance.sh"), ["grant-admin", email], {
    stdio: "pipe",
  });
}

async function otherPerson(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signUp(page, email);
  return page;
}

test.describe("instance panel", () => {
  test("an ordinary account has no Instance item, and the URL says nothing useful", async ({
    page,
  }) => {
    await signUp(page, uniqueEmail("inst-plain"));
    await createOrg(page, `Chandler ${Date.now()}`);

    // Absent, not disabled — the same "don't show a control that refuses"
    // rule as a task's Close button.
    await expect(page.getByRole("link", { name: "Instance", exact: true })).toHaveCount(0);

    // And typing the URL tells them nothing about what is behind it.
    await page.goto("/instance");
    await expect(page.getByRole("heading", { name: "Nothing here" })).toBeVisible();
  });

  test("an instance admin sees the panel, and it counts without opening anything", async ({
    page,
  }) => {
    const email = uniqueEmail("inst-admin");
    await signUp(page, email);
    // Held in a variable and matched in full: these suites leave their
    // accounts and organisations behind, so by the third run "Lighthouse"
    // alone matches four rows and fails on strict mode — the same drift
    // CLAUDE.md records for asserting on a literal slug.
    const orgName = `Lighthouse ${Date.now()}`;
    const orgId = await createOrg(page, orgName);

    grantAdmin(email);
    // `/me` is fetched on load and decides the rail item, so a reload is what
    // a real operator would do after being granted.
    await page.reload();
    await page.getByRole("link", { name: "Instance", exact: true }).click();
    await page.waitForURL("**/instance");

    // Scoped to the totals region: "Organisations" is also the rail link and
    // the tab button beneath it, so a bare `getByText` matches three things.
    const totals = page.getByRole("region", { name: "Instance totals" });
    await expect(totals.getByText("Accounts")).toBeVisible();
    await expect(totals.getByText("Organisations", { exact: true })).toBeVisible();

    // Metadata only: the panel knows the organisation exists and can count
    // it, and there is no link from here into it.
    await page.getByRole("button", { name: "Organisations" }).click();
    // Scoped to the table: the organisation's name is also in the switcher at
    // the top of the rail and in the rail's own group label.
    const listed = page.getByRole("row").filter({ hasText: orgName });
    await expect(listed).toBeVisible();
    // …and there is no way in from here. The panel counts; it does not open.
    await expect(listed.getByRole("link")).toHaveCount(0);
    await expect(page.getByRole("link", { name: new RegExp(orgId) })).toHaveCount(0);
  });

  test("suspending an organisation tells its members why, and restoring puts them back", async ({
    page,
    browser,
  }) => {
    const adminEmail = uniqueEmail("inst-susp-admin");
    await signUp(page, adminEmail);
    await createOrg(page, `Keeper ${Date.now()}`);
    grantAdmin(adminEmail);

    // A different person, with their own organisation to be locked out of.
    const memberEmail = uniqueEmail("inst-susp-member");
    const member = await otherPerson(browser, memberEmail);
    const orgName = `Slipway ${Date.now()}`;
    const orgId = await createOrg(member, orgName);
    await expect(member.getByRole("heading", { name: orgName })).toBeVisible();

    await page.goto("/instance?tab=organisations");
    await page.getByRole("textbox", { name: "Find an organisation by name or slug" }).fill(orgName);
    const row = page.getByRole("row").filter({ hasText: orgName });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Suspend" }).click();

    const dialog = page.locator('[data-slot="dialog-content"]');
    await dialog.getByRole("textbox", { name: "Reason" }).fill("Bulk signups from one IP");
    await dialog.getByRole("button", { name: "Suspend" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(row.getByText("Suspended")).toBeVisible();

    // The claim worth having a browser for: the member is told what happened
    // rather than left on a screen whose panels all quietly 403'd.
    await member.goto(`/orgs/${orgId}`);
    await expect(member.getByRole("heading", { name: `${orgName} is suspended` })).toBeVisible();
    await expect(member.getByText("Bulk signups from one IP")).toBeVisible();
    // It has not vanished — they are still a member, and it is coming back.
    await expect(member.getByText("Nothing in it has been deleted")).toBeVisible();
    // The rest of their account is untouched: this is an organisation being
    // shut, not a person being suspended.
    await member.goto("/account");
    await expect(member.getByRole("heading", { name: "Account" })).toBeVisible();

    await page.getByRole("button", { name: "Restore" }).click();
    await expect(row.getByText("Suspended")).toHaveCount(0);

    await member.goto(`/orgs/${orgId}`);
    await expect(member.getByRole("heading", { name: orgName })).toBeVisible();
  });

  test("the panel offers no way to suspend yourself, or to appoint anybody", async ({ page }) => {
    const email = uniqueEmail("inst-self");
    await signUp(page, email);
    await createOrg(page, `Beacon ${Date.now()}`);
    grantAdmin(email);
    await page.goto("/instance");

    await page.getByRole("textbox", { name: "Find an account by address or name" }).fill(email);
    const mine = page.getByRole("row").filter({ hasText: email });
    await expect(mine).toBeVisible();
    // Locking yourself out of the panel you are standing in is recoverable
    // only from a shell you may not have to hand, so the control is absent.
    await expect(mine.getByRole("button", { name: "Suspend" })).toHaveCount(0);
    // …and it says you are one, which is how a lone admin knows they are the
    // lone admin before doing anything drastic.
    await expect(mine.getByText("Instance admin")).toBeVisible();

    // Nothing here hands out the row. That is the whole reason a web panel
    // is acceptable: one stolen session cannot become a permanent foothold.
    await expect(page.getByRole("button", { name: /make.*admin/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /grant/i })).toHaveCount(0);
  });
});
