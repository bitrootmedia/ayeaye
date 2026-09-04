import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, openFilesPanel, signUp, uniqueEmail } from "./helpers";

/**
 * Dropping a file onto an upload panel.
 *
 * Playwright has no "drag a file from the desktop" gesture, so the drop is
 * built the way the browser would: a real `DataTransfer` carrying a real
 * `File`, dispatched as trusted-shaped events at the element. That exercises
 * everything except the OS drag itself — the depth counter, the
 * `preventDefault` on dragover, and the upload the drop kicks off.
 */

const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

/** Build a DataTransfer holding one file, in the page. */
async function fileTransfer(page: Page, name: string, type: string, base64: string) {
  return page.evaluateHandle(
    ({ name, type, base64 }) => {
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
      const dt = new DataTransfer();
      dt.items.add(new File([bytes], name, { type }));
      return dt;
    },
    { name, type, base64 },
  );
}

/** Enter, hover, drop — the whole sequence, because the highlight only
 *  appears after dragenter and the drop is only accepted after dragover. */
async function dropOnto(page: Page, selector: string, dt: unknown) {
  await page.dispatchEvent(selector, "dragenter", { dataTransfer: dt });
  await page.dispatchEvent(selector, "dragover", { dataTransfer: dt });
  await page.dispatchEvent(selector, "drop", { dataTransfer: dt });
}

test.describe("drag and drop", () => {
  test("a file dropped on the Files panel is attached to the task", async ({ page }) => {
    await signUp(page, uniqueEmail("dd"));
    const orgId = await createOrg(page, `Drop ${Date.now()}`);
    await createTask(page, orgId, "Drop target");
    await openTask(page, orgId, "Drop target");
    await openFilesPanel(page);

    const dt = await fileTransfer(page, "dropped.png", "image/png", PNG);
    const panel = '[aria-label="Files"]';

    // The highlight appears while it's over the panel…
    await page.dispatchEvent(panel, "dragenter", { dataTransfer: dt });
    await expect(page.getByText("Drop to attach to this task")).toBeVisible();

    await page.dispatchEvent(panel, "dragover", { dataTransfer: dt });
    await page.dispatchEvent(panel, "drop", { dataTransfer: dt });

    // …and the file lands, through the same three-step handshake as the button.
    await expect(
      page.getByRole("region", { name: "Files" }).getByRole("button", { name: "Open dropped.png" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Drop to attach to this task")).toHaveCount(0);
  });

  test("a file dropped on the composer is staged, not sent", async ({ page }) => {
    await signUp(page, uniqueEmail("dd"));
    const orgId = await createOrg(page, `Drop ${Date.now()}`);
    await createTask(page, orgId, "Composer drop");
    await openTask(page, orgId, "Composer drop");

    const dt = await fileTransfer(page, "reply.png", "image/png", PNG);
    await dropOnto(page, '[aria-label="Comment composer"]', dt);

    // Staged: uploaded and confirmed, waiting for a comment to belong to.
    await expect(page.getByRole("button", { name: "Remove reply.png" })).toBeVisible({
      timeout: 15_000,
    });
    // Nothing has been posted — dropping a file is not sending a message.
    await expect(page.getByText("No comments yet")).toBeVisible();

    await page.getByLabel("Write a comment").fill("Here it is");
    await page.getByRole("button", { name: "Comment" }).click();
    await expect(
      page.getByRole("region", { name: "Comments" }).getByRole("img", { name: "reply.png" }),
    ).toBeVisible();
  });

  test("dragging text over a panel does not offer to upload it", async ({ page }) => {
    await signUp(page, uniqueEmail("dd"));
    const orgId = await createOrg(page, `Drop ${Date.now()}`);
    await createTask(page, orgId, "Not a file");
    await openTask(page, orgId, "Not a file");
    await openFilesPanel(page);

    const dt = await page.evaluateHandle(() => {
      const dt = new DataTransfer();
      dt.setData("text/plain", "just some words");
      return dt;
    });
    await page.dispatchEvent('[aria-label="Files"]', "dragenter", { dataTransfer: dt });
    await expect(page.getByText("Drop to attach to this task")).toHaveCount(0);
  });

  test("the highlight survives moving across the panel's own children", async ({ page }) => {
    // The trap: `dragleave` fires when the pointer crosses onto a child, so a
    // naive implementation strobes as you move over the panel.
    await signUp(page, uniqueEmail("dd"));
    const orgId = await createOrg(page, `Drop ${Date.now()}`);
    await createTask(page, orgId, "Steady");
    await openTask(page, orgId, "Steady");
    await openFilesPanel(page);

    const dt = await fileTransfer(page, "steady.png", "image/png", PNG);
    const panel = '[aria-label="Files"]';
    const child = '[aria-label="Add a file"]';

    await page.dispatchEvent(panel, "dragenter", { dataTransfer: dt });
    await page.dispatchEvent(child, "dragenter", { dataTransfer: dt });
    await page.dispatchEvent(panel, "dragleave", { dataTransfer: dt });
    // Entered twice, left once — still inside.
    await expect(page.getByText("Drop to attach to this task")).toBeVisible();

    await page.dispatchEvent(child, "dragleave", { dataTransfer: dt });
    await expect(page.getByText("Drop to attach to this task")).toHaveCount(0);
  });
});
