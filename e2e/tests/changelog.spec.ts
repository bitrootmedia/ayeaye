import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * The changelog: the organisation's dated record of what happened.
 *
 * `scripts/e2e-changelog.sh` proves the two bars over HTTP — any member may
 * record one, and only whoever recorded it (or an org admin) may change it.
 * What only a browser can show is the half that matters to a person: that a
 * colleague sees the same log, that the controls on somebody else's entry are
 * *absent* rather than present and refusing, and that an entry lands under the
 * date it happened rather than the date it was typed.
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

async function addEntry(page: Page, orgId: string, what: string, when?: string) {
  await page.goto(`/orgs/${orgId}/changelog`);
  await page.getByRole("button", { name: "Add entry" }).first().click();
  const dialog = page.locator('[data-slot="dialog-content"]');
  await dialog.getByRole("textbox", { name: "What happened" }).fill(what);
  // `getByLabel` matches on substring, so "Date" would also find "Date for
  // …" on an open row editor — exact, per CLAUDE.md's own note.
  if (when) await dialog.getByLabel("Date", { exact: true }).fill(when);
  await dialog.getByRole("button", { name: "Add entry" }).click();
  // Wait for the dialog to actually go before looking for the entry: until
  // it does, the text is also sitting in the textarea it was just typed
  // into, and `getByText` matches that too. The click only waits for the
  // click — what its handler does afterwards keeps running.
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(what)).toBeVisible();
}

