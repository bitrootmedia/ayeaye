import { expect, test, type Page } from "@playwright/test";

import {
  createOrg,
  createTask,
  inviteMember,
  signUp,
  uniqueEmail,
} from "./helpers";

/**
 * The task description editor.
 *
 * The three things worth proving are the three that are easy to get wrong:
 * formatting survives a round trip, a pasted picture becomes a task
 * attachment with a *fresh* URL, and search matches the prose rather than the
 * markup wrapped around it.
 */

const PNG =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

const body = (page: Page) => page.locator(".ProseMirror").first();

test.describe("rich descriptions", () => {
  test("formatting survives a save and a reload", async ({ page }) => {
    await signUp(page, uniqueEmail("rt"));
    const orgId = await createOrg(page, `Rich ${Date.now()}`);
    await createTask(page, orgId, "Written up");
    await openTask(page, orgId, "Written up");

    await body(page).click();
    await page.keyboard.type("The hull needs ");
    await page.getByRole("button", { name: "Bold" }).click();
    await page.keyboard.type("two coats");
    await page.getByRole("button", { name: "Bold" }).click();
    await page.keyboard.press("Enter");
    await page.getByRole("button", { name: "Bullet list" }).click();
    await page.keyboard.type("primer");
    await page.keyboard.press("Enter");
    await page.keyboard.type("topcoat");

    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();

    await page.reload();
    await expect(body(page).locator("strong")).toHaveText("two coats");
    await expect(body(page).locator("li")).toHaveCount(2);
  });

  test("clicking the toolbar does not swallow the next character", async ({ page }) => {
    // Clicking a button used to blur the editor; the chain's `.focus()` put it
    // back a tick later, and whatever you typed in between was lost. It cost
    // the first letter of every word anybody emphasised.
    await signUp(page, uniqueEmail("rt"));
    const orgId = await createOrg(page, `Rich ${Date.now()}`);
    await createTask(page, orgId, "No lost letters");
    await openTask(page, orgId, "No lost letters");

    await body(page).click();
    await page.keyboard.type("the ");
    await page.getByRole("button", { name: "Inline code" }).click();
    await page.keyboard.type("NMEA2000");
    await expect(body(page).locator("code")).toHaveText("NMEA2000");
  });

  test("a code block is highlighted and keeps its language", async ({ page }) => {
    await signUp(page, uniqueEmail("rt"));
    const orgId = await createOrg(page, `Rich ${Date.now()}`);
    await createTask(page, orgId, "With code");
    await openTask(page, orgId, "With code");

    await body(page).click();
    await page.getByRole("button", { name: "Code block" }).click();
    await page.getByLabel("Code language").selectOption("python");
    await page.keyboard.type("def hello():\n    return 'world'");

    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();

    await page.reload();
    const code = body(page).locator("pre code");
    await expect(code).toHaveClass(/language-python/);
    // Highlighted, not just monospaced: lowlight emits hljs token spans.
    await expect(code.locator(".hljs-keyword").first()).toBeVisible();
  });

  test("a picture is visible the moment it uploads, before any save", async ({ page }) => {
    // The body stores only the attachment id and the server adds the `src` on
    // read — so before the first save there is nothing to display unless the
    // editor keeps the URL that `confirm` handed back. It didn't, and a
    // freshly-pasted screenshot showed as its own alt text: an upload that
    // worked, looking exactly like one that hadn't.
    await signUp(page, uniqueEmail("rt"));
    const orgId = await createOrg(page, `Rich ${Date.now()}`);
    await createTask(page, orgId, "Instant picture");
    await openTask(page, orgId, "Instant picture");

    await page.getByLabel("Picture to add").setInputFiles({
      name: "sketch.png",
      mimeType: "image/png",
      buffer: Buffer.from(PNG, "base64"),
    });

    const image = body(page).locator("img").first();
    await expect(image).toBeVisible({ timeout: 15_000 });
    await expect(image).toHaveAttribute("src", /\/media\/tasks\//);
    // Rendered, not merely present: a broken image is visible and has a src
    // too, and that is the state being guarded against.
    await expect
      .poll(() => image.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0);
  });

  test("a picture becomes a task attachment, with a URL minted at read time", async ({
    page,
  }) => {
    await signUp(page, uniqueEmail("rt"));
    const orgId = await createOrg(page, `Rich ${Date.now()}`);
    await createTask(page, orgId, "Illustrated");
    await openTask(page, orgId, "Illustrated");

    await page.getByLabel("Picture to add").setInputFiles({
      name: "sketch.png",
      mimeType: "image/png",
      buffer: Buffer.from(PNG, "base64"),
    });
    await expect(body(page).locator("img")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();

    await page.reload();
    const image = body(page).locator("img").first();
    // The body stores only the id; the src is put on at read time, and it is
    // a presigned URL from our own origin.
    await expect(image).toHaveAttribute("data-attachment-id", /[0-9a-f-]{36}/);
    await expect(image).toHaveAttribute("src", /\/media\/tasks\/.*X-Amz-Signature/);

    // …and the same picture is a file on the task, without a second upload.
    await expect(
      page.getByRole("region", { name: "Files" }).getByRole("button", { name: "Open sketch.png" }),
    ).toBeVisible();
  });

  test("search finds the words, not the tags", async ({ page }) => {
    await signUp(page, uniqueEmail("rt"));
    const orgId = await createOrg(page, `Rich ${Date.now()}`);
    await createTask(page, orgId, "Findable");
    await openTask(page, orgId, "Findable");

    await body(page).click();
    await page.keyboard.type("mizzenmast repair");
    await page.getByRole("button", { name: "Bold" }).click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();

    await page.getByRole("button", { name: "Search" }).click();
    await page.getByRole("textbox", { name: "Search" }).pressSequentially("mizzenmast");
    await expect(page.getByRole("dialog").getByText("Findable")).toBeVisible({ timeout: 10_000 });
    // The snippet is prose. Storing HTML and searching it raw would put
    // markup in front of people and match every task on the word "strong".
    await expect(page.getByRole("dialog").getByText(/</)).toHaveCount(0);
  });

  test("a read-only viewer sees the formatting, not an editor", async ({ page }) => {
    await signUp(page, uniqueEmail("rt"));
    const orgId = await createOrg(page, `Rich ${Date.now()}`);
    await createTask(page, orgId, "Read only later");
    await openTask(page, orgId, "Read only later");
    await body(page).click();
    await page.keyboard.type("Plain enough");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();
    await expect(page.getByText("Plain enough")).toBeVisible();
  });
});

/**
 * Versions — recovering a description somebody saved over.
 *
 * Reported: "sometimes somebody overwrites a description and it's a problem
 * not being able to recover." The HTTP suite
 * (`scripts/e2e-task-revisions.sh`) proves what the endpoints store; what
 * only a browser can show is that the person who lost the text can actually
 * get it back from the screen they lost it on.
 */
test.describe("versions", () => {
  test("a description saved over can be read back and restored", async ({ page }) => {
    await signUp(page, uniqueEmail("ver"));
    const orgId = await createOrg(page, `Recover ${Date.now()}`);
    await createTask(page, orgId, "Windlass service");
    await openTask(page, orgId, "Windlass service");

    await body(page).click();
    await page.keyboard.type("Order the bearing housing from the yard.");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();

    // Somebody saves straight over it, which is the whole reported problem.
    await body(page).click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type("wrong task, sorry");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();
    await expect(body(page)).toHaveText("wrong task, sorry");

    await page.getByRole("button", { name: "Versions", exact: true }).click();
    const dialog = page.locator('[data-slot="dialog-content"]');
    // Two rows, and they are the reason each one carries a snippet: the task
    // was created with no description, so the first save replaced an empty
    // one — same title, same author, same minute as the second. Without the
    // snippet these two are indistinguishable, and picking the right one is
    // a guessing game rather than recovery.
    await expect(dialog.getByText(/replaced by/)).toHaveCount(2);
    await expect(dialog.getByText("No description")).toBeVisible();

    // Readable before restoring: recovering by copy-paste is a legitimate
    // outcome, and it's the only one available to a read-only viewer.
    await dialog.getByText("Order the bearing housing from the yard.").click();
    await expect(dialog.getByRole("heading", { name: "Earlier version" })).toBeVisible();
    await expect(dialog.getByText("Order the bearing housing from the yard.")).toBeVisible();

    await dialog.getByRole("button", { name: "Restore this version" }).click();
    await expect(page.getByRole("heading", { name: "Restored" })).toBeVisible();
    await expect(body(page)).toHaveText("Order the bearing housing from the yard.");

    // The restore is itself undoable — the text it replaced is now a version.
    await page.getByRole("button", { name: "Versions", exact: true }).click();
    await expect(page.locator('[data-slot="dialog-content"]').getByText("wrong task, sorry")).toBeVisible();
  });

  test("an unedited task says so rather than showing an empty list", async ({ page }) => {
    await signUp(page, uniqueEmail("ver"));
    const orgId = await createOrg(page, `Recover ${Date.now()}`);
    await createTask(page, orgId, "Nothing written yet");
    await openTask(page, orgId, "Nothing written yet");

    await page.getByRole("button", { name: "Versions", exact: true }).click();
    await expect(page.locator('[data-slot="dialog-content"]').getByText(/Nothing has been saved over yet/)).toBeVisible();
  });

  test("a read-only colleague can read a lost version but not restore it", async ({
    page,
    browser,
  }) => {
    const owner = uniqueEmail("vown");
    const other = uniqueEmail("voth");
    await signUp(page, owner);
    const orgId = await createOrg(page, `Recover ${Date.now()}`);
    const link = await inviteMember(page, orgId, other);
    const them = await browser.newContext().then((c) => c.newPage());
    await signUp(them, other);
    await them.goto(link);
    await them.getByRole("button", { name: /^Join / }).click();
    await them.waitForURL(/\/orgs\/[0-9a-f-]+/);

    await createTask(page, orgId, "Winch overhaul");
    await openTask(page, orgId, "Winch overhaul");
    await body(page).click();
    await page.keyboard.type("The colleague's own notes, about to be lost.");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();
    await body(page).click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type("gone");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();

    // Shared read-only — the same AccessPanel a project uses, on the task.
    await page.getByLabel("Share with").click();
    await page.getByRole("option", { name: other }).click();
    await page.getByRole("button", { name: "Share" }).click();
    await expect(page.getByText("Shared with")).toBeVisible();

    const url = page.url();
    await them.goto(url);
    await them.getByRole("button", { name: "Versions", exact: true }).click();
    const dialog = them.locator('[data-slot="dialog-content"]');
    // They can read it back — copy-paste is a real recovery, and the only
    // one available to somebody without write access.
    await expect(dialog.getByText("The colleague's own notes, about to be lost.")).toBeVisible();
    // …and they are not offered a restore that would 403 on the server.
    await expect(dialog.getByRole("button", { name: "Restore" })).toHaveCount(0);

    await them.context().close();
  });
});
