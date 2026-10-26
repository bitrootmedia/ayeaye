import { expect, test, type Browser, type Page } from "@playwright/test";

import { createOrg, inviteMember, signUp, uniqueEmail } from "./helpers";

/**
 * Facts and recall, as people see them.
 *
 * `scripts/e2e-recall.sh` proves the rules over HTTP — who may write, that
 * recall finds by meaning, that access is in the statement. What only a
 * browser shows: that a colleague with read access sees the fact and none of
 * the controls, that a ⌘K hit on a fact lands on its book with that fact
 * picked out (a fact has no screen of its own, so this is the link most
 * likely to go nowhere), and that superseding strikes it through rather than
 * making it vanish.
 */

async function otherPerson(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signUp(page, email);
  return page;
}

async function newBook(page: Page, orgId: string, name: string): Promise<string> {
  await page.goto(`/orgs/${orgId}/kb`);
  await page.getByRole("button", { name: "New book" }).first().click();
  const dialog = page.locator('[data-slot="dialog-content"]');
  await dialog.getByRole("textbox", { name: "Name" }).fill(name);
  await dialog.getByRole("button", { name: "Create" }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await page.waitForURL(/\/kb\/books\/[0-9a-f-]+$/);
  return page.url().split("/").pop()!;
}

async function addFact(page: Page, body: string) {
  const box = page.getByRole("textbox", { name: "New fact" });
  await box.fill(body);
  await page.getByRole("button", { name: "Add fact" }).click();
  // The box emptying is the effect, not the text appearing: `getByText`
  // also matches what is still sitting in the textarea, so it passes before
  // the POST has landed — and the next fill is then wiped by this one's
  // reset. The changelog's own dialog note, in a box that has no dialog.
  await expect(box).toHaveValue("");
  await expect(page.locator("li[id^='fact-']").filter({ hasText: body })).toBeVisible();
}

test.describe("facts and recall", () => {
  test("a reader sees a colleague's fact, and none of its controls", async ({
    page,
    browser,
  }) => {
    await signUp(page, uniqueEmail("rc-owner"));
    const orgId = await createOrg(page, `Slipway ${Date.now()}`);
    const bookId = await newBook(page, orgId, "Gotchas");
    const bookUrl = `/orgs/${orgId}/kb/books/${bookId}`;
    const fact = "Passbolt: reload nginx after certbot renews, or it serves the old certificate.";
    await addFact(page, fact);
    await expect(page.getByRole("button", { name: `Edit ${fact.slice(0, 40)}` })).toBeVisible();

    const mateEmail = uniqueEmail("rc-mate");
    const link = await inviteMember(page, orgId, mateEmail);
    const mate = await otherPerson(browser, mateEmail);
    await mate.goto(link);
    await mate.getByRole("button", { name: /^Join / }).click();
    await mate.waitForURL(/\/orgs\/[0-9a-f-]+/);

    // Not shared yet: the book, and so its facts, don't exist for them.
    await mate.goto(bookUrl);
    await expect(mate.getByText(/have access to this book/)).toBeVisible();

    // Share it read-only, through the same Access panel as everything else.
    await page.goto(bookUrl);
    await page.getByLabel("Share with").click();
    await page.getByRole("option", { name: mateEmail }).click();
    // Exact: the "Share with" picker's trigger is a button too, and a
    // substring match on "Share" clicked that instead of sharing.
    await page.getByRole("button", { name: "Share", exact: true }).click();
    await expect(page.getByRole("heading", { name: `Shared with ${mateEmail}` })).toBeVisible();

    await mate.reload();
    await expect(mate.getByText(fact)).toBeVisible();
    await expect(mate.getByRole("textbox", { name: "New fact" })).toHaveCount(0);
    await expect(mate.getByRole("button", { name: `Edit ${fact.slice(0, 40)}` })).toHaveCount(0);
  });

  test("a ⌘K hit on a fact lands on its book with the fact picked out", async ({ page }) => {
    await signUp(page, uniqueEmail("rc-search"));
    const orgId = await createOrg(page, `Pontoon ${Date.now()}`);
    const bookId = await newBook(page, orgId, "Runbook notes");
    const fact = "Metabase sync needs statement_timeout raised on the read replica.";
    await addFact(page, fact);

    await page.goto(`/orgs/${orgId}/tasks`);
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByRole("textbox", { name: "Search" }).pressSequentially("statement_timeout");
    await page.getByRole("button", { name: /Metabase sync/ }).click();
    await page.waitForURL(new RegExp(`/kb/books/${bookId}\\?fact=`));
    await expect(page.locator("li[id^='fact-']").filter({ hasText: fact })).toHaveClass(
      /bg-accent/,
    );
  });

  test("superseding strikes a fact through rather than making it vanish", async ({ page }) => {
    await signUp(page, uniqueEmail("rc-sup"));
    const orgId = await createOrg(page, `Mooring ${Date.now()}`);
    await newBook(page, orgId, "Decisions");
    const fact = "Invoices go out on the first calendar day of the month.";
    await addFact(page, fact);

    await page.getByRole("button", { name: `Supersede ${fact.slice(0, 40)}` }).click();
    await expect(page.getByText(fact)).toHaveCount(0);

    await page.getByRole("button", { name: "Show superseded" }).click();
    const row = page.getByText(fact);
    await expect(row).toBeVisible();
    await expect(row).toHaveClass(/line-through/);

    await page.getByRole("button", { name: `Restore ${fact.slice(0, 40)}` }).click();
    await expect(page.getByText(fact)).not.toHaveClass(/line-through/);
  });

  test("recall answers from the knowledge base, and the question is in the URL", async ({
    page,
  }) => {
    await signUp(page, uniqueEmail("rc-ask"));
    const orgId = await createOrg(page, `Harbour ${Date.now()}`);
    await newBook(page, orgId, "Gotchas");
    const fact = "Leadflow celery workers stop consuming after a Redis restart; restart them.";
    await addFact(page, fact);

    await page.goto(`/orgs/${orgId}/kb`);
    await page.getByRole("textbox", { name: "Ask what the team knows" }).fill("celery workers");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/recall=celery/);
    const answer = page.getByRole("region", { name: "Recall" }).getByRole("link", {
      name: /Leadflow celery/,
    });
    // Generous: the question is embedded before it is compared, and on a dev
    // stack that queues behind the sweep backfilling every other suite's tasks.
    await expect(answer).toBeVisible({ timeout: 20_000 });
    await answer.click();
    await page.waitForURL(/\/kb\/books\/[0-9a-f-]+\?fact=/);
    await expect(page.getByText(fact)).toBeVisible();
  });
});
