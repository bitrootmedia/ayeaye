import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

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