test.describe("changelog", () => {
  test("an empty log says so rather than looking broken", async ({ page }) => {
    await signUp(page, uniqueEmail("cl-empty"));
    // Named after nothing in particular: an organisation called
    // "Changelog …" would give the org switcher that accessible name and
    // collide with this screen's own controls.
    const orgId = await createOrg(page, `Boatshed ${Date.now()}`);
    await page.goto(`/orgs/${orgId}/changelog`);
    await expect(page.getByText("Nothing recorded yet")).toBeVisible();
  });

  test("an entry a colleague recorded is on your log too, under the date it happened", async ({
    page,
    browser,
  }) => {
    await signUp(page, uniqueEmail("cl-owner"));
    const orgId = await createOrg(page, `Drydock ${Date.now()}`);

    const mateEmail = uniqueEmail("cl-mate");
    const link = await inviteMember(page, orgId, mateEmail);
    const mate = await otherPerson(browser, mateEmail);
    await acceptInvite(mate, link);

    // A plain member records it — a log only an admin may write to is a log
    // that stays empty.
    await addEntry(mate, orgId, "BingAds version lift", "2026-03-02");

    await page.goto(`/orgs/${orgId}/changelog`);
    await expect(page.getByText("BingAds version lift")).toBeVisible();
    // Filed under the date it *happened*, not the date it was typed — the
    // two dates are the whole point of the feature.
    await expect(page.getByRole("heading", { name: "2026-03-02" })).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Changelog for 2026-03-02" }).getByText("BingAds"),
    ).toBeVisible();
    // And who wrote it down, which is the third field and the one a log is
    // useless without a month later.
    await expect(page.getByText(`Added by ${mateEmail}`)).toBeVisible();
  });

  test("somebody else's entry offers no controls, and yours offers both", async ({
    page,
    browser,
  }) => {
    await signUp(page, uniqueEmail("cl-a"));
    const orgId = await createOrg(page, `Chandler ${Date.now()}`);

    const mateEmail = uniqueEmail("cl-b");
    const link = await inviteMember(page, orgId, mateEmail);
    const mate = await otherPerson(browser, mateEmail);
    await acceptInvite(mate, link);

    // Two *plain* members would be the sharper test of the edit bar, but the
    // absence that matters most is a member looking at an owner's entry.
    await addEntry(page, orgId, "Rebuilt the winch", "2026-02-10");
    await addEntry(mate, orgId, "Reordered the antifoul", "2026-02-11");

    // Absent, not disabled — the same "don't show a control that 403s" rule
    // as a task's Close button.
    await mate.goto(`/orgs/${orgId}/changelog`);
    await expect(mate.getByText("Rebuilt the winch")).toBeVisible();
    await expect(mate.getByRole("button", { name: "Edit Rebuilt the winch" })).toHaveCount(0);
    await expect(mate.getByRole("button", { name: "Delete Rebuilt the winch" })).toHaveCount(0);
    // Their own, they can change.
    await expect(mate.getByRole("button", { name: "Edit Reordered the antifoul" })).toBeVisible();

    // The owner is an admin, so the escape hatch applies to anybody's.
    await page.goto(`/orgs/${orgId}/changelog`);
    await expect(page.getByRole("button", { name: "Edit Reordered the antifoul" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete Reordered the antifoul" })).toBeVisible();
  });

  test("correcting an entry's date moves it to the right day", async ({ page }) => {
    await signUp(page, uniqueEmail("cl-edit"));
    const orgId = await createOrg(page, `Slip ${Date.now()}`);
    await addEntry(page, orgId, "Mast unstepped", "2026-04-01");

    await page.getByRole("button", { name: "Edit Mast unstepped" }).click();
    await page.getByLabel("Date for Mast unstepped").fill("2026-04-08");
    await page.getByLabel("Description of Mast unstepped").fill("Mast unstepped and stored");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    // A redated entry belongs under a different heading, which is why the
    // save reloads rather than patching the row where it sits.
    await expect(page.getByRole("heading", { name: "2026-04-08" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "2026-04-01" })).toHaveCount(0);
    await expect(page.getByText("Mast unstepped and stored")).toBeVisible();
    // The edit is marked as one: a corrected log entry that looks untouched
    // is a log that quietly rewrote itself.
    await expect(page.getByText("· edited")).toBeVisible();
  });

  test("⌘K finds an entry and lands on a log that contains it", async ({ page }) => {
    await signUp(page, uniqueEmail("cl-search"));
    const orgId = await createOrg(page, `Harbour ${Date.now()}`);
    // Two entries, so "landed on a filtered log" is a different claim from
    // "landed on the log" — with one entry the two are indistinguishable.
    await addEntry(page, orgId, "BingAds version lift", "2026-01-05");
    await addEntry(page, orgId, "Repainted the shed", "2026-01-06");

    await page.goto(`/orgs/${orgId}/tasks`);
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByRole("textbox", { name: "Search" }).pressSequentially("BingAds");
    const hit = page.getByRole("button", { name: /BingAds version lift/ });
    await expect(hit).toBeVisible();
    await hit.click();

    // The palette carries the query into the URL precisely so the row it
    // matched is on the page it lands on — a five-year log would otherwise
    // open at page one with the hit nowhere in sight.
    await page.waitForURL(/\/changelog\?q=BingAds/);
    await expect(page.getByText("BingAds version lift")).toBeVisible();
    await expect(page.getByText("Repainted the shed")).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Filter the changelog" })).toHaveValue(
      "BingAds",
    );

    // Clearing the filter puts the whole log back, and takes the query out
    // of the URL with it.
    await page.getByRole("textbox", { name: "Filter the changelog" }).fill("");
    await expect(page.getByText("Repainted the shed")).toBeVisible();
    await expect(page).not.toHaveURL(/q=/);
  });

  test("deleting your own entry takes it off everybody's log", async ({ page, browser }) => {
    await signUp(page, uniqueEmail("cl-del"));
    const orgId = await createOrg(page, `Quay ${Date.now()}`);

    const mateEmail = uniqueEmail("cl-del-mate");
    const link = await inviteMember(page, orgId, mateEmail);
    const mate = await otherPerson(browser, mateEmail);
    await acceptInvite(mate, link);

    await addEntry(page, orgId, "Recorded by mistake", "2026-05-05");
    await mate.goto(`/orgs/${orgId}/changelog`);
    await expect(mate.getByText("Recorded by mistake")).toBeVisible();

    await page.getByRole("button", { name: "Delete Recorded by mistake" }).click();
    await expect(page.getByText("Recorded by mistake")).toHaveCount(0);

    await mate.reload();
    await expect(mate.getByText("Recorded by mistake")).toHaveCount(0);
    await expect(mate.getByText("Nothing recorded yet")).toBeVisible();
  });
});
