import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * Bookmarks: the organisation's shared shelf of links.
 *
 * `scripts/e2e-bookmarks.sh` proves the three bars over HTTP — who may add,
 * who may edit, and that only an owner may pin. What only a browser can show
 * is the half that matters to a person: that a colleague sees the same shelf
 * in the same order, that the pin control is *absent* rather than present and
 * refusing, and that a reorder is a real placement rather than a local
 * rearrangement.
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

async function addBookmark(page: Page, orgId: string, url: string, description: string) {
  await page.goto(`/orgs/${orgId}/bookmarks`);
  await page.getByRole("button", { name: "Add bookmark" }).click();
  const dialog = page.locator('[data-slot="dialog-content"]');
  await dialog.getByRole("textbox", { name: "Link" }).fill(url);
  await dialog.getByRole("textbox", { name: "Description" }).fill(description);
  await dialog.getByRole("button", { name: "Add bookmark" }).click();
  await expect(page.getByRole("link", { name: description })).toBeVisible();
}

test.describe("bookmarks", () => {
  test("an empty shelf says so rather than looking broken", async ({ page }) => {
    await signUp(page, uniqueEmail("bm-empty"));
    // Named after nothing in particular: an organisation called
    // "Bookmarks …" would give the org switcher that accessible name and
    // collide with this screen's own controls.
    const orgId = await createOrg(page, `Chandlery ${Date.now()}`);
    await page.goto(`/orgs/${orgId}/bookmarks`);
    await expect(page.getByText("No bookmarks yet")).toBeVisible();
  });

  test("a link a colleague added is on your shelf too, and opens in a new tab", async ({
    page,
    browser,
  }) => {
    await signUp(page, uniqueEmail("bm-owner"));
    const orgId = await createOrg(page, `Boatyard ${Date.now()}`);

    const mateEmail = uniqueEmail("bm-mate");
    const link = await inviteMember(page, orgId, mateEmail);
    const mate = await otherPerson(browser, mateEmail);
    await acceptInvite(mate, link);

    // A plain member adds it — the shelf is not admin-only, or it stays empty.
    await addBookmark(mate, orgId, "example.com/handbook", "Crew handbook");

    await page.goto(`/orgs/${orgId}/bookmarks`);
    const shelved = page.getByRole("link", { name: "Crew handbook" });
    await expect(shelved).toBeVisible();
    // The bare hostname gained a scheme on the way in. Without it this href
    // is *relative* and navigates inside the app instead of out to the site.
    await expect(shelved).toHaveAttribute("href", "https://example.com/handbook");
    await expect(shelved).toHaveAttribute("target", "_blank");

    // The owner can edit anybody's; the member who added it can edit their
    // own. Both are resolved server-side, so the control is simply there.
    await expect(page.getByRole("button", { name: "Edit Crew handbook" })).toBeVisible();
    await expect(mate.getByRole("button", { name: "Edit Crew handbook" })).toBeVisible();
  });

  test("only the owner gets a pin control, and a pinned link leads everyone's shelf", async ({
    page,
    browser,
  }) => {
    await signUp(page, uniqueEmail("bm-pin-owner"));
    const orgId = await createOrg(page, `Marina ${Date.now()}`);

    // An *admin*, deliberately — pinning is the one thing in this product an
    // admin cannot do outside deleting the organisation, so testing it
    // against a plain member would prove the weaker claim.
    const adminEmail = uniqueEmail("bm-pin-admin");
    const link = await inviteMember(page, orgId, adminEmail, "admin");
    const admin = await otherPerson(browser, adminEmail);
    await acceptInvite(admin, link);

    await addBookmark(page, orgId, "https://example.com/rota", "Duty rota");
    await addBookmark(page, orgId, "https://example.com/prices", "Price list");

    // Absent, not disabled — the same "don't show a control that 403s" rule
    // as a task's Close button.
    await admin.goto(`/orgs/${orgId}/bookmarks`);
    await expect(admin.getByRole("link", { name: "Price list" })).toBeVisible();
    await expect(admin.getByRole("button", { name: "Pin Price list" })).toHaveCount(0);
    await expect(admin.getByRole("button", { name: "Unpin Price list" })).toHaveCount(0);
    // …but an admin can still edit and remove anybody's link.
    await expect(admin.getByRole("button", { name: "Edit Price list" })).toBeVisible();
    await expect(admin.getByRole("button", { name: "Delete Price list" })).toBeVisible();

    await page.goto(`/orgs/${orgId}/bookmarks`);
    await page.getByRole("button", { name: "Pin Price list" }).click();
    await expect(page.getByRole("heading", { name: "Pinned", exact: true })).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Pinned bookmarks" }).getByRole("link", {
        name: "Price list",
      }),
    ).toBeVisible();

    // The point of pinning: it is the *organisation's* order, not the
    // pinner's own view of it.
    await admin.reload();
    await expect(
      admin.getByRole("region", { name: "Pinned bookmarks" }).getByRole("link", {
        name: "Price list",
      }),
    ).toBeVisible();
    await expect(
      admin.getByRole("region", { name: "Bookmarks" }).getByRole("link", { name: "Duty rota" }),
    ).toBeVisible();
  });

  test("keyboard drag reorders the shelf, and the new order survives a reload", async ({
    page,
  }) => {
    await signUp(page, uniqueEmail("bm-order"));
    const orgId = await createOrg(page, `Slipway ${Date.now()}`);
    await addBookmark(page, orgId, "https://example.com/one", "First link");
    await addBookmark(page, orgId, "https://example.com/two", "Second link");

    const order = () =>
      page.getByRole("region", { name: "Bookmarks" }).getByRole("link").allInnerTexts();
    await expect
      .poll(async () => (await order()).map((t) => t.trim()))
      .toEqual(["First link", "Second link"]);

    // Keyboard-driven rather than synthetic pointer movement, the same idiom
    // (and the same reason) as `planner.spec.ts`: dnd-kit's pointer sensor is
    // flaky to script, and its collision state updates on the next animation
    // frame rather than synchronously with the keydown.
    // `exact` because `getByRole`'s name matching is substring by default:
    // this is also why the delete control says "Delete X" rather than
    // "Remove X", which literally contains "move X".
    const handle = page.getByRole("button", { name: "Move First link", exact: true });
    await handle.focus();
    await page.keyboard.press("Space");
    await page.waitForTimeout(250);
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(250);
    await page.keyboard.press("Space");

    await expect
      .poll(async () => (await order()).map((t) => t.trim()))
      .toEqual(["Second link", "First link"]);

    // A real placement, not a client-side rearrangement.
    await page.reload();
    await expect
      .poll(async () => (await order()).map((t) => t.trim()))
      .toEqual(["Second link", "First link"]);
  });

  test("a link is edited in place, on the row you are already looking at", async ({ page }) => {
    await signUp(page, uniqueEmail("bm-edit"));
    const orgId = await createOrg(page, `Harbour ${Date.now()}`);
    await addBookmark(page, orgId, "https://example.com/old", "Old wiki");

    await page.getByRole("button", { name: "Edit Old wiki" }).click();
    const description = page.getByRole("textbox", { name: "Description of Old wiki" });
    await description.fill("New wiki");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    await expect(page.getByRole("link", { name: "New wiki" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("link", { name: "New wiki" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Old wiki" })).toHaveCount(0);
  });
});
